"""Hugging Face Inference Providers backend.

Everything here mirrors :mod:`services.gemini` one-for-one so the agents can
swap providers by changing a single import. HF exposes an OpenAI-compatible
chat endpoint at ``https://router.huggingface.co/v1`` - we POST to it directly
instead of through a SDK so status codes (401 / 404 / 429 / 503) reach
:func:`classify_exception` unchanged and every failure can be typed.

Two practical differences from Gemini drive the design:

* **No native structured output.** The JSON schema is embedded in the prompt
  and the response is parsed by :func:`_coerce`, which tolerates markdown
  fences and validates against the Pydantic model.
* **Not every free model is multimodal.** PDFs are converted to extracted text
  before the call; images are sent as OpenAI ``image_url`` parts and, if the
  chosen model rejects them, one image-free retry is attempted automatically.
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

import requests
from pydantic import BaseModel, ValidationError

from config import HF_MODEL_SUGGESTIONS, settings
from services.gemini import (
    MODEL_CHECK_TTL,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    ModelError,
    response_schema_for,
)

logger = logging.getLogger("mediclaim.hf")

T = TypeVar("T", bound=BaseModel)

#: HF Inference Providers can be flaky between providers, so identical to the
#: Gemini path: exponential backoff rather than hammering the endpoint.
_client_lock = threading.Lock()
_model_check_cache: Dict[str, Dict[str, str]] = {}
_model_check_time: float = 0.0


class _HttpError(Exception):
    """Transport-level failure carrying the HTTP status the server returned."""

    def __init__(self, status: int, text: str):
        super().__init__(f"HTTP {status}: {text}")
        self.status = status
        self.text = text


def _endpoint() -> str:
    return settings.hf_base_url.rstrip("/") + "/chat/completions"


def _suggest() -> str:
    return ", ".join(HF_MODEL_SUGGESTIONS[:3])


def classify_exception(exc: Exception, model_name: str = "") -> ModelError:
    """Map an HTTP/transport failure onto a typed, actionable :class:`ModelError`."""
    if isinstance(exc, _HttpError):
        status, text = exc.status, exc.text
    else:
        status = int(getattr(exc, "status_code", 0) or 0)
        text = str(exc)

    lowered = text.lower()

    def error(kind: str, hint: str, summary: str) -> ModelError:
        return ModelError(
            f"{summary} (model={model_name or 'unknown'}).",
            hint=hint,
            model=model_name,
            kind=kind,
            code="hf_error",
        )

    if status in {401, 403} or "invalid token" in lowered or "invalid username" in lowered:
        return error(
            "auth",
            "Verify HF_TOKEN in your .env file (https://huggingface.co/settings/tokens, "
            "a 'Fine-grained' or 'Read' token works), then restart the backend.",
            "Hugging Face rejected the token",
        )

    if status == 404 or "not found" in lowered or "does not exist" in lowered:
        return error(
            "model",
            f"Model '{model_name}' is not served on Hugging Face right now. "
            f"Change HF_MODEL_EXTRACTION / HF_MODEL_REASONING / HF_MODEL_REVIEW in "
            f".env to one of: {_suggest()}. Then restart the backend.",
            "Hugging Face model is not available",
        )

    if status == 429 or "rate limit" in lowered or "quota" in lowered:
        return error(
            "quota",
            "Hugging Face is rate limiting this token or model. Wait for the window "
            "to reset, switch HF_MODEL_* to a less busy model, or set AI_PROVIDER=offline.",
            "Hugging Face quota exhausted",
        )

    if status in {500, 502, 503, 504} or "not running" in lowered or "unavailable" in lowered:
        return error(
            "overloaded",
            "The Hugging Face provider is temporarily overloaded. This is transient - "
            "retry in a few minutes.",
            "Hugging Face is temporarily overloaded",
        )

    if status == 400:
        # A text-only model rejecting an image is the common case here; the
        # caller downgrades this to an image-free retry before failing.
        if any(word in lowered for word in ("image", "vision", "multimodal", "content type")):
            return ModelError(
                f"The model {model_name} rejected an attachment: {text[:160]}",
                hint="Set HF_MODEL_EXTRACTION to a vision model, or leave the images out.",
                model=model_name,
                kind="content",
                code="hf_error",
            )
        return error(
            "content",
            "Hugging Face rejected the request payload. Check the uploaded documents "
            "and the HF_MODEL_* configuration.",
            "Hugging Face rejected the request",
        )

    return ModelError(
        f"Hugging Face request failed: {text[:300]}",
        model=model_name,
        kind="unknown",
        code="hf_error",
    )


def _post(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous POST. Run via ``asyncio.to_thread`` so the loop never blocks."""
    if not settings.hf_configured:
        raise ModelError(
            "HF_TOKEN is not set.",
            hint="Add HF_TOKEN to .env and restart the backend.",
            kind="auth",
            code="hf_error",
        )
    try:
        response = requests.post(
            _endpoint(),
            headers={
                "Authorization": f"Bearer {settings.hf_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=(15, settings.request_timeout),
        )
    except requests.Timeout as exc:
        raise ModelError(
            "Hugging Face request timed out.",
            hint="Raise AI_REQUEST_TIMEOUT in .env or pick a faster model.",
            kind="overloaded",
            code="hf_error",
        ) from exc
    except requests.RequestException as exc:
        raise ModelError(
            f"Could not reach Hugging Face: {exc}",
            hint="Check your network / proxy, then retry.",
            kind="unknown",
            code="hf_error",
        ) from exc

    if response.status_code >= 400:
        raise _HttpError(response.status_code, response.text)
    try:
        return response.json()
    except ValueError as exc:
        raise ModelError(
            "Hugging Face returned a non-JSON response.",
            kind="content",
            code="hf_error",
        ) from exc


def _content_text(data: Dict[str, Any]) -> str:
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# Attachments -> OpenAI content parts
# ---------------------------------------------------------------------------


def _strip_data_url(data_url: str) -> tuple[str, str]:
    header, _, payload = data_url.partition(",")
    mime = "image/png"
    match = re.search(r"data:([\w./+-]+)", header)
    if match:
        mime = match.group(1)
    return mime, payload


def _pdf_as_text(path: str) -> str:
    """HF providers do not ingest PDFs, so read the embedded text layer first."""
    try:
        from services.offline import extract_pdf_text

        return extract_pdf_text(path).strip()
    except Exception as exc:  # pragma: no cover - unreadable PDF
        logger.warning("Could not extract PDF text from %s: %s", path, exc)
        return ""


def build_messages(
    system_instruction: str, prompt: str, documents: Optional[Sequence[Dict[str, str]]] = None
) -> List[Dict[str, Any]]:
    """Assemble OpenAI-style messages: system + user text + attachments."""
    user_parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]

    for document in documents or []:
        mime = (document.get("mime_type") or "").lower()
        try:
            if document.get("data_url"):
                mime, payload = _strip_data_url(document["data_url"])
                if mime.startswith("image/"):
                    user_parts.append(
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{payload}"}}
                    )
                continue

            path = document.get("path", "")
            if not path:
                continue

            if mime == "application/pdf" or path.lower().endswith(".pdf"):
                text = _pdf_as_text(path)
                if text:
                    name = document.get("filename") or path
                    user_parts.append(
                        {
                            "type": "text",
                            "text": f"--- Text extracted from {name} ---\n{text}\n--- end ---",
                        }
                    )
            elif mime.startswith("image/"):
                with open(path, "rb") as handle:
                    payload = base64.b64encode(handle.read()).decode()
                user_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{payload}"},
                    }
                )
        except Exception as exc:  # pragma: no cover - unreadable attachment
            logger.warning("Skipping attachment %s: %s", document.get("filename"), exc)

    return [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": user_parts},
    ]


