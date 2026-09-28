"""Claim storage: in-memory index plus optional JSON persistence on disk.

Deliberately simple - no database, no ORM. The in-memory dict is the source of
truth while the app is running; each mutation is mirrored to
``backend/data/claims/<claim_id>.json`` so claims survive a restart.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from config import CLAIM_STORE_DIR, UPLOAD_DIR, settings
from models.schemas import ClaimRecord, build_default_stages

logger = logging.getLogger("mediclaim.store")

_CLAIMS: Dict[str, ClaimRecord] = {}
_LOCKS: Dict[str, asyncio.Lock] = {}
_REGISTRY_LOCK = asyncio.Lock()

# Extensions we accept from the browser / curl.
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic"}
EXTENSION_MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return f"clm_{uuid.uuid4().hex[:12]}"


def claim_lock(claim_id: str) -> asyncio.Lock:
    """One lock per claim so the pipeline cannot be run twice concurrently."""
    if claim_id not in _LOCKS:
        _LOCKS[claim_id] = asyncio.Lock()
    return _LOCKS[claim_id]


def claim_dir(claim_id: str) -> Path:
    path = UPLOAD_DIR / claim_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def claim_file(claim_id: str) -> Path:
    return CLAIM_STORE_DIR / f"{claim_id}.json"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_claim(record: ClaimRecord) -> ClaimRecord:
    _CLAIMS[record.claim_id] = record
    _write(record)
    return record


def get_claim(claim_id: str) -> Optional[ClaimRecord]:
    """In-memory first, then lazily rehydrate from disk after a restart."""
    if claim_id in _CLAIMS:
        return _CLAIMS[claim_id]
    path = claim_file(claim_id)
    if path.exists():
        try:
            record = ClaimRecord.model_validate_json(path.read_text(encoding="utf-8"))
            _CLAIMS[claim_id] = record
            return record
        except Exception as exc:  # pragma: no cover - corrupted file
            logger.error("Could not load claim %s: %s", claim_id, exc)
    return None


def list_claims() -> List[ClaimRecord]:
    """All known claims, newest first. Reads the store folder for leftovers."""
    records = list(_CLAIMS.values())
    if CLAIM_STORE_DIR.exists():
        for path in CLAIM_STORE_DIR.glob("clm_*.json"):
            claim_id = path.stem
            if claim_id not in _CLAIMS:
                record = get_claim(claim_id)
                if record:
                    records.append(record)
    return sorted(records, key=lambda item: item.created_at, reverse=True)


def update_claim(record: ClaimRecord) -> ClaimRecord:
    record.updated_at = utc_now()
    _CLAIMS[record.claim_id] = record
    _write(record)
    return record


def delete_claim(claim_id: str) -> bool:
    existed = _CLAIMS.pop(claim_id, None) is not None
    path = claim_file(claim_id)
    if path.exists():
        path.unlink()
        existed = True
    uploads = UPLOAD_DIR / claim_id
    if uploads.exists():
        shutil.rmtree(uploads, ignore_errors=True)
    _LOCKS.pop(claim_id, None)
    return existed


def reset_pipeline(record: ClaimRecord) -> ClaimRecord:
    """Clear every agent output and put all stages back to ``pending``."""
    record.document_understanding = None
    record.claim_data = None
    record.validation = None
    record.generated = None
    record.review = None
    record.pdf_filename = ""
    record.error = ""
    record.status = "draft"
    record.stages = build_default_stages()
    return record


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _write(record: ClaimRecord) -> None:
    if not settings.persist_claims:
        return
    try:
        claim_file(record.claim_id).write_text(
            json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:  # pragma: no cover - disk problems must not 500
        logger.error("Could not persist claim %s: %s", record.claim_id, exc)


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


def save_upload(claim_id: str, filename: str, content: bytes) -> Path:
    """Persist an uploaded document and return its path on disk."""
    safe_name = Path(filename or "document").name
    target = claim_dir(claim_id) / f"{uuid.uuid4().hex[:8]}_{safe_name}"
    target.write_bytes(content)
    return target


def guess_mime(filename: str, declared: str) -> str:
    if declared and declared in settings.allowed_mime_types:
        return declared
    return EXTENSION_MIME.get(Path(filename).suffix.lower(), "application/pdf")


def is_allowed(filename: str, mime_type: str) -> bool:
    suffix = Path(filename).suffix.lower()
    if suffix in ALLOWED_EXTENSIONS:
        return True
    return mime_type in settings.allowed_mime_types
