"""Thin wrapper around the `marker` library plus a small in-memory job manager.

marker is heavy: it loads several deep-learning models (~a few GB) and a single
conversion can take seconds to minutes. So we:

  * load the models exactly once, lazily, on the first conversion;
  * run conversions on a bounded thread pool (default: one at a time, because
    each marker worker wants ~5GB of VRAM);
  * expose conversions as polled "jobs" so the web UI stays responsive.

The marker imports are deliberately done *inside* functions so that the web app
(and the test-suite) can import this module without marker — and its multi-GB
model stack — being installed.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .config import settings

logger = logging.getLogger("history_scanner.marker")

# Output formats marker can render. Markdown is the friendly default.
SUPPORTED_OUTPUT_FORMATS = ("markdown", "html", "json")
FORMAT_EXTENSION = {"markdown": "md", "html": "html", "json": "json"}


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


@dataclass
class ScanOptions:
    """Per-document conversion options chosen in the UI."""

    use_llm: bool = False
    force_ocr: bool = True
    output_format: str = "markdown"
    # Comma-separated hint languages for the OCR model, e.g. "en,fr,la".
    languages: str | None = None

    def normalized(self) -> "ScanOptions":
        fmt = self.output_format if self.output_format in SUPPORTED_OUTPUT_FORMATS else "markdown"
        langs = self.languages.strip() if self.languages else None
        return ScanOptions(
            use_llm=bool(self.use_llm),
            force_ocr=bool(self.force_ocr),
            output_format=fmt,
            languages=langs or None,
        )


@dataclass
class Job:
    id: str
    filename: str
    input_path: Path
    work_dir: Path
    options: ScanOptions
    status: JobStatus = JobStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    # Result payload (populated when status == DONE)
    text: str | None = None
    output_ext: str | None = None
    images: list[str] = field(default_factory=list)
    page_count: int | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status.value,
            "options": {
                "use_llm": self.options.use_llm,
                "force_ocr": self.options.force_ocr,
                "output_format": self.options.output_format,
                "languages": self.options.languages,
            },
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": (
                round(self.finished_at - self.started_at, 1)
                if self.started_at and self.finished_at
                else None
            ),
            "error": self.error,
            "page_count": self.page_count,
            "images": self.images,
            # Only ship the (potentially large) text once the job is done.
            "text": self.text if self.status == JobStatus.DONE else None,
        }


# ── Lazy model loading ────────────────────────────────────────────────────────

_models: Any = None
_models_lock = threading.Lock()


def get_models() -> Any:
    """Load marker's model artifacts once and cache them for the process."""
    global _models
    if _models is None:
        with _models_lock:
            if _models is None:
                if settings.torch_device:
                    import os

                    os.environ.setdefault("TORCH_DEVICE", settings.torch_device)
                logger.info("Loading marker models (first run downloads several GB)…")
                from marker.models import create_model_dict

                _models = create_model_dict()
                logger.info("marker models loaded.")
    return _models


def marker_available() -> bool:
    try:
        import marker  # noqa: F401

        return True
    except Exception:  # pragma: no cover - depends on install
        return False


# ── Conversion ────────────────────────────────────────────────────────────────


def _build_config(options: ScanOptions) -> dict[str, Any]:
    config: dict[str, Any] = {
        "output_format": options.output_format,
        "force_ocr": options.force_ocr,
    }
    if options.languages:
        config["languages"] = options.languages
    if options.use_llm:
        config["use_llm"] = True
        config["llm_service"] = settings.llm_service
        if settings.llm_is_claude:
            if not settings.anthropic_api_key:
                raise RuntimeError(
                    "LLM enhancement requested but ANTHROPIC_API_KEY is not set."
                )
            config["claude_api_key"] = settings.anthropic_api_key
            config["claude_model_name"] = settings.claude_model_name
    return config


def convert(input_path: Path, work_dir: Path, options: ScanOptions) -> dict[str, Any]:
    """Run a single marker conversion. Returns a result dict.

    This is a blocking call meant to run on a worker thread.
    """
    from marker.config.parser import ConfigParser
    from marker.converters.pdf import PdfConverter
    from marker.output import text_from_rendered

    config = _build_config(options)
    config_parser = ConfigParser(config)

    converter = PdfConverter(
        config=config_parser.generate_config_dict(),
        artifact_dict=get_models(),
        processor_list=config_parser.get_processors(),
        renderer=config_parser.get_renderer(),
        llm_service=config_parser.get_llm_service(),
    )

    rendered = converter(str(input_path))
    text, ext, images = text_from_rendered(rendered)

    image_dir = work_dir / "images"
    saved_images: list[str] = []
    if images:
        image_dir.mkdir(parents=True, exist_ok=True)
        for name, image in images.items():
            safe_name = Path(name).name
            try:
                image.save(image_dir / safe_name)
                saved_images.append(safe_name)
            except Exception:  # pragma: no cover - defensive
                logger.warning("Failed to save extracted image %s", name)

    page_count = _extract_page_count(rendered)

    # Persist the primary text output for later download.
    out_ext = FORMAT_EXTENSION.get(options.output_format, "txt")
    (work_dir / f"result.{out_ext}").write_text(text, encoding="utf-8")

    return {
        "text": text,
        "output_ext": out_ext,
        "images": saved_images,
        "page_count": page_count,
    }


def _extract_page_count(rendered: Any) -> int | None:
    meta = getattr(rendered, "metadata", None)
    if isinstance(meta, dict):
        stats = meta.get("page_stats")
        if isinstance(stats, list):
            return len(stats)
        if isinstance(meta.get("page_count"), int):
            return meta["page_count"]
    return None


# ── Job manager ───────────────────────────────────────────────────────────────


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, settings.max_concurrent_jobs),
            thread_name_prefix="marker",
        )
        self._data_dir = Path(settings.data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def submit(
        self, filename: str, data: bytes, ext: str, options: ScanOptions
    ) -> Job:
        job_id = uuid.uuid4().hex
        work_dir = self._data_dir / job_id
        work_dir.mkdir(parents=True, exist_ok=True)

        # Persist the upload *before* scheduling the worker so the conversion
        # thread can never race ahead of the file being on disk.
        input_path = work_dir / f"input{ext}"
        input_path.write_bytes(data)

        job = Job(
            id=job_id,
            filename=filename,
            input_path=input_path,
            work_dir=work_dir,
            options=options.normalized(),
        )
        with self._lock:
            self._jobs[job_id] = job
        self._executor.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _run(self, job: Job) -> None:
        job.status = JobStatus.PROCESSING
        job.started_at = time.time()
        logger.info("Job %s started (%s)", job.id, job.filename)
        try:
            result = convert(job.input_path, job.work_dir, job.options)
            job.text = result["text"]
            job.output_ext = result["output_ext"]
            job.images = result["images"]
            job.page_count = result["page_count"]
            job.status = JobStatus.DONE
            logger.info("Job %s done", job.id)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            job.status = JobStatus.ERROR
            job.error = str(exc) or exc.__class__.__name__
            logger.error("Job %s failed: %s\n%s", job.id, exc, traceback.format_exc())
        finally:
            job.finished_at = time.time()


# A module-level singleton the web app uses.
job_manager = JobManager()
