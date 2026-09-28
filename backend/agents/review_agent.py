"""Agent 5 - Review.

The last gate before the draft is shown to the user. It compares the generated
claim form against the merged claim data and against the raw document snapshot,
looking for the classic failure modes of extraction pipelines: a number that was
transposed, a name that was dropped, a field that quietly disappeared between
stages.

It reports findings only. It does not approve a claim, and it does not modify
any value - corrections are made by the user and the pipeline is re-run.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from config import settings
from models.schemas import (
    ClaimData,
    DocumentUnderstanding,
    GeneratedClaim,
    Issue,
    ReviewResult,
    ValidationResult,
)
from services import gemini, normalize
from services.normalize import clean_text

logger = logging.getLogger("mediclaim.agent.review")

AGENT_NAME = "Review Agent"

SYSTEM_INSTRUCTION = """You are the Review Agent of MediClaim, which prepares draft insurance claim forms.

You perform a final quality check on a draft claim by comparing it against (a) the merged claim dataset it was built from and (b) the raw facts that were read out of the patient's documents.

WHAT TO LOOK FOR
1. Transcription errors: a digit, date, name or identifier in the draft that does not match the source.
2. Omissions: a non-empty value in the source that is missing from the draft.
3. Distortions: a diagnosis, procedure or description that has been reworded into something the source does not say.
4. Arithmetic problems: line items that do not add up to the claim total, or a total that differs from the source.
5. Claims of certainty that the source does not support - e.g. a place of treatment or a currency that was never provided.

STRICT LIMITS
- You do NOT approve, reject, endorse or authorise the claim. Your status is only READY_FOR_REVIEW (a human must still check it) or NEEDS_CORRECTION (something is wrong in the draft).
- You never invent missing information and never suggest a clinical value.
- Report at most 8 issues, most serious first.
- Each `message` is one short sentence a non-technical reviewer can act on. No markdown.
- Each `suggestion` is a concrete action.
- `field` must be a dotted path from the vocabulary given in the prompt, or "general".
- Return only the JSON object matching the schema, with every key present."""

PROMPT_TEMPLATE = """Review this draft claim form against its sources.

## 1. Raw facts read from the documents (the original source of truth)
{document_block}

## 2. Merged claim dataset (what the pipeline decided to use)
{claim_block}

## 3. The draft claim form that will be printed on the PDF
{draft_block}

## Fields the draft is expected to carry
{field_list}

The JSON schema to follow exactly:
{schema}

