"""API tests that mock out the heavy marker engine.

These verify the web layer (validation, job lifecycle, downloads) without needing
marker, PyTorch, or the multi-GB model stack installed.
"""

import time

import pytest
from fastapi.testclient import TestClient

from app import main, marker_runner


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Point the job manager at a clean temp dir for the test run.
    marker_runner.job_manager._data_dir = tmp_path
    # Pretend marker is installed.
    monkeypatch.setattr(main, "marker_available", lambda: True)
    return TestClient(main.app)


def _fake_convert(input_path, work_dir, options):
    """Stand-in for marker_runner.convert that writes a deterministic result."""
    text = f"# Transcribed\n\nForce OCR was {options.force_ocr}, LLM {options.use_llm}.\n"
    ext = marker_runner.FORMAT_EXTENSION[options.output_format]
    (work_dir / f"result.{ext}").write_text(text, encoding="utf-8")
    return {"text": text, "output_ext": ext, "images": [], "page_count": 1}


def _wait_done(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def test_health(client):
    body = client.get("/api/health").json()
    assert "marker_available" in body
    assert body["output_formats"] == ["markdown", "html", "json"]
    assert "llm" in body


def test_index_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "History Scanner" in res.text


def test_rejects_unsupported_extension(client):
    res = client.post(
        "/api/scan",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 400
    assert "Unsupported" in res.json()["detail"]


def test_rejects_empty_file(client):
    res = client.post(
        "/api/scan",
        files={"file": ("scan.png", b"", "image/png")},
    )
    assert res.status_code == 400


def test_full_scan_flow(client, monkeypatch):
    monkeypatch.setattr(marker_runner, "convert", _fake_convert)

    res = client.post(
        "/api/scan",
        files={"file": ("letter.png", b"fake-image-bytes", "image/png")},
        data={"force_ocr": "true", "use_llm": "false", "output_format": "markdown"},
    )
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    body = _wait_done(client, job_id)
    assert body["status"] == "done", body.get("error")
    assert "Transcribed" in body["text"]
    assert body["page_count"] == 1

    dl = client.get(f"/api/jobs/{job_id}/download")
    assert dl.status_code == 200
    assert b"Transcribed" in dl.content


def test_error_is_surfaced(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(marker_runner, "convert", boom)
    res = client.post(
        "/api/scan",
        files={"file": ("letter.png", b"bytes", "image/png")},
    )
    job_id = res.json()["job_id"]
    body = _wait_done(client, job_id)
    assert body["status"] == "error"
    assert "model exploded" in body["error"]


def test_job_not_found(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404
