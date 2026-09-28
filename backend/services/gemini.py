"""Shared Gemini plumbing: client creation, schema sanitising, structured calls.

Every AI call in the application goes through :func:`run_structured`. Agents
never talk to the SDK directly, which keeps model names, retries, timeouts and
error messages in exactly one place.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Type, TypeVar

from pydantic import BaseModel, ValidationError

from config import settings

logger = logging.getLogger("mediclaim.gemini")

#: Exponential backoff for transient (overloaded / malformed-response) failures.
#: Immediate retries against a congested endpoint just burn quota, so wait.
RETRY_BASE_DELAY = 2.0
RETRY_MAX_DELAY = 20.0

#: /api/health is polled by the UI, so the live model probe is cached to avoid
#: spending rate-limit quota just to render a status banner.
MODEL_CHECK_TTL = 300.0
_model_check_cache: Dict[str, Dict[str, str]] = {}
_model_check_time: float = 0.0

T = TypeVar("T", bound=BaseModel)

_client = None
_client_lock = threading.Lock()
_client_error: Optional[str] = None

# JSON-schema keywords Gemini's structured-output API does not accept.
_UNSUPPORTED_SCHEMA_KEYS = {
    "title",
    "default",
    "examples",
    "additionalProperties",
    "$schema",
    "$id",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "const",
    "anyOf",
    "oneOf",
    "allOf",
    "not",
    "patternProperties",
    "dependentRequired",
}


class GeminiError(RuntimeError):
    """Raised when a Gemini call cannot produce a usable structured payload.

    ``kind`` drives both the retry policy and the hint shown in the UI:

    ``auth``       the key is missing/wrong            -> never retry
    ``model``      the model is retired or not enabled -> never retry
    ``quota``      rate limit / out of quota           -> never retry
    ``overloaded`` transient 500/503/UNAVAILABLE        -> retry with backoff
    ``content``    empty or non-JSON response          -> retry, then give up
    ``unknown``    anything else                       -> retry
    """

    def __init__(
        self,
        message: str,
        *,
        hint: str = "",
        model: str = "",
        kind: str = "unknown",
    ):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.model = model
        self.kind = kind

    @property
    def retryable(self) -> bool:
        return self.kind in {"overloaded", "content", "unknown"}

    def to_dict(self) -> Dict[str, str]:
        return {
            "detail": self.message,
            "hint": self.hint,
            "code": "gemini_error",
            "kind": self.kind,
            "model": self.model,
        }


#: Kinds that will never succeed on a retry, so the loop stops immediately.
FATAL_KINDS = {"auth", "model", "quota"}

#: Kinds where a deterministic fallback is a sensible automatic response: the
#: key is fine and the model exists, we simply cannot call it right now.
DEGRADE_KINDS = {"quota", "overloaded"}


def classify_exception(exc: Exception, model_name: str = "") -> GeminiError:
    """Turn an arbitrary SDK/network exception into a typed, actionable error.

    Google returns a very consistent error body, so classification is done on
    the status code first and the message only as a fallback for older SDK
    versions that do not expose ``code``.
    """
    message = str(exc)
    lowered = message.lower()

    code = ""
    for attr in ("code", "status_code", "status"):
        value = getattr(exc, attr, None)
        if value is not None:
            code = str(getattr(value, "value", value)).upper()
            break

    def error(code_hint: str, kind: str, hint: str, summary: str) -> GeminiError:
        return GeminiError(f"{summary} (model={model_name or 'unknown'}).", hint=hint,
                           model=model_name, kind=kind)

    if code in {"401", "403"} or "api key not valid" in lowered or "api_key" in lowered:
        return error(code, "auth",
                     "Verify GEMINI_API_KEY in your .env file, then restart the backend.",
                     "Gemini rejected the API key")

    if code == "404" or "not_found" in lowered or "no longer available" in lowered:
        return error(code, "model",
                     "This model has been retired or is not enabled for your account. "
                     "Change the GEMINI_MODEL_* values in .env (call "
                     "GET /api/health for the suggested model) and restart the backend.",
                     "Gemini model is not available")

    if code == "429" or "resource_exhausted" in lowered or "quota" in lowered:
        return error(code, "quota",
                     "Your Gemini quota for this model is exhausted or rate limited. "
                     "Wait for the quota window to reset, use a different model, or "
                     "unset GEMINI_API_KEY to run in deterministic offline mode.",
                     "Gemini quota exhausted")

    if code in {"500", "502", "503", "504"} or "unavailable" in lowered or "overloaded" in lowered:
        return error(code, "overloaded",
                     "The Gemini endpoint is temporarily overloaded. This is transient - "
                     "retry in a few minutes.",
                     "Gemini is temporarily overloaded")

    if code == "400" or "invalid_argument" in lowered or "invalid request" in lowered:
        return error(code, "content",
                     "Gemini rejected the request payload. Check the uploaded documents "
                     "and the model configuration.",
                     "Gemini rejected the request")

    return GeminiError(f"Gemini request failed: {message}", model=model_name)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def get_client():
    """Lazily create a single ``google.genai`` client for the process."""
    global _client, _client_error
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        if not settings.gemini_configured:
            _client_error = (
                "GEMINI_API_KEY is not set. Add it to your .env file "
                "(see .env.example) and restart the backend."
            )
            return None
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - dependency missing
            _client_error = (
                "The google-genai package is not installed. Run: "
                "py -m pip install -r requirements.txt"
            )
            logger.error(_client_error)
            return None
        try:
            _client = genai.Client(api_key=settings.gemini_api_key)
        except Exception as exc:  # pragma: no cover - misconfiguration
            _client_error = f"Could not initialise the Gemini client: {exc}"
            logger.error(_client_error)
            return None
    return _client


def verify_models(force: bool = False) -> Dict[str, Dict[str, str]]:
    """Send one tiny real request per configured model.

    A key being present proves nothing: Google happily accepts a key whose
    model names have been retired, which would otherwise show a reassuring
    "connected" health check while every pipeline call fails with 404. This
    does the smallest possible call so the health endpoint tells the truth.

    Results are cached because /api/health is polled by the UI on every page
    load - probing live each time would burn rate-limit quota and could itself
    trigger the 429 it is supposed to report.
    """
    global _model_check_cache, _model_check_time

    client = get_client()
    if client is None:
        return {}

    if (
        not force
        and _model_check_cache
        and (time.monotonic() - _model_check_time) < MODEL_CHECK_TTL
    ):
        return _model_check_cache

    results: Dict[str, Dict[str, str]] = {}

    def probe(model_name: str) -> None:
        try:
            client.models.generate_content(
                model=model_name,
                contents="Reply with OK.",
                config={"max_output_tokens": 8},
            )
            results[model_name] = {"ok": "true", "detail": "reachable"}
        except Exception as exc:  # noqa: BLE001
            error = classify_exception(exc, model_name)
            results[model_name] = {
                "ok": "false",
                "kind": error.kind,
                "detail": error.message,
                "hint": error.hint,
            }

    for name in dict.fromkeys(
        [settings.model_extraction, settings.model_reasoning, settings.model_review]
    ):
        probe(name)

    _model_check_cache = results
    _model_check_time = time.monotonic()
    return results


def client_status() -> Dict[str, str]:
    """Human-readable status used by /api/health and error messages."""
    if not settings.gemini_configured:
        return {
            "mode": "offline_deterministic",
            "message": "GEMINI_API_KEY is not configured - running without AI calls.",
        }
    if get_client() is None:
        return {"mode": "offline_deterministic", "message": _client_error or "Gemini unavailable."}
    return {"mode": "gemini", "message": "Gemini connected."}


def ai_mode() -> str:
    return client_status()["mode"]


# ---------------------------------------------------------------------------
# Schema handling
# ---------------------------------------------------------------------------


def _sanitize_schema(node: Any) -> Any:
    """Recursively strip JSON-schema keywords Gemini rejects."""
    if isinstance(node, dict):
        cleaned: Dict[str, Any] = {}
        for key, value in node.items():
            if key in _UNSUPPORTED_SCHEMA_KEYS:
                continue
            cleaned[key] = _sanitize_schema(value)
        return cleaned
    if isinstance(node, list):
        return [_sanitize_schema(item) for item in node]
    return node


def response_schema_for(model: Type[BaseModel]) -> Dict[str, Any]:
    """Gemini-safe JSON schema for a Pydantic model."""
    return _sanitize_schema(model.model_json_schema())


def schema_hint(model: Type[BaseModel]) -> str:
    """Compact schema description embedded in prompts (belt and braces)."""
    return json.dumps(response_schema_for(model), indent=2)


# ---------------------------------------------------------------------------
# Content building
# ---------------------------------------------------------------------------


def _image_part(path: str, mime_type: str):
    from google.genai import types

    with open(path, "rb") as handle:
        data = handle.read()
    return types.Part.from_bytes(data=data, mime_type=mime_type)


def _strip_data_url(data_url: str) -> tuple[str, str]:
    """``data:image/png;base64,AAAA`` -> ``("image/png", "AAAA")``."""
    header, _, payload = data_url.partition(",")
    mime = "image/png"
    match = re.search(r"data:([\w./+-]+)", header)
    if match:
        mime = match.group(1)
    return mime, payload


def build_contents(
    prompt: str, documents: Optional[Sequence[Dict[str, str]]] = None
):
    """Assemble multimodal contents: prompt text + inline documents.

    ``documents`` items look like ``{"path": ..., "mime_type": ...}`` or
    ``{"data_url": "data:image/png;base64,..."}``. Gemini receives the raw
    bytes directly - there is no separate OCR stage.
    """
    from google.genai import types

    parts: List[Any] = [types.Part.from_text(text=prompt)]
    for document in documents or []:
        try:
            if document.get("data_url"):
                mime, payload = _strip_data_url(document["data_url"])
                parts.append(
                    types.Part.from_bytes(
                        data=base64.b64decode(payload), mime_type=mime
                    )
                )
            elif document.get("path"):
                parts.append(_image_part(document["path"], document.get("mime_type", "")))
        except Exception as exc:  # pragma: no cover - unreadable attachment
            logger.warning("Skipping attachment %s: %s", document.get("filename"), exc)
    return [types.Content(role="user", parts=parts)]


# ---------------------------------------------------------------------------
# Structured call
# ---------------------------------------------------------------------------


def _config(model_cls: Type[BaseModel], temperature: float, system_instruction: str):
    from google.genai import types

    return types.GenerateContentConfig(
        temperature=temperature,
        top_p=0.95,
        max_output_tokens=8192,
        response_mime_type="application/json",
        response_schema=response_schema_for(model_cls),
        system_instruction=system_instruction,
        http_options=types.HttpOptions(timeout=settings.request_timeout * 1000),
    )


def _coerce(text: str, model_cls: Type[T], model_name: str) -> T:
    """Parse and validate a JSON response, tolerating markdown fences."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    if not cleaned:
        raise GeminiError("Gemini returned an empty response.", model=model_name)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiError(
            f"Gemini returned invalid JSON: {exc.msg} (line {exc.lineno}).",
            hint="This is usually a transient model issue - retry the step.",
            model=model_name,
        ) from exc
    if not isinstance(payload, dict):
        raise GeminiError("Gemini returned JSON that is not an object.", model=model_name)
    try:
        return model_cls.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ())) or "(root)"
        raise GeminiError(
            f"Gemini response did not match {model_cls.__name__} at '{location}'.",
            hint=first.get("msg", ""),
            model=model_name,
        ) from exc


