"""Shared agent scaffolding: errors, stage timing, prompt helpers."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from models.schemas import ClaimRecord, PipelineStage
from services import store

logger = logging.getLogger("mediclaim.agent")


class AgentError(RuntimeError):
    """An agent could not produce a usable result."""

    def __init__(self, agent: str, message: str, hint: str = ""):
        super().__init__(message)
        self.agent = agent
        self.message = message
        self.hint = hint

    def to_dict(self) -> Dict[str, str]:
        return {"detail": self.message, "hint": self.hint, "code": "agent_error"}


@dataclass
class AgentResult:
    """Uniform envelope returned by every agent run."""

    data: Any = None
    warnings: List[str] = field(default_factory=list)
    used_ai: bool = False
    message: str = ""


@asynccontextmanager
async def stage(
    record: ClaimRecord,
    stage_key: str,
    processing_message: str,
):
    """Mark a pipeline stage as processing for the duration of the block.

    The UI polls ``record.stages`` while the pipeline runs, so the status is
    flipped before the work starts and set again when the block exits.
    """
    target = record.get_stage(stage_key)
    if target:
        target.status = "processing"
        target.message = processing_message
    store.update_claim(record)
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed = int((time.perf_counter() - started) * 1000)
        if target:
            target.duration_ms = elapsed


def finish_stage(
    record: ClaimRecord,
    stage_key: str,
    status: str,
    message: str,
    detail: str = "",
) -> None:
    target = record.get_stage(stage_key)
    if target:
        target.status = status  # type: ignore[assignment]
        target.message = message
        target.detail = detail
    store.update_claim(record)
    logger.info("[%s] %s - %s", stage_key, status, message)


def stage_key_for(record: ClaimRecord, key: str) -> Optional[PipelineStage]:
    return record.get_stage(key)


def json_block(payload: Any, title: str = "") -> str:
    """Pretty JSON for embedding in a prompt."""
    import json

    heading = f"{title}\n" if title else ""
    return heading + "```json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```"


def documents_for_prompt(documents: Sequence[Dict[str, Any]]) -> str:
    """Numbered attachment list for inclusion in a prompt."""
    lines = []
    for index, document in enumerate(documents, start=1):
        mime = document.get("mime_type", "")
        kind = "PDF" if "pdf" in mime else "image"
        label = document.get("filename") or f"attachment-{index}"
        lines.append(f"{index}. [{kind}] {label}")
    return "\n".join(lines)
