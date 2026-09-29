"""Agent 4 - Claim Generation.

Turns a validated :class:`ClaimData` into a standardised insurance claim form
as **structured JSON only**. The model never touches layout, fonts or pages -
it fills in values such as the narrative, the claim category and the itemised
amounts, and Python owns the numbering, the arithmetic and the rendering.

That boundary is the reason the output PDF is predictable: every character on
the page comes from :class:`GeneratedClaim`, which is fully inspectable before
a single pixel is drawn.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import List, Tuple

from config import settings
from models.schemas import ClaimData, ClaimLineItem, GeneratedClaim, ValidationResult
from services import llm, normalize
from services.normalize import clean_text, is_blank

logger = logging.getLogger("mediclaim.agent.generation")

AGENT_NAME = "Claim Generation Agent"

SYSTEM_INSTRUCTION = """You are the Claim Generation Agent of MediClaim, which prepares insurance claim forms.

You turn an already-validated claim dataset into the values of a standard insurance claim form. You produce JSON data only - you do not design, lay out or render a document.

RULES
1. Use only values that appear in the dataset you are given. Never add a diagnosis, procedure, provider, date or amount that is not there. Never round a total except to 2 decimals.
2. `narrative` is a factual 2-4 sentence summary for the insurer: who was treated, where, the diagnosis, the procedure or treatment, the admission and discharge dates, and the amount claimed. Write it in plain third-person English. No markdown, no bullet points, no headings, no legal conclusions, no "approved" or "eligible" language.
3. `line_items` is the itemised claim. If the dataset already has billing line items, copy them exactly, one line per item, with the description and amount unchanged. Only if there are no line items may you group the claim into a small number of high-level lines that are each directly supported by the dataset (for example "Room charges", "Professional fees", "Medicines and consumables" with amounts that sum exactly to the total). Never invent an amount that does not add up to the total.
4. `claim_type` is a short category such as "Hospitalisation Cash Claim", "OPD Claim", "Surgical Claim" or "Day Care Claim", chosen from the treatment facts.
5. `service_period` is the treatment period, formatted as "01 - 05 Mar 2026", or empty if the dates are missing.
6. `place_of_treatment` is the city and country of the hospital, or empty if unknown.
7. `claimed_by` is "Patient" or "Hospital".
8. Return only the JSON object matching the schema, with every key present."""

PROMPT_TEMPLATE = """Build the claim form values from this validated claim dataset.

## Validated claim dataset
{claim_block}

## Validation outcome
{validation_block}

## Documents attached to this claim
{document_block}

Rules specific to this claim:
{rule_block}

The JSON schema to follow exactly:
{schema}

Return the JSON object now."""


def make_claim_number(claim_id: str) -> str:
    """Deterministic, human-quotable claim reference: MC-YYYYMMDD-XXXXXX."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = "".join(ch for ch in claim_id if ch.isalnum())[-6:].upper() or uuid.uuid4().hex[:6]
    return f"MC-{stamp}-{suffix}"


def _service_period(claim: ClaimData) -> str:
    admission = normalize.parse_date(claim.treatment.admission_date)
    discharge = normalize.parse_date(claim.treatment.discharge_date)
    if admission and discharge:
        if admission.year == discharge.year and admission.month == discharge.month:
            return f"{admission.day:02d} - {discharge.strftime('%d %b %Y')}"
        return f"{admission.strftime('%d %b %Y')} - {discharge.strftime('%d %b %Y')}"
    if admission:
        return f"From {admission.strftime('%d %b %Y')}"
    if discharge:
        return f"Until {discharge.strftime('%d %b %Y')}"
    return ""


def _default_claim_type(claim: ClaimData) -> str:
    haystack = f"{claim.treatment.treatment_type} {claim.treatment.procedure} {claim.claim.claim_type}".lower()
    if "day care" in haystack or "daycare" in haystack:
        return "Day Care Claim"
    if "outpatient" in haystack or "opd" in haystack:
        return "OPD Claim"
    if claim.treatment.admission_date and claim.treatment.discharge_date:
        return "Hospitalisation Cash Claim"
    return "Reimbursement Claim"


def _place_of_treatment(claim: ClaimData) -> str:
    parts = normalize.split_multi(claim.hospital.address)
    city = ""
    for candidate in reversed(parts):
        if not re_looks_like_state(candidate):
            city = candidate
            break
    if not city:
        city = parts[-1] if parts else ""
    city = re.sub(r"\b(pin|pincode|postal|zip)\b.*$", "", city, flags=2).strip(" ,")
    return city if city and len(city) < 40 else ""


