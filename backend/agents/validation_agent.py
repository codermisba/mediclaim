"""Agent 3 - Validation.

Two layers:

1. **Deterministic checks (always run).** Required-field presence, date
   parsing and ordering, billing arithmetic, currency sanity, name/identifier
   plausibility. These are plain Python so the result is reproducible and can
   never be talked into by a model.
2. **Semantic review (Gemini, when configured).** Cross-checks the dataset for
   *semantic* problems that rules cannot see - e.g. a diagnosis that has nothing
   to do with the billed procedures, or a discharge summary that belongs to a
   different patient than the one named on the invoice.

The agent never approves, rejects, assesses fraud or makes any medical or
insurance decision. It only reports what is present, absent or contradictory.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from config import settings
from models.schemas import (
    OPTIONAL_CLAIM_FIELDS,
    REQUIRED_CLAIM_FIELDS,
    ClaimData,
    Issue,
    ValidationResult,
)
from services import gemini, normalize
from services.normalize import clean_text, is_blank

logger = logging.getLogger("mediclaim.agent.validation")

AGENT_NAME = "Validation Agent"

SYSTEM_INSTRUCTION = """You are the Validation Agent of MediClaim, which prepares insurance claim forms.

You check a merged claim dataset for completeness and internal consistency before a draft claim form is produced.

STRICT LIMITS
- You do NOT approve, reject, authorise or deny any claim.
- You do NOT assess fraud, eligibility, medical necessity or whether a treatment was appropriate.
- You do NOT suggest a medical diagnosis, procedure or treatment.
- You never invent or "correct" a value. You only report what is wrong.

WHAT TO REPORT
1. `missing_required` - dotted paths that are essential for an insurance claim and are empty. Use the paths from the vocabulary you were given; do not invent new required fields.
2. `missing_optional` - dotted paths that are empty but nice to have.
3. `inconsistencies` - contradictions *inside the data*, each with severity "error" if it would block submission and "warning" otherwise. Examples: a discharge date earlier than the admission date; a billed total that does not equal the sum of the line items; a doctor name on the discharge summary that differs from the doctor name on the invoice; an insurance policy number that is obviously truncated.
4. `warnings` - weaker concerns: an unusually long stay, an unusually high amount, a missing ICD code, an address that looks partial, an identifier that is suspiciously short.

RULES
- Report at most 12 issues, most important first.
- Each `message` must be one short sentence a non-technical person can act on. No markdown, no code.
- Each `suggestion` must be a concrete action ("Add the doctor's registration number").
- `source` is one of: "document_understanding", "extraction", "validation".
- Return only the JSON object matching the schema, with every key present."""

PROMPT_TEMPLATE = """Validate the following claim dataset.

## Claim dataset
{claim_block}

## Field vocabulary
{vocabulary}

## Checked so far by deterministic rules (do not repeat these)
{already_checked}

Look for SEMANTIC problems that rules cannot detect: internal contradictions
between documents, values that clearly belong to a different person, clinical
text that does not match the billed items, truncated or mixed-up identifiers.

The JSON schema to follow exactly:
{schema}