def _without_images(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strip image parts so a text-only model can still answer from the text."""
    stripped: List[Dict[str, Any]] = []
    for message in messages:
        if isinstance(message.get("content"), list):
            message = {
                **message,
                "content": [p for p in message["content"] if p.get("type") != "image_url"],
            }
        stripped.append(message)
    return stripped


def _has_images(messages: List[Dict[str, Any]]) -> bool:
    return any(
        part.get("type") == "image_url"
        for message in messages
        if isinstance(message.get("content"), list)
        for part in message["content"]
    )


# ---------------------------------------------------------------------------
# Structured call
# ---------------------------------------------------------------------------


def _coerce(text: str, model_cls: Type[T], model_name: str) -> T:
    """Parse and validate a JSON response, tolerating markdown fences."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    # Some models prepend a sentence such as "Here is the JSON requested:".
    if not cleaned.startswith("{"):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start : end + 1]

    if not cleaned:
        raise ModelError(
            f"The model {model_name} returned an empty response.",
            model=model_name,
            kind="content",
            code="hf_error",
        )
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ModelError(
            f"The model returned invalid JSON: {exc.msg} (line {exc.lineno}).",
            hint="This is usually a transient model issue - retry the step.",
            model=model_name,
            kind="content",
            code="hf_error",
        ) from exc
    if not isinstance(payload, dict):
        raise ModelError(
            f"The model returned JSON that is not an object.",
            model=model_name,
            kind="content",
            code="hf_error",
        )
    try:
        return model_cls.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ())) or "(root)"
        raise ModelError(
            f"Model response did not match {model_cls.__name__} at '{location}'.",
            hint=first.get("msg", ""),
            model=model_name,
            kind="content",
            code="hf_error",
        ) from exc


