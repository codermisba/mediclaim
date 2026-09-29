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


#: Default model for the Hugging Face provider. Qwen 72B is served by HF
#: Inference Providers with a generous free tier and follows JSON instructions
#: reliably, which matters because the agents validate every response against a
#: Pydantic schema. Override per role with HF_MODEL_* in .env.
DEFAULT_HF_MODEL = "Qwen/Qwen2.5-72B-Instruct"

#: Alternative HF models worth trying if the default is busy or unavailable.
#: Check GET /api/health after changing - it probes the live endpoint.
HF_MODEL_SUGGESTIONS = (
    "Qwen/Qwen2.5-72B-Instruct",
    "deepseek-ai/DeepSeek-V3-0324",
    "meta-llama/Llama-3.3-70B-Instruct",
    "mistralai/Mistral-Small-24B-Instruct-2501",
    "google/gemma-3-27b-it",
)


@dataclass(frozen=True)
class Settings:
    """Application settings resolved from environment variables."""

    # --- AI provider ----------------------------------------------------
    # ``huggingface`` (default), ``gemini`` or ``offline``. ``offline`` forces
    # the deterministic reader even when a token is present.
    ai_provider: str = field(
        default_factory=lambda: _env_str("AI_PROVIDER", "huggingface").lower()
    )
    #: Set to 1 to run the deterministic pipeline even when a token is present.
    #: Useful for demos, cost control and verifying the offline path.
    force_offline: bool = field(default_factory=lambda: _env_bool("FORCE_OFFLINE", False))

    # --- Hugging Face (default provider) --------------------------------
    hf_token: str = field(default_factory=lambda: _env_str("HF_TOKEN", ""))
    #: OpenAI-compatible chat endpoint exposed by HF Inference Providers.
    hf_base_url: str = field(
        default_factory=lambda: _env_str("HF_BASE_URL", "https://router.huggingface.co/v1")
    )
    hf_model_extraction: str = field(
        default_factory=lambda: _env_str("HF_MODEL_EXTRACTION", DEFAULT_HF_MODEL)
    )
    hf_model_reasoning: str = field(
        default_factory=lambda: _env_str("HF_MODEL_REASONING", DEFAULT_HF_MODEL)
    )
    hf_model_review: str = field(
        default_factory=lambda: _env_str("HF_MODEL_REVIEW", DEFAULT_HF_MODEL)
    )

    # --- Google Gemini (optional alternative) ---------------------------
    gemini_api_key: str = field(default_factory=lambda: _env_str("GEMINI_API_KEY", ""))
    #: Gemini 3.x is current generation; 2.5 is retired for new keys (404).
    gemini_model_extraction: str = field(
        default_factory=lambda: _env_str("GEMINI_MODEL_EXTRACTION", "gemini-3.8-flash")
    )
    gemini_model_reasoning: str = field(
        default_factory=lambda: _env_str("GEMINI_MODEL_REASONING", "gemini-3.8-flash")
    )
    gemini_model_review: str = field(
        default_factory=lambda: _env_str("GEMINI_MODEL_REVIEW", "gemini-3.8-flash")
    )

    temperature_extraction: float = field(
        default_factory=lambda: _env_float(
            "AI_TEMPERATURE_EXTRACTION", _env_float("GEMINI_TEMPERATURE_EXTRACTION", 0.0)
        )
    )
    temperature_reasoning: float = field(
        default_factory=lambda: _env_float(
            "AI_TEMPERATURE_REASONING", _env_float("GEMINI_TEMPERATURE_REASONING", 0.1)
        )
    )
    request_timeout: int = field(
        default_factory=lambda: _env_int("AI_REQUEST_TIMEOUT", _env_int("GEMINI_REQUEST_TIMEOUT", 180))
    )
    max_attempts: int = field(
        default_factory=lambda: _env_int("AI_MAX_ATTEMPTS", _env_int("GEMINI_MAX_ATTEMPTS", 3))
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
            "CORS_ORIGINS", "http://localhost:5174,http://127.0.0.1:5174"
        )
    )
    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO"))

    # --- Application ----------------------------------------------------
    app_name: str = field(default_factory=lambda: _env_str("APP_NAME", "ClaimGen AI"))
    app_version: str = field(default_factory=lambda: _env_str("APP_VERSION", "1.0.0"))
    persist_claims: bool = field(default_factory=lambda: _env_bool("PERSIST_CLAIMS", True))

    @property
    def gemini_configured(self) -> bool:
        if self.force_offline or self.ai_provider not in {"gemini", "huggingface"}:
            return False
        key = self.gemini_api_key
        return self.ai_provider == "gemini" and bool(key) and not key.startswith("your_")

    @property
    def hf_configured(self) -> bool:
        """True only when HF is the selected provider *and* a real token exists."""
        if self.force_offline or self.ai_provider != "huggingface":
            return False
        token = self.hf_token
        return bool(token) and not token.startswith("your_")

    @property
    def ai_mode(self) -> str:
        """``huggingface`` / ``gemini`` / ``offline_deterministic``.

        This is the single value the pipeline and UI key off, so a stage that
        never reached a model is always distinguishable from one that did.
        """
        if self.hf_configured:
            return "huggingface"
        if self.gemini_configured:
            return "gemini"
        return "offline_deterministic"

    @property
    def model_extraction(self) -> str:
        return (
            self.gemini_model_extraction
            if self.ai_provider == "gemini"
            else self.hf_model_extraction
        )

    @property
    def model_reasoning(self) -> str:
        return (
            self.gemini_model_reasoning
            if self.ai_provider == "gemini"
            else self.hf_model_reasoning
        )

    @property
    def model_review(self) -> str:
        return self.gemini_model_review if self.ai_provider == "gemini" else self.hf_model_review

    @property
    def configured_models(self) -> list[str]:
        """Unique model names that will actually be called, in call order."""
        return list(dict.fromkeys([self.model_extraction, self.model_reasoning, self.model_review]))


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
            "ai_mode": self.ai_mode,
            "provider": self.ai_provider,
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
    "DEFAULT_HF_MODEL",
    "HF_MODEL_SUGGESTIONS",
    "BACKEND_DIR",
    "PROJECT_ROOT",
    "DATA_DIR",
    "UPLOAD_DIR",
    "CLAIM_STORE_DIR",
    "SAMPLE_DIR",
]
