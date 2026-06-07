"""Runtime configuration, sourced from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    # Server
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _as_int(os.getenv("PORT"), 8000))

    # LLM enhancement (Claude by default)
    llm_service: str = field(
        default_factory=lambda: os.getenv(
            "MARKER_LLM_SERVICE", "marker.services.claude.ClaudeService"
        )
    )
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("CLAUDE_API_KEY")
    )
    claude_model_name: str = field(
        default_factory=lambda: os.getenv("CLAUDE_MODEL_NAME", "claude-sonnet-4-6")
    )

    # Default scan options (overridable per request from the UI)
    default_use_llm: bool = field(
        default_factory=lambda: _as_bool(os.getenv("DEFAULT_USE_LLM"), True)
    )
    default_force_ocr: bool = field(
        default_factory=lambda: _as_bool(os.getenv("DEFAULT_FORCE_OCR"), True)
    )

    # Limits / runtime
    max_upload_mb: int = field(
        default_factory=lambda: _as_int(os.getenv("MAX_UPLOAD_MB"), 50)
    )
    max_concurrent_jobs: int = field(
        default_factory=lambda: _as_int(os.getenv("MAX_CONCURRENT_JOBS"), 1)
    )
    torch_device: str | None = field(
        default_factory=lambda: os.getenv("TORCH_DEVICE") or None
    )
    data_dir: str = field(
        default_factory=lambda: os.getenv("DATA_DIR", "/tmp/history-scanner")
    )

    @property
    def llm_is_claude(self) -> bool:
        return "claude" in self.llm_service.lower()

    @property
    def llm_configured(self) -> bool:
        """Whether LLM enhancement can actually be used right now."""
        if self.llm_is_claude:
            return bool(self.anthropic_api_key)
        # Other services (Ollama, Gemini, etc.) manage their own credentials;
        # assume the operator configured them.
        return True

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