def re_looks_like_state(token: str) -> bool:
    """Very small heuristic so a pin code is not mistaken for a city."""
    text = clean_text(token).lower()
    if not text or len(text) > 30:
        return True
    if re.fullmatch(r"\d{4,10}", text.replace("-", "")):
        return True
    if re.search(r"pin|pincode|postal|zip|code", text):
        return True
    return False


def _deterministic_narrative(claim: ClaimData) -> str:
    """Factual fallback narrative built only from dataset values."""
    who = claim.patient.name or "The patient"
    where = claim.hospital.name or "the treating facility"
    sentences: List[str] = []
    sentences.append(
        f"{who} was treated at {where}"
        + (f" by {claim.doctor.name}" if claim.doctor.name else "")
        + "."
    )
    if claim.treatment.diagnosis:
        sentences.append(
            f"The diagnosis recorded was "
            f"{normalize.first_sentences(claim.treatment.diagnosis, 1, 200).rstrip('.')}."
        )
    if claim.treatment.procedure or claim.treatment.treatment:
        detail = claim.treatment.procedure or claim.treatment.treatment
        sentences.append(f"The treatment provided was {normalize.first_sentences(detail, 1, 200)}.")
    if claim.treatment.admission_date and claim.treatment.discharge_date:
        sentences.append(
            f"The period of hospitalisation was {normalize.human_date(claim.treatment.admission_date)} "
            f"to {normalize.human_date(claim.treatment.discharge_date)}."
        )
    elif claim.treatment.admission_date:
        sentences.append(f"The patient was admitted on {normalize.human_date(claim.treatment.admission_date)}.")
    if claim.billing.total_amount > 0:
        sentences.append(
            f"The total amount claimed is {normalize.format_money(claim.billing.total_amount, claim.billing.currency)}"
            + (f" as per invoice {claim.billing.invoice_number}." if claim.billing.invoice_number else ".")
        )
    return " ".join(sentences)


def _fallback_line_items(claim: ClaimData) -> List[ClaimLineItem]:
    """High-level groups that add up exactly to the claimed total."""
    total = claim.billing.total_amount
    if total <= 0:
        return []
    if claim.billing.line_items:
        return [
            ClaimLineItem(
                description=clean_text(item.description),
                category=clean_text(item.category) or "Billable item",
                amount=round(item.amount, 2),
            )
            for item in claim.billing.line_items
            if item.amount > 0
        ]
    room = 0.40 * total if claim.treatment.admission_date else 0.0
    professional = 0.25 * total
    consumables = 0.20 * total
    diagnostics = total - room - professional - consumables
    groups = [
        ("Professional / doctor fees", professional, "Professional fees"),
        ("Medicines, consumables and pharmacy", consumables, "Consumables"),
        ("Diagnostics and investigations", diagnostics, "Diagnostics"),
    ]
    if room > 0:
        groups.insert(0, ("Room charges and hospital facilities", room, "Room charges"))
    return [
        ClaimLineItem(
            description=f"{description} (estimated from the lump-sum total)",
            category=category,
            amount=round(amount, 2),
        )
        for description, amount, category in groups
        if amount > 0
    ]


def _normalise_totals(generated: GeneratedClaim, claim: ClaimData) -> GeneratedClaim:
    """Python owns the arithmetic. The model's numbers never win by default."""
    total = claim.billing.total_amount
    lines = [item for item in generated.line_items if item.amount > 0]
    if lines:
        subtotal = round(sum(item.amount for item in lines), 2)
        if total > 0 and abs(subtotal - total) > max(1.0, total * 0.02):
            # Model's itemisation does not reconcile with the invoiced total.
            # Fall back to a deterministic split that does.
            lines = _fallback_line_items(claim)
            subtotal = round(sum(item.amount for item in lines), 2)
    else:
        lines = _fallback_line_items(claim)
        subtotal = round(sum(item.amount for item in lines), 2)

    discount = round(claim.billing.discount, 2) if claim.billing.discount > 0 else 0.0
    generated.line_items = lines
    generated.sub_total = subtotal
    generated.discount = discount
    generated.total = round(subtotal - discount, 2)
    if total > 0 and discount == 0:
        generated.total = total
    generated.claim_amount = generated.total
    generated.currency = normalize.normalize_currency(generated.currency) or normalize.normalize_currency(
        claim.billing.currency
    )
    if not generated.currency:
        generated.currency = "INR"
    generated.currency_symbol = normalize.currency_symbol(generated.currency)
    if not generated.service_period:
        generated.service_period = _service_period(claim)
    if not generated.claim_type:
        generated.claim_type = _default_claim_type(claim)
    if not generated.place_of_treatment:
        generated.place_of_treatment = _place_of_treatment(claim)
    if not generated.claimed_by:
        generated.claimed_by = clean_text(claim.claim.claimed_by) or "Patient"
    return generated