async def run_structured(
    *,
    model_name: str,
    system_instruction: str,
    prompt: str,
    response_model: Type[T],
    documents: Optional[Sequence[Dict[str, str]]] = None,
    temperature: Optional[float] = None,
    max_attempts: Optional[int] = None,
) -> T:
    """Call Gemini once (with retries) and return a validated ``response_model``.

    The synchronous client is used inside a worker thread so FastAPI's event
    loop is never blocked and we stay compatible across SDK versions.
    """
    client = get_client()
    if client is None:
        raise GeminiError(
            _client_error or "Gemini is not available.",
            hint="Set GEMINI_API_KEY in .env and restart the backend.",
        )

    if temperature is None:
        temperature = (
            settings.temperature_reasoning
            if model_name == settings.model_reasoning
            else settings.temperature_extraction
        )
    attempts = max_attempts or settings.max_attempts
    contents = build_contents(prompt, documents)
    config = _config(response_model, temperature, system_instruction)
    last_error: Optional[GeminiError] = None

    for attempt in range(1, attempts + 1):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=contents,
                config=config,
            )
            text = getattr(response, "text", None)
            if not text:
                block = getattr(response, "candidates", [None])[0]
                reason = getattr(getattr(block, "finish_reason", None), "__str__", lambda: "")()
                raise GeminiError(
                    "Gemini returned no text content"
                    + (f" (finish_reason={reason})." if reason else "."),
                    hint="Check the prompt for content that triggers safety filters.",
                    model=model_name,
                    kind="content",
                )
            return _coerce(text, response_model, model_name)
        except GeminiError as exc:
            last_error = exc
        except Exception as exc:  # network, quota, unknown SDK errors
            last_error = classify_exception(exc, model_name)

        # A retired model, a bad key or an exhausted quota will fail identically
        # on every retry, so stop immediately and let the user fix the cause.
        if last_error.kind in FATAL_KINDS:
            logger.error("Gemini call failed fatally (%s): %s", last_error.kind, last_error.message)
            raise last_error

        if attempt < attempts:
            delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
            logger.warning(
                "Gemini attempt %s/%s failed for %s (%s); retrying in %.1fs: %s",
                attempt,
                attempts,
                model_name,
                last_error.kind,
                delay,
                last_error.message,
            )
            await asyncio.sleep(delay)

    assert last_error is not None
    raise last_error


