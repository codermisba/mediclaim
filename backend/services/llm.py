"""Provider-agnostic AI entry point.

The agents import this module instead of a specific vendor SDK, so the whole
pipeline can run on Hugging Face, on Google Gemini, or on neither. Callers only
ever need three things:

* :func:`ai_mode`      - ``huggingface`` / ``gemini`` / ``offline_deterministic``
* :func:`try_structured` - run a model, or degrade gracefully with a note
* :func:`schema_hint`  - JSON schema text embedded in prompts

Every failure type is :class:`~services.gemini.ModelError`, so retry policy and
UI hints stay identical across providers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence, Type, TypeVar

from pydantic import BaseModel

from config import settings
from services import gemini, hf
from services.gemini import ModelError, response_schema_for

logger = logging.getLogger("mediclaim.llm")

T = TypeVar("T", bound=BaseModel)

__all__ = [
    "ModelError",
    "ai_mode",
    "client_status",
    "configured_models",
    "get_client",
    "list_models",
    "response_schema_for",
    "run_structured",
    "schema_hint",
    "try_structured",
    "verify_models",
]


def configured_module():
    """The provider module for this process, or ``None`` when offline."""
    if settings.force_offline or settings.ai_provider == "offline":
        return None
    if settings.ai_provider == "gemini":
        return gemini if settings.gemini_configured else None
    return hf if settings.hf_configured else None


def _offline_status() -> Dict[str, str]:
    if settings.force_offline:
        message = "FORCE_OFFLINE=1 - running the deterministic engine only."
    elif settings.ai_provider == "offline":
        message = "AI_PROVIDER=offline - running the deterministic engine only."
    elif settings.ai_provider == "gemini":
        message = (
            "GEMINI_API_KEY is not configured - running without AI calls. "
            "Add it to .env (see .env.example) and restart the backend."
        )
    else:
        message = (
            "HF_TOKEN is not configured - running without AI calls. "
            "Add HF_TOKEN to .env (see .env.example) and restart the backend."
        )
    return {"mode": "offline_deterministic", "message": message}


def client_status() -> Dict[str, str]:
    """Human-readable status used by /api/health and error messages."""
    module = configured_module()
    if module is None:
        return _offline_status()
    return module.client_status()


def ai_mode() -> str:
    return client_status()["mode"]


def configured_models() -> List[str]:
    return settings.configured_models


async def verify_models(force: bool = False) -> Dict[str, Dict[str, str]]:
    """Probe every configured model in a worker thread (the probe blocks on I/O)."""
    module = configured_module()
    if module is None:
        return {}
    return await asyncio.to_thread(module.verify_models, force)


def get_client():
    module = configured_module()
    return module.get_client() if module is not None else None


async def list_models() -> List[str]:
    module = configured_module()
    if module is None:
        return []
    return await module.list_models()


def schema_hint(model: Type[BaseModel]) -> str:
    """Compact schema description embedded in prompts (shared by providers)."""
    return gemini.schema_hint(model)


async def run_structured(**kwargs: Any) -> Any:
    module = configured_module()
    if module is None:
        raise ModelError(
            "No AI provider is configured.",
            hint="Set HF_TOKEN in .env (or GEMINI_API_KEY with AI_PROVIDER=gemini) "
            "and restart the backend.",
            kind="auth",
        )
    return await module.run_structured(**kwargs)


async def try_structured(**kwargs: Any) -> tuple[Optional[Any], str]:
    """Run the model, or return ``(None, note)`` when it degrades gracefully."""
    module = configured_module()
    if module is None:
        return None, (
            "No AI provider is configured, so the deterministic engine was used. "
            "Results are flagged for human review."
        )
    return await module.try_structured(**kwargs)
