"""MediClaim / ClaimGen AI - FastAPI application.

    uvicorn main:app --reload      (run from the backend/ directory)

All AI work happens in the agent pipeline; this module only handles HTTP,
uploads and PDF delivery. There is no database, no auth and no external
service: claims live in memory and are mirrored to JSON files on disk.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from agents.base import AgentError
from config import SAMPLE_DIR, settings
from models.schemas import (
    ApiError,
    ClaimIdRequest,
    ClaimRecord,
    ClaimSummaryLine,
    CreateClaimRequest,
    DocumentMeta,
    HealthResponse,
    SampleData,
    UpdateClaimRequest,
    UserInput,
    build_default_stages,
)
from services import llm, pipeline, sample_data, store

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-7s %(name)-26s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mediclaim.api")

# Running pipelines, keyed by claim id, so a second request cannot start one.
_RUNNING: Dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 74)
    logger.info("  %s %s", settings.app_name, settings.app_version)
    logger.info("  AI mode: %s", llm.client_status()["message"])
    logger.info("  Claims folder: %s", store.CLAIM_STORE_DIR)
    logger.info("=" * 74)
    yield
    for task in list(_RUNNING.values()):
        task.cancel()
    client = llm.get_client()
    if client is not None:
        try:
            client.close()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            pass


app = FastAPI(
    title=f"{settings.app_name} API",
    version=settings.app_version,
    description=(
        "Multimodal agent pipeline that turns patient details and uploaded medical "
        "documents into a draft insurance claim form and a printable PDF. "
        "Every generated claim requires review by an authorised person."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def public_record(record: ClaimRecord) -> Dict[str, Any]:
    """Serialise a claim for the API, hiding server-side file paths."""
    payload = record.model_dump(mode="json")
    for document in payload.get("documents", []):
        document.pop("stored_path", None)
    return payload


def _get_or_404(claim_id: str) -> ClaimRecord:
    record = store.get_claim(claim_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=ApiError(
                detail=f"No claim found with id '{claim_id}'.",
                hint="It may have been deleted, or the backend was restarted without persistence.",
                code="claim_not_found",
            ).model_dump(),
        )
    return record


def _attach_documents(record: ClaimRecord, entries: List[Dict[str, Any]]) -> None:
    record.documents = entries


def _is_running(claim_id: str) -> bool:
    task = _RUNNING.get(claim_id)
    return task is not None and not task.done()


# ---------------------------------------------------------------------------
# Health / config
# ---------------------------------------------------------------------------


@app.get("/api/live")
async def live() -> Dict[str, str]:
    """Cheap liveness probe for the host platform.

    Deliberately does *not* call Gemini: a platform health check runs every
    minute, and spending model quota on it would be both slow and pointless.
    Use ``/api/health`` when you want the real model diagnostics.
    """
    return {"status": "ok"}


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    status = llm.client_status()
    checks: Dict[str, Any] = {}
    message = status["message"]

    if status["mode"] != "offline_deterministic":
        # Prove the configured models actually answer. A valid token is not
        # enough - retired or unserved model names still authenticate cleanly.
        checks = await asyncio.to_thread(llm.verify_models)
        broken = {m: c for m, c in checks.items() if c.get("ok") != "true"}
        if broken:
            provider = "Hugging Face" if status["mode"] == "huggingface" else "Gemini"
            names = ", ".join(broken)
            first = next(iter(broken.values()))
            message = (
                f"{provider} is reachable but {len(broken)} of {len(checks)} configured "
                f"model(s) cannot be used: {names}. "
                f"{first.get('detail', '')} {first.get('hint', '')}".strip()
            )
            logger.warning("health: %s", message)

    return HealthResponse(
        status="degraded" if any(c.get("ok") != "true" for c in checks.values()) else "ok",
        ai_mode=status["mode"],
        app_name=settings.app_name,
        version=settings.app_version,
        models={
            "extraction": settings.model_extraction,
            "reasoning": settings.model_reasoning,
            "review": settings.model_review,
        },
        model_checks=checks,
        message=message,
    )


@app.get("/api/config")
async def get_config() -> Dict[str, Any]:
    return settings.public_config()


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


@app.get("/api/claims")
async def list_claims() -> Dict[str, Any]:
    records = store.list_claims()
    return {
        "claims": [record.to_summary().model_dump(mode="json") for record in records],
        "count": len(records),
        "ai_mode": llm.ai_mode(),
    }


@app.post("/api/claim/create", status_code=201)
async def create_claim(payload: CreateClaimRequest = Body(default_factory=CreateClaimRequest)) -> Dict[str, Any]:
    claim_id = store.new_id()
    input_data = payload.input_data or UserInput()
    title = payload.title.strip() or "Untitled claim"

    if payload.use_sample_data:
        input_data = sample_data.SAMPLE_INPUT.model_copy(deep=True)
        title = sample_data.SAMPLE_CLAIM_TITLE
        available = sample_data.ensure_sample_documents()
        documents: List[DocumentMeta] = []
        for index, (filename, path) in enumerate(available.items()):
            try:
                stored = store.save_upload(claim_id, filename, path.read_bytes())
            except Exception as exc:  # noqa: BLE001
                logger.error("Could not attach sample %s: %s", filename, exc)
                continue
            documents.append(
                DocumentMeta(
                    document_id=f"doc_{index:02d}",
                    filename=filename,
                    stored_path=str(stored),
                    mime_type=sample_data.SAMPLE_MIME.get(filename, "application/pdf"),
                    size_bytes=stored.stat().st_size,
                    uploaded_at=store.utc_now(),
                    status="uploaded",
                )
            )
    else:
        documents = []

    record = ClaimRecord(
        claim_id=claim_id,
        title=title,
        status="draft",
        created_at=store.utc_now(),
        updated_at=store.utc_now(),
        ai_mode=llm.ai_mode(),  # type: ignore[arg-type]
        input_data=input_data,
        documents=documents,
        stages=build_default_stages(),
    )
    store.create_claim(record)
    logger.info("Created claim %s (%s)", claim_id, title)
    return {"claim_id": claim_id, "claim": public_record(record)}


@app.post("/api/claim/upload", status_code=201)
async def upload_documents(
    claim_id: str = Form(...),
    files: List[UploadFile] = File(...),
) -> Dict[str, Any]:
    record = _get_or_404(claim_id)
    if not files:
        raise HTTPException(
            status_code=400,
            detail=ApiError(detail="No files were received.", code="no_files").model_dump(),
        )
    existing = len(record.documents)
    room = settings.max_documents_per_claim - existing
    if room <= 0:
        raise HTTPException(
            status_code=400,
            detail=ApiError(
                detail=(
                    f"This claim already has the maximum of "
                    f"{settings.max_documents_per_claim} documents."
                ),
                code="too_many_documents",
            ).model_dump(),
        )

    added: List[DocumentMeta] = []
    rejected: List[Dict[str, str]] = []

    for upload in files[:room]:
        filename = upload.filename or "document"
        content = await upload.read()
        if not content:
            rejected.append({"filename": filename, "reason": "The file is empty."})
            continue
        if len(content) > settings.max_upload_bytes:
            rejected.append(
                {
                    "filename": filename,
                    "reason": f"Larger than the {settings.max_upload_mb} MB limit.",
                }
            )
            continue
        mime_type = store.guess_mime(filename, upload.content_type or "")
        if not store.is_allowed(filename, mime_type):
            rejected.append(
                {
                    "filename": filename,
                    "reason": "Unsupported file type. Use PDF, JPG, PNG, WEBP or HEIC.",
                }
            )
            continue
        stored = store.save_upload(claim_id, filename, content)
        added.append(
            DocumentMeta(
                document_id=f"doc_{store.new_id()[-8:]}",
                filename=filename,
                stored_path=str(stored),
                mime_type=mime_type,
                size_bytes=len(content),
                uploaded_at=store.utc_now(),
                status="uploaded",
            )
        )
        logger.info("Stored %s for claim %s (%d bytes)", filename, claim_id, len(content))

    if not added:
        raise HTTPException(
            status_code=400,
            detail=ApiError(
                detail="None of the uploaded files could be accepted.",
                hint="; ".join(f"{item['filename']}: {item['reason']}" for item in rejected),
                code="upload_rejected",
            ).model_dump(),
        )

    record.documents.extend(added)
    record.updated_at = store.utc_now()
    store.update_claim(record)
    return {
        "claim_id": claim_id,
        "added": [item.model_dump(mode="json") for item in added],
        "rejected": rejected,
        "claim": public_record(record),
    }


@app.delete("/api/claim/upload/{claim_id}/{document_id}")
async def delete_document(claim_id: str, document_id: str) -> Dict[str, Any]:
    record = _get_or_404(claim_id)
    target = next((doc for doc in record.documents if doc.document_id == document_id), None)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=ApiError(
                detail=f"No document '{document_id}' on this claim.", code="document_not_found"
            ).model_dump(),
        )
    if target.stored_path:
        try:
            from pathlib import Path

            Path(target.stored_path).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    record.documents = [doc for doc in record.documents if doc.document_id != document_id]
    store.update_claim(record)
    return {"claim_id": claim_id, "documents": [d.model_dump(mode="json") for d in record.documents]}


@app.put("/api/claim/{claim_id}")
async def update_claim(claim_id: str, payload: UpdateClaimRequest) -> Dict[str, Any]:
    record = _get_or_404(claim_id)
    if payload.input_data is not None:
        record.input_data = payload.input_data
    if payload.title.strip():
        record.title = payload.title.strip()
    if payload.regenerate:
        store.reset_pipeline(record)
    store.update_claim(record)
    return {"claim_id": claim_id, "claim": public_record(record)}


@app.get("/api/claim/{claim_id}")
async def get_claim(claim_id: str) -> Dict[str, Any]:
    record = _get_or_404(claim_id)
    return {
        "claim_id": claim_id,
        "pipeline_running": _is_running(claim_id),
        "claim": public_record(record),
    }


@app.delete("/api/claim/{claim_id}", status_code=204)
async def delete_claim(claim_id: str) -> None:
    _get_or_404(claim_id)
    task = _RUNNING.pop(claim_id, None)
    if task and not task.done():
        task.cancel()
    store.delete_claim(claim_id)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _start_pipeline(claim_id: str, regenerate: bool) -> Dict[str, Any]:
    record = _get_or_404(claim_id)
    if _is_running(claim_id):
        raise HTTPException(
            status_code=409,
            detail=ApiError(
                detail="This claim is already being processed.",
                hint="Wait for the current run to finish.",
                code="already_running",
            ).model_dump(),
        )

    async def runner() -> None:
        try:
            await pipeline.run_pipeline(record, regenerate=regenerate)
        except AgentError as exc:  # pragma: no cover - handled inside the pipeline
            logger.error("Pipeline for %s failed: %s", claim_id, exc.message)
        except asyncio.CancelledError:  # pragma: no cover
            raise
        except Exception:  # noqa: BLE001 - never let a background task die silently
            logger.exception("Unhandled error in pipeline for %s", claim_id)
        finally:
            _RUNNING.pop(claim_id, None)

    _RUNNING[claim_id] = asyncio.create_task(runner())
    logger.info("Pipeline started for %s", claim_id)
    return {
        "claim_id": claim_id,
        "status": "processing",
        "message": "Pipeline started. Poll GET /api/claim/{claim_id} for progress.",
    }


@app.post("/api/claim/process")
async def process_claim(payload: ClaimIdRequest) -> Dict[str, Any]:
    """Run the full agent pipeline in the background."""
    return _start_pipeline(payload.claim_id, regenerate=True)


@app.post("/api/claim/validate")
async def validate_claim(payload: ClaimIdRequest) -> Dict[str, Any]:
    """Run the pipeline up to and including validation only."""
    record = _get_or_404(payload.claim_id)
    return await _run_partial(record, stop_after="validation")


@app.post("/api/claim/generate")
async def generate_claim(payload: ClaimIdRequest) -> Dict[str, Any]:
    """Generate the claim form and PDF from already-validated data."""
    record = _get_or_404(payload.claim_id)
    if record.claim_data is None:
        raise HTTPException(
            status_code=409,
            detail=ApiError(
                detail="There is no extracted claim data yet.",
                hint="Run POST /api/claim/process first.",
                code="not_extracted",
            ).model_dump(),
        )
    return await _run_partial(record, stop_after="review")


@app.post("/api/claim/review")
async def review_claim(payload: ClaimIdRequest) -> Dict[str, Any]:
    """Re-run the review agent against the current generated claim."""
    record = _get_or_404(payload.claim_id)
    if record.generated is None or record.claim_data is None:
        raise HTTPException(
            status_code=409,
            detail=ApiError(
                detail="There is no generated claim to review yet.",
                hint="Run POST /api/claim/generate first.",
                code="not_generated",
            ).model_dump(),
        )
    from agents import review_agent
    from agents.base import finish_stage

    stage = record.get_stage("review")
    if stage:
        stage.status = "processing"
        stage.message = "Final review in progress"
    store.update_claim(record)
    review, used_ai, message = await review_agent.run(
        record.claim_data, record.generated, record.document_understanding, record.validation
    )
    record.review = review
    finish_stage(
        record,
        "review",
        "warning" if review.status == "NEEDS_CORRECTION" else "completed",
        message,
        f"{review.checked_fields} field(s) compared, {len(review.issues)} issue(s)",
    )
    store.update_claim(record)
    return {"claim_id": record.claim_id, "claim": public_record(record), "used_ai": used_ai}


async def _run_partial(record: ClaimRecord, stop_after: str) -> Dict[str, Any]:
    """Run the pipeline but halt after the named stage.

    Used by the /validate and /generate endpoints so the UI can advance the
    agents one step at a time when the user wants to inspect intermediate state.
    """
    async with store.claim_lock(record.claim_id):
        previous = record.stages
        record.stages = build_default_stages()
        keep = [key for key in ("input", "document_analysis", "extraction")]
        if stop_after == "review":
            keep += ["validation", "generation", "review"]
        for stage in previous:
            if stage.key in keep:
                record.stages = [s for s in record.stages if s.key != stage.key] + [stage]
        record.stages.sort(key=lambda s: [k.key for k in build_default_stages()].index(s.key))
        record.status = "processing"
        store.update_claim(record)
        try:
            await pipeline.run_pipeline(record, regenerate=False)
        except Exception as exc:  # noqa: BLE001
            record.status = "error"
            record.error = str(exc)
            store.update_claim(record)
    return {
        "claim_id": record.claim_id,
        "status": record.status,
        "claim": public_record(record),
    }


@app.get("/api/claim/{claim_id}/pdf")
async def get_claim_pdf(claim_id: str) -> FileResponse:
    record = _get_or_404(claim_id)
    path = pipeline.pdf_path(record)
    if not path:
        raise HTTPException(
            status_code=409,
            detail=ApiError(
                detail="No claim form has been generated for this claim yet.",
                hint=(
                    "The pipeline stops when required information is missing. "
                    "Fill in the highlighted fields and run the pipeline again."
                    if record.status == "needs_input"
                    else "Run POST /api/claim/process to generate the claim."
                ),
                code="pdf_not_ready",
            ).model_dump(),
        )
    return FileResponse(
        path=path,
        media_type="application/pdf",
        filename=path.replace("\\", "/").split("/")[-1],
    )


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------


@app.get("/api/claims/sample", response_model=SampleData)
async def get_sample() -> SampleData:
    return sample_data.get_sample_data()


@app.get("/api/claims/sample/documents/{filename}")
async def get_sample_document(filename: str) -> FileResponse:
    safe = sample_data.DESCRIPTIONS and filename
    if not safe or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(
            status_code=400,
            detail=ApiError(detail="Invalid document name.", code="bad_name").model_dump(),
        )
    available = sample_data.ensure_sample_documents()
    path = available.get(safe)
    if path is None or not path.exists():
        raise HTTPException(
            status_code=404,
            detail=ApiError(
                detail=f"Sample document '{safe}' is not available.", code="sample_not_found"
            ).model_dump(),
        )
    return FileResponse(
        path=path,
        media_type=sample_data.SAMPLE_MIME.get(safe, "application/octet-stream"),
        filename=safe,
    )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content={"error": detail})
    return JSONResponse(
        status_code=exc.status_code, content={"error": {"detail": str(detail)}}
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "detail": "Something went wrong while handling this request.",
                "hint": str(exc) or exc.__class__.__name__,
                "code": "server_error",
            }
        },
    )


__all__ = ["app"]
