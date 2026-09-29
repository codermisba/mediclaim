"""Sequential agent pipeline.

    Input -> Document Analysis -> Information Extraction -> Validation
          -> Claim Generation -> Final Review -> PDF

The orchestrator owns stage transitions, timing, error handling and the
"stop the pipeline when required information is missing" rule. Agents only
transform data; they never know about HTTP or the UI.

The stage machine mirrors the UI:
    pending -> processing -> completed | warning | failed
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from agents import (
    document_agent,
    extraction_agent,
    generation_agent,
    input_agent,
    review_agent,
    validation_agent,
)
from agents.base import AgentError, finish_stage, stage
from config import CLAIM_STORE_DIR, settings
from models.schemas import ClaimRecord
from services import llm, store
from services.pdf_generator import build_claim_pdf

logger = logging.getLogger("mediclaim.pipeline")

DISCLAIMER = (
    "This document is an AI-generated DRAFT prepared from information supplied by the "
    "policyholder and documents provided for this request. It has not been reviewed or "
    "approved by any insurer. An authorised person must verify every field against the "
    "original documents before submission. MediClaim does not provide medical, insurance "
    "or coverage advice and does not approve, reject or assess any claim."
)

AI_MODE_WARNING = (
    "No AI provider was configured, so this claim was produced by the deterministic "
    "offline reader instead. Text-based PDFs were parsed; images and scanned documents "
    "were not analysed. Set HF_TOKEN in .env and re-run the pipeline."
)

DRAFT_NOTICE = (
    "DRAFT - requires verification by an authorised person before submission."
)


def _document_kinds(record: ClaimRecord) -> List[str]:
    kinds: List[str] = []
    for document in record.documents:
        if document.detected_type:
            kinds.append(f"{document.filename}: {document.detected_type}")
        else:
            kinds.append(f"{document.filename}: {document.mime_type}")
    return kinds


def _mark_input_done(record: ClaimRecord, message: str, detail: str) -> None:
    status = "warning" if llm.ai_mode() == "offline_deterministic" else "completed"
    if not detail:
        detail = "Details are ready for the agents"
    finish_stage(record, "input", status, message, detail)


async def run_pipeline(record: ClaimRecord, regenerate: bool = True) -> ClaimRecord:
    """Run every agent in order for one claim, updating ``record`` in place.

    The claim is persisted after each stage so the UI can poll progress.
    """
    if regenerate:
        documents = record.documents
        input_data = record.input_data
        title = record.title
        store.reset_pipeline(record)
        record.documents = documents
        record.input_data = input_data
        record.title = title

    record.ai_mode = llm.ai_mode()  # type: ignore[assignment]
    record.status = "processing"
    record.error = ""
    record.ai_notice = ""
    if not record.created_at:
        record.created_at = store.utc_now()
    store.update_claim(record)

    try:
        # ---------------------------------------------------------- 1. input
        async with stage(record, "input", "Collecting typed details and documents"):
            time.sleep(0.05)  # yields so the UI can paint the stage
            _, message, detail = input_agent.run(record)
        _mark_input_done(record, message, detail)

        # ------------------------------------------- 2. document understanding
        async with stage(record, "document_analysis", "Analyzing documents"):
            understanding, detected, used_ai, message = await document_agent.run(
                record.documents, record.input_data.notes
            )
        record.document_understanding = understanding
        for document in record.documents:
            document_agent.build_meta(
                document,
                detected_kind=detected.get(document.filename, ""),
                status="analysed",
                note="" if used_ai else "Not analysed by AI in offline mode.",
            )
        record = _stage_done(record, "document_analysis", used_ai, message, understanding)

        # ------------------------------------------------- 3. extraction
        async with stage(record, "extraction", "Extracting claim information"):
            assert understanding is not None
            claim_data, used_ai, message = await extraction_agent.run(
                understanding, record.input_data, sample_claim=False
            )
        record.claim_data = claim_data
        record = _stage_done(record, "extraction", used_ai, message, claim_data)

        # ------------------------------------------------- 4. validation
        async with stage(record, "validation", "Validating required fields"):
            assert claim_data is not None
            validation, used_ai, message = await validation_agent.run(
                claim_data, _document_kinds(record)
            )
        record.validation = validation
        record = _stage_done(record, "validation", used_ai, message, validation)

        # ------------------------------------------- halt if input is missing
        if record.validation.missing_required:
            record.status = "needs_input"
            finish_stage(
                record,
                "validation",
                "failed",
                message,
                detail="; ".join(
                    _label(path) for path in record.validation.missing_required
                ),
            )
            for key in ("generation", "review"):
                target = record.get_stage(key)
                if target:
                    target.status = "pending"
                    target.message = "Waiting for the required information above"
            store.update_claim(record)
            logger.info("Pipeline halted for %s: missing required fields", record.claim_id)
            return record

        # ------------------------------------------- 5. claim generation
        async with stage(record, "generation", "Generating claim"):
            generated, used_ai, message = await generation_agent.run(
                record.claim_data,
                record.validation,
                [document.filename for document in record.documents],
                record.claim_id,
            )
        record.generated = generated
        record = _stage_done(record, "generation", used_ai, message, generated)

        # --------------------------------------------------- 6. review
        async with stage(record, "review", "Final review in progress"):
            assert claim_data is not None and generated is not None
            review, used_ai, message = await review_agent.run(
                claim_data, generated, record.document_understanding, record.validation
            )
        record.review = review
        record = _stage_done(
            record,
            "review",
            used_ai,
            message,
            review,
            status_override="warning" if review.status == "NEEDS_CORRECTION" else None,
        )

        # ------------------------------------------------------ 7. PDF
        _write_pdf(record)

        record.status = "ready_for_review" if record.generated else "error"
        store.update_claim(record)
        logger.info("Pipeline finished for %s with status %s", record.claim_id, record.status)
        return record

    except AgentError as exc:
        record.status = "error"
        record.error = exc.message
        _fail_current(record, exc.message)
        store.update_claim(record)
        return record
    except Exception as exc:  # noqa: BLE001 - surfaced to the client
        logger.exception("Pipeline crashed for %s", record.claim_id)
        record.status = "error"
        record.error = str(exc)
        _fail_current(record, str(exc))
        store.update_claim(record)
        return record


def _stage_done(
    record: ClaimRecord,
    stage_key: str,
    used_ai: bool,
    message: str,
    payload,
    status_override: Optional[str] = None,
) -> ClaimRecord:
    status = status_override or "completed"
    if stage_key == "extraction" and getattr(payload, "uncertain_fields", None):
        status = "warning"
    detail = ""
    if stage_key == "extraction":
        missing = len(getattr(payload, "missing_fields", []) or [])
        uncertain = len(getattr(payload, "uncertain_fields", []) or [])
        detail = f"{missing} field(s) still missing, {uncertain} flagged for review"
    elif stage_key == "document_analysis":
        detail = f"read {len(getattr(payload, 'documents_seen', []) or [])} document(s)"
    elif stage_key == "validation":
        detail = f"{payload.checked_fields} field(s) checked"
    elif stage_key == "generation":
        detail = payload.claim_number
    elif stage_key == "review":
        detail = f"{payload.checked_fields} field(s) compared, {len(payload.issues)} issue(s)"
    if not used_ai:
        # True both in offline mode and when a stage degraded because Gemini was
        # unreachable, so a stage that never called the model must never look
        # like a clean success.
        status = "warning" if status == "completed" else status
        detail = (detail + " - " if detail else "") + "deterministic mode (no AI)"
        if record.ai_mode != "offline_deterministic" and not record.ai_notice:
            record.ai_notice = (
                "At least one stage could not reach Gemini (quota or a temporarily "
                "overloaded endpoint) and fell back to the deterministic engine. "
                "Those stages are marked 'warning' and must be checked by a human."
            )
    finish_stage(record, stage_key, status, message, detail)
    return record


def _fail_current(record: ClaimRecord, message: str) -> None:
    for key in ("document_analysis", "extraction", "validation", "generation", "review"):
        target = record.get_stage(key)
        if target and target.status == "processing":
            finish_stage(record, key, "failed", message)
            return


def _label(path: str) -> str:
    from models.schemas import OPTIONAL_CLAIM_FIELDS, REQUIRED_CLAIM_FIELDS

    labels = {**REQUIRED_CLAIM_FIELDS, **OPTIONAL_CLAIM_FIELDS}
    return labels.get(path, path)


def _write_pdf(record: ClaimRecord) -> None:
    """Render the deterministic PDF and remember where it went."""
    if not record.generated or not record.claim_data:
        return
    try:
        filename = build_claim_pdf(record, CLAIM_STORE_DIR)
        record.pdf_filename = filename
        store.update_claim(record)
    except Exception as exc:  # noqa: BLE001 - a PDF failure must not lose the claim
        logger.error("PDF generation failed for %s: %s", record.claim_id, exc)
        record.pdf_filename = ""


def pdf_path(record: ClaimRecord) -> Optional[str]:
    if not record.pdf_filename:
        return None
    path = CLAIM_STORE_DIR / record.pdf_filename
    return str(path) if path.exists() else None