def _rule_block(claim: ClaimData) -> str:
    lines: List[str] = []
    if claim.billing.line_items:
        total = round(sum(item.amount for item in claim.billing.line_items), 2)
        lines.append(
            f"- The invoice has {len(claim.billing.line_items)} line item(s) summing to "
            f"{total:,.2f} {claim.billing.currency}. Copy them exactly."
        )
    else:
        lines.append(
            f"- There is no itemised breakdown. Group the lump-sum total of "
            f"{claim.billing.total_amount:,.2f} {claim.billing.currency} into a few "
            "high-level lines that add up exactly to the total, and say in each "
            "description that the split is estimated."
        )
    if claim.billing.discount > 0:
        lines.append(
            f"- A discount of {claim.billing.discount:,.2f} is stated on the invoice; the "
            "final claim total is the line sum minus that discount."
        )
    if is_blank(claim.treatment.diagnosis):
        lines.append("- The diagnosis is missing. Do not state or imply one in the narrative.")
    if is_blank(claim.doctor.name):
        lines.append("- The treating doctor is unknown. Do not name a doctor in the narrative.")
    if not claim.treatment.admission_date or not claim.treatment.discharge_date:
        lines.append("- One or both stay dates are missing; describe only the dates you have.")
    return "\n".join(lines)


async def run(
    claim: ClaimData,
    validation: ValidationResult,
    document_filenames: List[str],
    claim_id: str,
) -> Tuple[GeneratedClaim, bool, str]:
    """Produce the structured claim form.

    Returns ``(generated, used_ai, message)``.
    """
    generated = GeneratedClaim(
        claim_number=make_claim_number(claim_id),
        claim_type=_default_claim_type(claim),
        currency=claim.billing.currency or "INR",
        narrative=_deterministic_narrative(claim),
        service_period=_service_period(claim),
        place_of_treatment=_place_of_treatment(claim),
        claimed_by=clean_text(claim.claim.claimed_by) or "Patient",
        documents_used=document_filenames,
        missing_fields=list(claim.missing_fields),
        uncertain_fields=list(claim.uncertain_fields),
    )
    used_ai = False
    degrade_note = ""

    if llm.ai_mode() != "offline_deterministic":
        prompt = PROMPT_TEMPLATE.format(
            claim_block=claim.model_dump_json(indent=2, exclude={"field_evidence"}),
            validation_block=(
                f"- required fields missing: {', '.join(validation.missing_required) or 'none'}\n"
                f"- blocking inconsistencies: {len([i for i in validation.inconsistencies if i.severity == 'error'])}\n"
                f"- warnings: {len(validation.warnings)}"
            ),
            document_block="\n".join(f"- {name}" for name in document_filenames) or "- none",
            rule_block=_rule_block(claim),
            schema=llm.schema_hint(GeneratedClaim),
        )
        model_result, degrade_note = await llm.try_structured(
            model_name=settings.model_extraction,
            system_instruction=SYSTEM_INSTRUCTION,
            prompt=prompt,
            response_model=GeneratedClaim,
            temperature=0.0,
        )
        if model_result is not None:
            used_ai = True
            # Keep the deterministic identifiers, then adopt the model's content.
            generated.narrative = clean_text(model_result.narrative) or generated.narrative
            generated.line_items = model_result.line_items
            generated.claim_type = clean_text(model_result.claim_type) or generated.claim_type
            generated.service_period = (
                clean_text(model_result.service_period) or generated.service_period
            )
            generated.place_of_treatment = (
                clean_text(model_result.place_of_treatment) or generated.place_of_treatment
            )
            generated.claimed_by = clean_text(model_result.claimed_by) or generated.claimed_by
    if not used_ai:
        logger.info("Gemini unavailable - generation agent used the deterministic builder")

    generated = _normalise_totals(generated, claim)
    generated.generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    generated.missing_fields = list(claim.missing_fields)
    generated.uncertain_fields = list(claim.uncertain_fields)
    generated.documents_used = document_filenames

    message = (
        f"Claim {generated.claim_number} generated for "
        f"{normalize.format_money(generated.claim_amount, generated.currency)}."
    )
    return generated, used_ai, f"{message} {degrade_note}".strip()
