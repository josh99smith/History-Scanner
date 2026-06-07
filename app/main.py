"""History Scanner web app – FastAPI backend wrapping the marker OCR engine."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)

from . import __version__
from .auth import COOKIE_NAME, COOKIE_MAX_AGE, check_password, cookie_is_valid, issue_cookie_value
from .config import settings
from .marker_runner import (
    SUPPORTED_OUTPUT_FORMATS,
    JobStatus,
    ScanOptions,
    job_manager,
    marker_available,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="History Scanner", version=__version__)

STATIC_DIR = Path(__file__).parent / "static"

# Paths reachable without a session when the password gate is on.
_PUBLIC_PATHS = {"/login", "/api/health", "/favicon.ico"}


def _is_secure(request: Request) -> bool:
    """True when the request reached us over HTTPS (directly or via a proxy)."""
    if request.url.scheme == "https":
        return True
    return request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    if not settings.auth_enabled or request.url.path in _PUBLIC_PATHS:
        return await call_next(request)
    if cookie_is_valid(request.cookies.get(COOKIE_NAME)):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Unauthorized. Please log in."}, status_code=401)
    return HTMLResponse(_login_page(), status_code=401)


def _login_page(error: str = "") -> str:
    return (STATIC_DIR / "login.html").read_text(encoding="utf-8").replace(
        "{{ERROR}}", error
    )


@app.get("/login", response_class=HTMLResponse)
def login_form() -> HTMLResponse:
    if not settings.auth_enabled:
        return HTMLResponse('<meta http-equiv="refresh" content="0; url=/">')
    return HTMLResponse(_login_page())


@app.post("/login")
def login_submit(request: Request, password: str = Form(...)) -> Response:
    if not check_password(password):
        return HTMLResponse(_login_page("Incorrect password."), status_code=401)
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        COOKIE_NAME,
        issue_cookie_value(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
    )
    return resp


@app.post("/logout")
def logout() -> Response:
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp

# Input types marker can handle (with the [full] extra installed).
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp",
    ".docx", ".pptx", ".xlsx", ".epub", ".html", ".htm",
}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse(
        {
            "version": __version__,
            "marker_available": marker_available(),
            "llm": {
                "service": settings.llm_service,
                "is_claude": settings.llm_is_claude,
                "configured": settings.llm_configured,
                "model": settings.claude_model_name if settings.llm_is_claude else None,
            },
            "defaults": {
                "use_llm": settings.default_use_llm and settings.llm_configured,
                "force_ocr": settings.default_force_ocr,
            },
            "output_formats": list(SUPPORTED_OUTPUT_FORMATS),
            "max_upload_mb": settings.max_upload_mb,
            "auth_enabled": settings.auth_enabled,
        }
    )


@app.post("/api/scan")
async def scan(
    file: UploadFile = File(...),
    use_llm: bool = Form(False),
    force_ocr: bool = Form(True),
    output_format: str = Form("markdown"),
    languages: str | None = Form(None),
) -> JSONResponse:
    if not marker_available():
        raise HTTPException(
            status_code=503,
            detail="The marker OCR engine is not installed. Run `pip install marker-pdf[full]`.",
        )

    filename = file.filename or "document"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or 'unknown'}'. "
            f"Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )

    if use_llm and not settings.llm_configured:
        raise HTTPException(
            status_code=400,
            detail="LLM enhancement is selected but no API key is configured. "
            "Set ANTHROPIC_API_KEY (or disable LLM enhancement).",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_upload_mb} MB limit.",
        )

    options = ScanOptions(
        use_llm=use_llm,
        force_ocr=force_ocr,
        output_format=output_format,
        languages=languages,
    )

    job = job_manager.submit(filename=filename, data=data, ext=ext, options=options)
    return JSONResponse({"job_id": job.id, "status": job.status.value}, status_code=202)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JSONResponse(job.public_dict())


@app.get("/api/jobs/{job_id}/images/{name}")
def job_image(job_id: str, name: str) -> FileResponse:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    image_path = (job.work_dir / "images" / Path(name).name).resolve()
    # Guard against path traversal.
    if not str(image_path).startswith(str((job.work_dir / "images").resolve())):
        raise HTTPException(status_code=400, detail="Invalid image path.")
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found.")
    return FileResponse(image_path)


@app.get("/api/jobs/{job_id}/download")
def job_download(job_id: str) -> FileResponse:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != JobStatus.DONE or not job.output_ext:
        raise HTTPException(status_code=409, detail="Result is not ready.")
    result_path = job.work_dir / f"result.{job.output_ext}"
    if not result_path.is_file():
        raise HTTPException(status_code=404, detail="Result file missing.")
    stem = Path(job.filename).stem or "document"
    return FileResponse(
        result_path,
        filename=f"{stem}.{job.output_ext}",
        media_type="application/octet-stream",
    )


def run() -> None:  # pragma: no cover - convenience entry point
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":  # pragma: no cover
    run()