Return the JSON object now. If the draft faithfully represents the source, return
`status: "READY_FOR_REVIEW"` with an empty `issues` list."""

#: dotted paths the draft must reflect, with a label used to check presence.
_DRAFT_FIELDS: Dict[str, str] = {
    "patient.name": "patient name",
    "patient.date_of_birth": "date of birth",
    "patient.gender": "gender",
    "patient.address": "patient address",
    "insurance.provider": "insurance provider",
    "insurance.policy_number": "policy number",
    "insurance.member_id": "member ID",
    "hospital.name": "hospital name",
    "hospital.address": "hospital address",
    "doctor.name": "doctor name",
    "doctor.registration_number": "doctor registration number",
    "treatment.diagnosis": "diagnosis",
    "treatment.admission_date": "admission date",
    "treatment.discharge_date": "discharge date",
    "billing.total_amount": "claimed amount",
    "billing.currency": "currency",
}

_MONEY = 0.01
_NAME_OVERLAP = 0.6


def _json(payload: object) -> str:
    import json

    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def _source_snapshot(understanding: Optional[DocumentUnderstanding]) -> Dict[str, str]:
    if understanding is None:
        return {}
    return {
        "patient.name": understanding.patient_name,
        "patient.date_of_birth": understanding.patient_date_of_birth,
        "patient.gender": understanding.patient_gender,
        "patient.phone": understanding.patient_phone,
        "patient.address": understanding.patient_address,
        "insurance.provider": understanding.insurance_provider,
        "insurance.policy_number": understanding.insurance_policy_number,
        "insurance.member_id": understanding.insurance_member_id,
        "hospital.name": understanding.hospital_name,
        "hospital.address": understanding.hospital_address,
        "hospital.phone": understanding.hospital_phone,
        "doctor.name": understanding.doctor_name,
        "doctor.registration_number": understanding.doctor_registration_number,
        "doctor.specialization": understanding.doctor_specialization,
        "treatment.diagnosis": understanding.diagnosis,
        "treatment.admission_date": understanding.admission_date,
        "treatment.discharge_date": understanding.discharge_date,
        "billing.total_amount": str(understanding.total_amount),
        "billing.currency": understanding.currency,
        "billing.invoice_number": understanding.invoice_number,
    }


def _deterministic_review(
    claim: ClaimData,
    generated: GeneratedClaim,
    understanding: Optional[DocumentUnderstanding],
) -> ReviewResult:
    """Field-by-field checks that need no model."""
    issues: List[Issue] = []
    checked = 0

    def compare(path: str, draft_value: object) -> None:
        nonlocal checked
        source_value = normalize.get_path(claim, path)
        if normalize.is_blank(source_value):
            return
        checked += 1
        if normalize.is_blank(draft_value):
            issues.append(
                Issue(
                    field=path,
                    severity="error",
                    message=f"'{_DRAFT_FIELDS[path]}' is missing from the generated claim form.",
                    suggestion=f"Re-run the claim generation after checking '{_DRAFT_FIELDS[path]}'.",
                    source="review",
                )
            )
            return
        source_text = str(source_value)
        draft_text = str(draft_value)
        if isinstance(source_value, float) or isinstance(draft_value, float):
            if abs(float(source_value) - float(draft_value)) > _MONEY:
                issues.append(
                    Issue(
                        field=path,
                        severity="error",
                        message=(
                            f"'{_DRAFT_FIELDS[path]}' is {draft_text} in the claim form but "
                            f"{source_text} in the source data."
                        ),
                        suggestion="Check this value against the uploaded document.",
                        source="review",
                    )
                )
            return
        if path in {"patient.name", "hospital.name", "doctor.name"}:
            if not normalize.similar(source_text, draft_text) and normalize.word_overlap(
                source_text, draft_text
            ) < _NAME_OVERLAP:
                issues.append(
                    Issue(
                        field=path,
                        severity="warning",
                        message=f"'{_DRAFT_FIELDS[path]}' differs from the source data.",
                        suggestion="Check the spelling of this name against the document.",
                        source="review",
                    )
                )
            return
        if path in {"patient.date_of_birth", "treatment.admission_date", "treatment.discharge_date"}:
            left = normalize.parse_date(source_text)
            right = normalize.parse_date(draft_text)
            if left and right and left != right:
                issues.append(
                    Issue(
                        field=path,
                        severity="error",
                        message=f"'{_DRAFT_FIELDS[path]}' is {draft_text} in the claim form but {source_text} in the source data.",
                        suggestion="Check this date against the document.",
                        source="review",
                    )
                )
            return
        if not normalize.similar(source_text, draft_text):
            issues.append(
                Issue(
                    field=path,
                    severity="warning",
                    message=f"'{_DRAFT_FIELDS[path]}' does not exactly match the source data.",
                    suggestion="Verify this value against the uploaded document.",
                    source="review",
                )
            )

    compare("patient.name", claim.patient.name)
    compare("patient.date_of_birth", normalize.human_date(claim.patient.date_of_birth))
    compare("patient.gender", claim.patient.gender)
    compare("patient.address", claim.patient.address)
    compare("insurance.provider", claim.insurance.provider)
    compare("insurance.policy_number", claim.insurance.policy_number)
    compare("insurance.member_id", claim.insurance.member_id)
    compare("hospital.name", claim.hospital.name)
    compare("hospital.address", claim.hospital.address)
    compare("doctor.name", claim.doctor.name)
    compare("doctor.registration_number", claim.doctor.registration_number)
    compare("treatment.diagnosis", claim.treatment.diagnosis)
    compare("treatment.admission_date", normalize.human_date(claim.treatment.admission_date))
    compare("treatment.discharge_date", normalize.human_date(claim.treatment.discharge_date))
    compare("billing.total_amount", generated.claim_amount)
    compare("billing.currency", generated.currency)

    # Line items must reconcile with the claim total.
    if generated.line_items:
        checked += 1
        line_sum = round(sum(item.amount for item in generated.line_items), 2)
        if abs(line_sum - generated.total) > max(1.0, generated.total * 0.01):
            issues.append(
                Issue(
                    field="claim.line_items",
                    severity="error",
                    message="The itemised amounts do not add up to the claim total.",
                    suggestion="Regenerate the claim so the line items match the total.",
                    source="review",
                )
            )

    # Anything read from the documents that never reached the merged dataset.
    snapshot = _source_snapshot(understanding)
    for path, raw in snapshot.items():
        if not raw or raw == "0.0":
            continue
        if normalize.is_blank(normalize.get_path(claim, path)):
            checked += 1
            issues.append(
                Issue(
                    field=path,
                    severity="info",
                    message=(
                        f"'{normalize.humanise_path(path)}' was read from the documents as "
                        f"'{normalize.first_sentences(raw, 1, 60)}' but is not on the claim form."
                    ),
                    suggestion="Add it to the form if the insurer needs it.",
                    source="review",
                )
            )

    for path in claim.uncertain_fields:
        issues.append(
            Issue(
                field=path,
                severity="warning",
                message=(
                    f"'{normalize.humanise_path(path)}' was flagged as uncertain during extraction "
                    "and appears on the claim form as it stands."
                ),
                suggestion=f"Confirm '{normalize.humanise_path(path)}' against the source document.",
                source="review",
            )
        )

    errors = [issue for issue in issues if issue.severity == "error"]
    status = "NEEDS_CORRECTION" if errors else "READY_FOR_REVIEW"
    if errors:
        summary = f"{len(errors)} issue(s) must be corrected before this draft is submitted."
    elif issues:
        summary = f"Draft looks consistent with the source; {len(issues)} item(s) for a human to confirm."
    else:
        summary = "Draft matches the source data. A human reviewer must still verify it."
    return ReviewResult(
        status=status, summary=summary, issues=issues[:8], checked_fields=checked
    )


def _merge(deterministic: ReviewResult, model: ReviewResult) -> ReviewResult:
    seen = {(issue.field, clean_text(issue.message).lower()) for issue in deterministic.issues}
    issues = list(deterministic.issues)
    for issue in model.issues:
        key = (issue.field, clean_text(issue.message).lower())
        if key in seen:
            continue
        seen.add(key)
        if issue.severity == "info":
            issue = issue.model_copy(update={"severity": "warning"})
        issues.append(issue)
    issues = issues[:8]
    errors = [issue for issue in issues if issue.severity == "error"]
    status = "NEEDS_CORRECTION" if errors else "READY_FOR_REVIEW"
    if errors:
        summary = f"{len(errors)} issue(s) must be corrected before this draft is submitted."
    elif issues:
        summary = f"Draft looks consistent with the source; {len(issues)} item(s) for a human to confirm."
    else:
        summary = model.summary or "Draft matches the source data. A human reviewer must still verify it."
    return ReviewResult(
        status=status,
        summary=summary,
        issues=issues,
        checked_fields=max(deterministic.checked_fields, model.checked_fields),
    )


async def run(
    claim: ClaimData,
    generated: GeneratedClaim,
    understanding: Optional[DocumentUnderstanding],
    validation: Optional[ValidationResult] = None,
) -> Tuple[ReviewResult, bool, str]:
    """Review the generated claim against its sources.

    Returns ``(review, used_ai, message)``.
    """
    result = _deterministic_review(claim, generated, understanding)
    used_ai = False
    degrade_note = ""

    if gemini.ai_mode() == "gemini":
        prompt = PROMPT_TEMPLATE.format(
            document_block=_json(_source_snapshot(understanding) or {"note": "no documents were uploaded"}),
            claim_block=_json(claim.model_dump(exclude={"field_evidence", "field_sources"})),
            draft_block=_json(generated.model_dump()),
            field_list="\n".join(f"- {path}: {label}" for path, label in _DRAFT_FIELDS.items()),
            schema=gemini.schema_hint(ReviewResult),
        )
        model_result, degrade_note = await gemini.try_structured(
            model_name=settings.model_review,
            system_instruction=SYSTEM_INSTRUCTION,
            prompt=prompt,
            response_model=ReviewResult,
            temperature=0.0,
        )
        if model_result is not None:
            used_ai = True
            result = _merge(result, model_result)

    # A claim that is still missing required fields can never be "ready".
    if validation is not None and validation.missing_required and result.status == "READY_FOR_REVIEW":
        result.status = "NEEDS_CORRECTION"
        result.summary = "Required information is still missing, so this draft is not ready to review."
        result.issues = list(result.issues)[:7] + [
            Issue(
                field=path,
                severity="error",
                message=f"Required information '{normalize.humanise_path(path)}' is still missing.",
                suggestion=f"Provide '{normalize.humanise_path(path)}' and re-run the pipeline.",
                source="review",
            )
            for path in validation.missing_required[: max(0, 8 - len(result.issues))]
        ]

    message = (
        "Final review completed - draft is ready for a human reviewer."
        if result.status == "READY_FOR_REVIEW"
        else "Final review found issues that need attention."
    )
    logger.info("Review %s - %s", result.status, result.summary)
    return result, used_ai, f"{message} {degrade_note}".strip()