async def try_structured(
    **kwargs: Any,
) -> tuple[Optional[Any], str]:
    """Call :func:`run_structured`, degrading gracefully when Gemini is reachable
    but temporarily unusable (quota exhausted, endpoint overloaded).

    Every agent computes its deterministic result *before* attempting the model
    call, so when this returns ``(None, note)`` the caller simply keeps that
    result and reports ``used_ai = False``. Losing a quota window should not
    throw away the document analysis the model already completed, and it must
    never be silently hidden - the returned note is surfaced in the UI.

    Real misconfiguration (retired model, bad key) still raises, because a
    silent fallback there would hide a bug the user has to fix.
    """
    try:
        return await run_structured(**kwargs), ""
    except GeminiError as exc:
        if exc.kind not in DEGRADE_KINDS:
            raise
        note = (
            f"Gemini was unavailable for this stage ({exc.kind}: {exc.message}) "
            "so the deterministic engine was used instead. Results are still "
            "flagged for human review."
        )
        logger.warning("Degrading to deterministic mode: %s", exc.message)
        return None, note


async def list_models() -> List[str]:
    """Best-effort model listing, used by the health endpoint."""
    client = get_client()
    if client is None:
        return []

    def _list() -> List[str]:
        page = client.models.list()
        return [model.name.replace("models/", "") for model in page]

    try:
        return await asyncio.to_thread(_list)
    except Exception:  # pragma: no cover - informational only
        return []