Return the JSON object now. If you find no semantic problems, return empty lists
and `valid: true` - do not manufacture findings."""

_ALLOWED_ISSUE_FIELDS = {
    "billing.total_amount", "billing.currency", "billing.invoice_number",
    "billing.invoice_date", "billing.line_items", "billing.discount",
    "billing.paid_amount",
    "patient.date_of_birth", "patient.gender", "patient.name", "patient.phone",
    "patient.address", "patient.email",
    "treatment.admission_date", "treatment.discharge_date", "treatment.diagnosis",
    "treatment.treatment", "treatment.procedure", "treatment.icd_code",
    "insurance.policy_number", "insurance.member_id", "insurance.provider",
    "insurance.policy_start_date", "insurance.policy_end_date",
    "hospital.name", "hospital.address", "hospital.license_number",
    "doctor.name", "doctor.registration_number", "doctor.specialization",
    "doctor.designation", "claim.claim_type", "claim.claimed_by",
}


# ---------------------------------------------------------------------------
# Layer 1 - deterministic rules
# ---------------------------------------------------------------------------


def _missing(claim: ClaimData) -> Tuple[List[str], List[str]]:
    missing_required: List[str] = []
    for path in REQUIRED_CLAIM_FIELDS:
        if is_blank(normalize.get_path(claim, path)):
            missing_required.append(path)
    missing_optional: List[str] = []
    for path in OPTIONAL_CLAIM_FIELDS:
        if is_blank(normalize.get_path(claim, path)):
            missing_optional.append(path)
    return missing_required, missing_optional


def _check_dates(claim: ClaimData) -> List[Issue]:
    issues: List[Issue] = []
    admission = normalize.parse_date(claim.treatment.admission_date)
    discharge = normalize.parse_date(claim.treatment.discharge_date)
    invoice_date = normalize.parse_date(claim.billing.invoice_date)

    if claim.treatment.admission_date and not admission:
        issues.append(
            Issue(
                field="treatment.admission_date",
                severity="error",
                message="The admission date could not be read as a date.",
                suggestion="Enter the admission date as YYYY-MM-DD.",
                source="validation",
            )
        )
    if claim.treatment.discharge_date and not discharge:
        issues.append(
            Issue(
                field="treatment.discharge_date",
                severity="error",
                message="The discharge date could not be read as a date.",
                suggestion="Enter the discharge date as YYYY-MM-DD.",
                source="validation",
            )
        )
    if admission and discharge:
        if discharge < admission:
            issues.append(
                Issue(
                    field="treatment.discharge_date",
                    severity="error",
                    message="The discharge date is earlier than the admission date.",
                    suggestion="Correct whichever of the two dates is wrong.",
                    source="validation",
                )
            )
        else:
            days = (discharge - admission).days
            if days > 365:
                issues.append(
                    Issue(
                        field="treatment.discharge_date",
                        severity="warning",
                        message=f"The stay length of {days} days looks unusually long.",
                        suggestion="Confirm both dates against the discharge summary.",
                        source="validation",
                    )
                )
    if invoice_date and discharge and invoice_date < admission:
        issues.append(
            Issue(
                field="billing.invoice_date",
                severity="warning",
                message="The invoice is dated before the patient was admitted.",
                suggestion="Check the invoice date and the admission date.",
                source="validation",
            )
        )

    dob = normalize.parse_date(claim.patient.date_of_birth)
    if dob:
        age_years = (date.today() - dob).days // 365
        if age_years < 0 or age_years > 120:
            issues.append(
                Issue(
                    field="patient.date_of_birth",
                    severity="error",
                    message="The date of birth is not a plausible date.",
                    suggestion="Re-enter the date of birth as YYYY-MM-DD.",
                    source="validation",
                )
            )
    return issues


def _check_billing(claim: ClaimData) -> List[Issue]:
    issues: List[Issue] = []
    items = claim.billing.line_items

    if items:
        line_total = round(sum(item.amount for item in items), 2)
        if claim.billing.total_amount > 0:
            difference = abs(line_total - claim.billing.total_amount)
            tolerance = max(1.0, claim.billing.total_amount * 0.01)
            if difference > tolerance:
                issues.append(
                    Issue(
                        field="billing.total_amount",
                        severity="warning",
                        message=(
                            f"The line items add up to {line_total:,.2f} but the stated total is "
                            f"{claim.billing.total_amount:,.2f}."
                        ),
                        suggestion="Check the invoice for a discount, tax or partial payment.",
                        source="validation",
                    )
                )
        if claim.billing.discount > 0:
            after_discount = round(line_total - claim.billing.discount, 2)
            if claim.billing.total_amount > 0 and abs(after_discount - claim.billing.total_amount) > 1.0:
                issues.append(
                    Issue(
                        field="billing.discount",
                        severity="info",
                        message="The total does not match the line items minus the discount.",
                        suggestion="Confirm the discount and the final amount on the invoice.",
                        source="validation",
                    )
                )
        for index, item in enumerate(items, start=1):
            if item.quantity > 0 and item.unit_price > 0:
                expected = round(item.quantity * item.unit_price, 2)
                if abs(expected - item.amount) > 1.0:
                    issues.append(
                        Issue(
                            field="billing.line_items",
                            severity="info",
                            message=(
                                f"Line {index} ('{normalize.first_sentences(item.description, 1, 40)}') "
                                f"has a quantity x unit price that differs from its amount."
                            ),
                            suggestion="Review this line on the invoice.",
                            source="validation",
                        )
                    )
    elif claim.billing.total_amount > 0:
        issues.append(
            Issue(
                field="billing.line_items",
                severity="warning",
                message="No itemised billing breakdown was found.",
                suggestion="Upload the itemised invoice to show how the total is made up.",
                source="validation",
            )
        )

    if claim.billing.total_amount > 0 and is_blank(claim.billing.currency):
        issues.append(
            Issue(
                field="billing.currency",
                severity="error",
                message="A total amount is present but no currency was given.",
                suggestion="Enter the currency, for example INR.",
                source="validation",
            )
        )
    if claim.billing.total_amount > 0 and claim.billing.currency in {
        "INR", "USD", "EUR", "GBP", "AED",
    }:
        # A claim of exactly 1.00 or 1000.00 across a hospital stay is often a
        # data-entry slip, so flag it for a human rather than "fixing" it.
        if claim.billing.total_amount in {1.0, 2.0, 10.0, 100.0, 1000.0}:
            issues.append(
                Issue(
                    field="billing.total_amount",
                    severity="warning",
                    message=(
                        f"The total of {claim.billing.total_amount:,.2f} looks like a placeholder value."
                    ),
                    suggestion="Verify the total amount on the invoice.",
                    source="validation",
                )
            )
    if claim.billing.paid_amount > claim.billing.total_amount > 0:
        issues.append(
            Issue(
                field="billing.paid_amount",
                severity="warning",
                message="The amount paid is greater than the total billed.",
                suggestion="Check both amounts on the receipt.",
                source="validation",
            )
        )
    return issues


def _check_identifiers(claim: ClaimData) -> List[Issue]:
    issues: List[Issue] = []
    if claim.insurance.policy_number and len(claim.insurance.policy_number) < 5:
        issues.append(
            Issue(
                field="insurance.policy_number",
                severity="warning",
                message="The policy number looks too short to be complete.",
                suggestion="Check the policy number on the insurance card.",
                source="validation",
            )
        )
    if claim.insurance.member_id and normalize.similar(
        claim.insurance.member_id, claim.insurance.policy_number
    ):
        issues.append(
            Issue(
                field="insurance.member_id",
                severity="warning",
                message="The member ID and the policy number contain the same value.",
                suggestion="Confirm which is the member ID and which is the policy number.",
                source="validation",
            )
        )
    if claim.doctor.registration_number and len(claim.doctor.registration_number) < 5:
        issues.append(
            Issue(
                field="doctor.registration_number",
                severity="warning",
                message="The doctor's registration number looks incomplete.",
                suggestion="Re-read the registration number from the documents.",
                source="validation",
            )
        )
    if claim.patient.phone:
        digits = re.sub(r"\D", "", claim.patient.phone)
        if len(digits) < 7:
            issues.append(
                Issue(
                    field="patient.phone",
                    severity="warning",
                    message="The phone number is too short to be a valid number.",
                    suggestion="Enter the patient's phone number with the country code.",
                    source="validation",
                )
            )
    if claim.patient.name and len(claim.patient.name.split()) < 2:
        issues.append(
            Issue(
                field="patient.name",
                severity="warning",
                message="The patient's name looks incomplete.",
                suggestion="Enter the patient's full name as printed on the ID document.",
                source="validation",
            )
        )
    return issues


def _check_uncertain(claim: ClaimData) -> List[Issue]:
    """Fields the extraction agent flagged for a human to double-check."""
    issues: List[Issue] = []
    for path in claim.uncertain_fields:
        value = normalize.get_path(claim, path)
        if is_blank(value):
            continue
        note = claim.field_evidence.get(path, "")
        issues.append(
            Issue(
                field=path,
                severity="warning",
                message=(
                    f"'{normalize.humanise_path(path)}' needs confirmation"
                    + (f" ({clean_text(note)})." if note else ".")
                ),
                suggestion=f"Check '{normalize.humanise_path(path)}' against the uploaded documents.",
                source="extraction",
            )
        )
    return issues


def _check_documents(document_kinds: List[str]) -> List[Issue]:
    """A claim with no supporting document is still allowed, but flagged."""
    if not document_kinds:
        return [
            Issue(
                field="documents",
                severity="warning",
                message="No supporting documents were uploaded with this claim.",
                suggestion="Attach the medical bill, prescription or discharge summary.",
                source="validation",
            )
        ]
    return []


def _deterministic(
    claim: ClaimData, document_kinds: List[str]
) -> Tuple[ValidationResult, List[str]]:
    missing_required, missing_optional = _missing(claim)
    inconsistencies = _check_dates(claim) + _check_billing(claim) + _check_identifiers(claim)
    warnings = _check_uncertain(claim) + _check_documents(document_kinds)

    errors = [issue for issue in inconsistencies if issue.severity == "error"]
    checked = sum(
        1
        for path in list(REQUIRED_CLAIM_FIELDS) + list(OPTIONAL_CLAIM_FIELDS)
        if not is_blank(normalize.get_path(claim, path))
    )
    result = ValidationResult(
        valid=not missing_required and not errors,
        missing_required=missing_required,
        missing_optional=missing_optional,
        inconsistencies=inconsistencies,
        warnings=warnings,
        checked_fields=checked,
    )
    already_checked = [
        f"{issue.severity}: {issue.field} - {issue.message}" for issue in inconsistencies + warnings
    ]
    return result, already_checked


# ---------------------------------------------------------------------------
# Layer 2 - Gemini semantic review
# ---------------------------------------------------------------------------

def _claim_block(claim: ClaimData) -> str:
    import json

    payload = claim.model_dump(exclude={"missing_fields", "uncertain_fields", "field_evidence"})
    payload.pop("field_sources", None)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _merge_issues(
    deterministic: List[Issue], model_issues: List[Issue]
) -> List[Issue]:
    seen = {
        (issue.field, normalize.clean_text(issue.message).lower())
        for issue in deterministic
    }
    merged = list(deterministic)
    for issue in model_issues:
        if issue.field not in _ALLOWED_ISSUE_FIELDS and issue.field not in {
            "documents", "general",
        }:
            # The model invented a field path - keep the message, drop the path.
            issue = issue.model_copy(update={"field": "general"})
        key = (issue.field, normalize.clean_text(issue.message).lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append(issue)
    return merged[:12]


async def run(
    claim: ClaimData,
    document_kinds: Optional[List[str]] = None,
) -> Tuple[ValidationResult, bool, str]:
    """Validate a merged claim dataset.

    Returns ``(result, used_ai, message)``. ``result.valid`` is False as soon as
    a required field is missing or a blocking inconsistency is found; the
    pipeline then stops before generating a claim.
    """
    document_kinds = document_kinds or []
    result, already_checked = _deterministic(claim, document_kinds)
    used_ai = False
    degrade_note = ""

    if gemini.ai_mode() == "gemini":
        vocabulary = "\n".join(
            [f"- {path}: {label} (required)" for path, label in REQUIRED_CLAIM_FIELDS.items()]
            + [f"- {path}: {label} (optional)" for path, label in OPTIONAL_CLAIM_FIELDS.items()]
        )
        prompt = PROMPT_TEMPLATE.format(
            claim_block=_claim_block(claim),
            vocabulary=vocabulary,
            already_checked="\n".join(f"- {line}" for line in already_checked) or "- nothing",
            schema=gemini.schema_hint(ValidationResult),
        )
        model_result, degrade_note = await gemini.try_structured(
            model_name=settings.model_reasoning,
            system_instruction=SYSTEM_INSTRUCTION,
            prompt=prompt,
            response_model=ValidationResult,
            temperature=settings.temperature_reasoning,
        )
        if model_result is not None:
            used_ai = True
            result.inconsistencies = _merge_issues(
                result.inconsistencies, model_result.inconsistencies
            )
            result.warnings = _merge_issues(result.warnings, model_result.warnings)
            result.checked_fields = max(result.checked_fields, model_result.checked_fields)

    blocking = [
        issue
        for issue in result.inconsistencies
        if issue.severity == "error" and issue.field in _ALLOWED_ISSUE_FIELDS
    ]
    result.valid = not result.missing_required and not blocking
    result.missing_required = normalize.dedupe(result.missing_required)
    result.missing_optional = normalize.dedupe(result.missing_optional)

    if result.missing_required:
        message = f"{len(result.missing_required)} required field(s) still need to be provided."
        status = "failed"
    elif not result.valid:
        message = "Blocking inconsistencies must be fixed before a claim can be generated."
        status = "failed"
    elif result.warnings or result.inconsistencies:
        message = (
            f"Required fields are complete, with {len(result.warnings)} warning(s) to review."
        )
        status = "warning"
    else:
        message = f"All {result.checked_fields} required field(s) present and consistent."
        status = "completed"

    logger.info("Validation %s: %s", status, message)
    return result, used_ai, f"{message} {degrade_note}".strip()
