"""Centralized application configuration.

Every tunable value (API key, model names, limits, paths) lives here and is
read from environment variables, so nothing is ever hardcoded in the agents.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CLAIM_STORE_DIR = DATA_DIR / "claims"
SAMPLE_DIR = DATA_DIR / "samples"

# Load a project-level .env and an optional backend/.env without overriding
# variables that already exist in the real environment.
load_dotenv(PROJECT_ROOT / ".env", override=False)
load_dotenv(BACKEND_DIR / ".env", override=False)


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_str(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env_str(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    return _env_str(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Application settings resolved from environment variables."""

    # --- Gemini ---------------------------------------------------------
    gemini_api_key: str = field(default_factory=lambda: _env_str("GEMINI_API_KEY", ""))
    #: Set to 1 to run the deterministic pipeline even when a key is present.
    #: Useful for demos, cost control and verifying the offline path.
    force_offline: bool = field(default_factory=lambda: _env_bool("FORCE_OFFLINE", False))

    # Gemini 3.x is the current generation: the 2.5 models are retired for new
    # API keys and now fail with 404 NOT_FOUND. Flash handles the fast
    # multimodal extraction work; the pro model is only worth its cost for the
    # consistency review, so it is opt-in via .env. All overridable.
    model_extraction: str = field(
        default_factory=lambda: _env_str("GEMINI_MODEL_EXTRACTION", "gemini-3.8-flash")
    )
    model_reasoning: str = field(
        default_factory=lambda: _env_str("GEMINI_MODEL_REASONING", "gemini-3.8-flash")
    )
    model_review: str = field(
        default_factory=lambda: _env_str("GEMINI_MODEL_REVIEW", "gemini-3.8-flash")
    )

    temperature_extraction: float = field(
        default_factory=lambda: _env_float("GEMINI_TEMPERATURE_EXTRACTION", 0.0)
    )
    temperature_reasoning: float = field(
        default_factory=lambda: _env_float("GEMINI_TEMPERATURE_REASONING", 0.1)
    )
    request_timeout: int = field(
        default_factory=lambda: _env_int("GEMINI_REQUEST_TIMEOUT", 180)
    )
    max_attempts: int = field(
        default_factory=lambda: _env_int("GEMINI_MAX_ATTEMPTS", 3)
    )

    # --- Uploads --------------------------------------------------------
    max_upload_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_MB", 20))
    max_documents_per_claim: int = field(
        default_factory=lambda: _env_int("MAX_DOCUMENTS_PER_CLAIM", 10)
    )
    allowed_mime_types: tuple[str, ...] = (
        "application/pdf",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/heic",
    )

    # --- Server ---------------------------------------------------------
    cors_origins: str = field(
        default_factory=lambda: _env_str(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        )
    )
    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO"))

    # --- Application ----------------------------------------------------
    app_name: str = field(default_factory=lambda: _env_str("APP_NAME", "ClaimGen AI"))
    app_version: str = field(default_factory=lambda: _env_str("APP_VERSION", "1.0.0"))
    persist_claims: bool = field(default_factory=lambda: _env_bool("PERSIST_CLAIMS", True))

    @property
    def gemini_configured(self) -> bool:
        if self.force_offline:
            return False
        key = self.gemini_api_key
        return bool(key) and not key.startswith("your_")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def public_config(self) -> dict:
        """Configuration safe to expose to the frontend (contains no secrets)."""
        return {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "ai_mode": "gemini" if self.gemini_configured else "offline_deterministic",
            "models": {
                "extraction": self.model_extraction,
                "reasoning": self.model_reasoning,
                "review": self.model_review,
            },
            "limits": {
                "max_upload_mb": self.max_upload_mb,
                "max_documents_per_claim": self.max_documents_per_claim,
                "allowed_mime_types": list(self.allowed_mime_types),
            },
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    for directory in (DATA_DIR, UPLOAD_DIR, CLAIM_STORE_DIR, SAMPLE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    return Settings()


settings = get_settings()

__all__ = [
    "Settings",
    "settings",
    "get_settings",
    "BACKEND_DIR",
    "PROJECT_ROOT",
    "DATA_DIR",
    "UPLOAD_DIR",
    "CLAIM_STORE_DIR",
    "SAMPLE_DIR",
]