def _payload(
    model_name: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    json_mode: bool = True,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 8192,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


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
    """Call Hugging Face (with retries) and return a validated ``response_model``."""
    if temperature is None:
        temperature = (
            settings.temperature_reasoning
            if model_name == settings.model_reasoning
            else settings.temperature_extraction
        )
    attempts = max_attempts or settings.max_attempts

    original = build_messages(system_instruction, prompt, documents)
    messages = original
    dropped_images = False
    # Not every provider on the router accepts OpenAI's response_format; if one
    # rejects it we fall back to prompt-driven JSON, which _coerce can parse.
    json_mode = True
    dropped_json_mode = False

    last_error: Optional[ModelError] = None
    attempt = 0

    while attempt < attempts:
        attempt += 1
        try:
            data = await asyncio.to_thread(
                _post, _payload(model_name, messages, temperature, json_mode)
            )
            return _coerce(_content_text(data), response_model, model_name)
        except ModelError as exc:
            last_error = exc
        except _HttpError as exc:
            last_error = classify_exception(exc, model_name)
        except Exception as exc:  # noqa: BLE001 - network / unexpected SDK-free errors
            last_error = classify_exception(exc, model_name)

        # A text-only model rejecting an image is a configuration detail, not a
        # dead end: retry once with the text (which includes extracted PDF text).
        if last_error.kind == "content" and not dropped_images and _has_images(messages):
            logger.info("Retrying %s without image attachments", model_name)
            messages = _without_images(original)
            dropped_images = True
            last_error = None
            attempt -= 1  # this is a payload fix, not a real attempt
            continue

        if (
            last_error.kind == "content"
            and not dropped_json_mode
            and any(word in last_error.message.lower() for word in ("response_format", "json_object", "json mode", "json schema"))
        ):
            logger.info("Retrying %s without response_format", model_name)
            json_mode = False
            dropped_json_mode = True
            last_error = None
            attempt -= 1
            continue

        if last_error.kind in {"auth", "model", "quota"}:
            logger.error(
                "HF call failed fatally (%s): %s", last_error.kind, last_error.message
            )
            raise last_error

        if attempt < attempts:
            delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
            logger.warning(
                "HF attempt %s/%s failed for %s (%s); retrying in %.1fs: %s",
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


async def try_structured(**kwargs: Any) -> tuple[Optional[Any], str]:
    """Call :func:`run_structured`, degrading gracefully when HF is reachable
    but temporarily unusable (rate limited, provider overloaded).

    Every agent computes its deterministic result *before* attempting the model
    call, so when this returns ``(None, note)`` the caller keeps that result and
    reports ``used_ai = False``. Real misconfiguration (bad token, unknown model)
    still raises, because a silent fallback would hide a bug the user must fix.
    """
    try:
        return await run_structured(**kwargs), ""
    except ModelError as exc:
        if exc.kind not in {"quota", "overloaded"}:
            raise
        note = (
            f"Hugging Face was unavailable for this stage ({exc.kind}: {exc.message}) "
            "so the deterministic engine was used instead. Results are still "
            "flagged for human review."
        )
        logger.warning("Degrading to deterministic mode: %s", exc.message)
        return None, note


# ---------------------------------------------------------------------------
# Client / health surface
# ---------------------------------------------------------------------------


def get_client():
    """HF is a plain HTTP endpoint, so there is no client object to keep."""
    return None


def client_status() -> Dict[str, str]:
    """Human-readable status used by /api/health and error messages."""
    if settings.force_offline:
        return {
            "mode": "offline_deterministic",
            "message": "FORCE_OFFLINE=1 - running the deterministic engine only.",
        }
    if not settings.hf_configured:
        return {
            "mode": "offline_deterministic",
            "message": (
                "HF_TOKEN is not configured - running without AI calls. "
                "Add HF_TOKEN to .env (see .env.example) and restart the backend."
            ),
        }
    return {
        "mode": "huggingface",
        "message": f"Hugging Face connected ({settings.model_extraction}).",
    }


def ai_mode() -> str:
    return client_status()["mode"]


def verify_models(force: bool = False) -> Dict[str, Dict[str, str]]:
    """Send one tiny real request per configured model.

    A token being present proves nothing: the model may be unknown to HF or
    out of capacity, which would otherwise show a reassuring "connected" health
    check while every pipeline call fails. Cached because /api/health is polled
    by the UI and a live probe would itself trip the 429 it reports.
    """
    global _model_check_cache, _model_check_time

    if not settings.hf_configured:
        return {}

    if (
        not force
        and _model_check_cache
        and (time.monotonic() - _model_check_time) < MODEL_CHECK_TTL
    ):
        return _model_check_cache

    results: Dict[str, Dict[str, str]] = {}

    for name in settings.configured_models:
        try:
            _post(_payload(name, [{"role": "user", "content": "Reply with OK."}], 0.0, json_mode=False))
            results[name] = {"ok": "true", "detail": "reachable"}
        except ModelError as error:
            results[name] = {
                "ok": "false",
                "kind": error.kind,
                "detail": error.message,
                "hint": error.hint,
            }
        except _HttpError as error:
            classified = classify_exception(error, name)
            results[name] = {
                "ok": "false",
                "kind": classified.kind,
                "detail": classified.message,
                "hint": classified.hint,
            }
        except Exception as exc:  # noqa: BLE001
            classified = classify_exception(exc, name)
            results[name] = {
                "ok": "false",
                "kind": classified.kind,
                "detail": classified.message,
                "hint": classified.hint,
            }

    _model_check_cache = results
    _model_check_time = time.monotonic()
    return results


async def list_models() -> List[str]:
    """Best-effort listing of models this token can reach."""
    try:
        response = await asyncio.to_thread(
            requests.get,
            settings.hf_base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {settings.hf_token}"},
            timeout=20,
        )
        if response.status_code != 200:
            return []
        data = response.json()
        if isinstance(data, dict):
            data = data.get("data", [])
        return [item.get("id", "") for item in data if isinstance(item, dict)][:200]
    except Exception:  # pragma: no cover - informational only
        return []
