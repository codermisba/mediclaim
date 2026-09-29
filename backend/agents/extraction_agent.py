"""Agent 2 - Information Extraction.

Merges what the patient typed with what the Document Understanding Agent read,
removes duplicate/conflicting values and normalises names, dates, money and
identifiers into one clean :class:`ClaimData` object.

Precedence, applied deterministically after the model has proposed a merge:

    typed by the user  >  read from a document  >  derived (e.g. from line items)

Anything that is still absent goes into ``missing_fields``; anything present but
flagged as low-confidence by the document agent goes into ``uncertain_fields``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from config import settings
from models.schemas import (
    ClaimData,
    DocumentUnderstanding,
    LineItem,
    UserInput,
)
from services import llm, normalize
from services.normalize import clean_text, is_blank

logger = logging.getLogger("mediclaim.agent.extraction")

AGENT_NAME = "Information Extraction Agent"

SYSTEM_INSTRUCTION = """You are the Information Extraction Agent of MediClaim, which prepares insurance claim forms.

You receive (a) the structured snapshot that a document agent already read from the patient's uploaded files and (b) the details the patient typed into the form. You merge them into one clean claim dataset.

RULES
1. Never invent a value. If a field is empty in BOTH sources, leave it empty and list its dotted path in `missing_fields`.
2. Prefer the value the patient typed over a value read from a document. If a typed value is blank, use the document value.
3. When the typed value and a document value disagree and both are clearly present, prefer the typed value and list that field in `uncertain_fields` so a human can confirm it.
4. Normalise, do not rewrite meaning:
   - names: remove honorifics (Dr., Mr.) and fix spacing/case only;
   - dates: ISO format YYYY-MM-DD;
   - gender: Male / Female / Other;
   - amounts: positive numbers rounded to 2 decimals;
   - currency: ISO code (INR, USD, EUR, GBP, AED...);
   - identifiers (policy number, member id, registration number, invoice number): keep the exact characters that were supplied; only remove spaces and dashes that are clearly formatting.
5. Copy the diagnosis, treatment and procedure text from the source. Do not paraphrase clinical text, do not add a medical opinion, do not infer a condition that is not written down.
6. `field_sources` records where each value came from: "user", "document", "derived" or "sample". Use "user" only for fields the patient actually typed.
7. Return only the JSON object matching the schema, with every key present."""

PROMPT_TEMPLATE = """Merge the two sources below into one claim dataset.

## 1. Values read from the uploaded documents
{document_block}

## 2. Values typed by the patient into the form
{user_block}

## Merging rules for this claim
{conflict_block}

## Field map (dotted path -> meaning)
{field_map}

The JSON schema to follow exactly:
{schema}

Return the JSON object now. Empty strings and 0 mean "not provided by either source" and the same dotted path must appear in `missing_fields`."""

#: Human-readable meaning for every dotted path the agent may fill.
FIELD_HELP: Dict[str, str] = {
    "patient.name": "patient's full legal name as printed on the documents",
    "patient.date_of_birth": "date of birth (YYYY-MM-DD)",
    "patient.gender": "Male, Female or Other",
    "patient.phone": "contact phone number",
    "patient.email": "contact email address",
    "patient.address": "residential address",
    "patient.patient_id": "hospital record / UHID / MRN",
    "insurance.provider": "insurer or health-plan company name",
    "insurance.policy_number": "policy number",
    "insurance.member_id": "member / insured id",
    "insurance.group_number": "group number",
    "insurance.claim_number": "claim reference number, if the insurer already issued one",
    "insurance.policy_holder": "policy holder name",
    "insurance.policy_start_date": "policy start date",
    "insurance.policy_end_date": "policy end date",
    "hospital.name": "hospital / clinic / diagnostic centre name",
    "hospital.address": "full hospital address",
    "hospital.phone": "hospital phone number",
    "hospital.email": "hospital email",
    "hospital.license_number": "hospital registration or licence number",
    "hospital.facility_type": "Hospital, Clinic, Diagnostic Centre, Day Care...",
    "doctor.name": "treating doctor's full name",
    "doctor.registration_number": "medical council registration number",
    "doctor.specialization": "specialty / department",
    "doctor.designation": "designation or qualifications",
    "doctor.phone": "doctor contact number",
    "treatment.diagnosis": "final diagnosis, exactly as written in the documents",
    "treatment.icd_code": "ICD code if printed",
    "treatment.treatment": "treatment / course of treatment",
    "treatment.procedure": "procedure or surgery performed",
    "treatment.admission_date": "date of admission (YYYY-MM-DD)",
    "treatment.discharge_date": "date of discharge (YYYY-MM-DD)",
    "treatment.clinical_notes": "brief factual clinical summary from the documents",
    "treatment.treatment_type": "Inpatient, Outpatient, Day Care, Diagnostic",
    "billing.total_amount": "total claimable amount, a positive number",
    "billing.currency": "ISO currency code, e.g. INR",
    "billing.invoice_number": "invoice or bill number",
    "billing.invoice_date": "invoice date (YYYY-MM-DD)",
    "billing.discount": "discount applied, if shown",
    "billing.paid_amount": "amount already paid by the patient, if shown",
    "claim.claim_type": "short claim category, e.g. Hospitalisation Cash Claim",
    "claim.claimed_by": "who submits the claim: Patient or Hospital",
    "claim.place_of_treatment": "City / Country of treatment",
}

#: How to normalise a dotted path once a value has been chosen.
_STRING_RULES = {
    "patient.name": normalize.normalize_person_name,
    "doctor.name": normalize.normalize_person_name,
    "insurance.policy_holder": normalize.normalize_person_name,
    "patient.gender": normalize.normalize_gender,
    "insurance.policy_number": normalize.normalize_identifier,
    "insurance.member_id": normalize.normalize_identifier,
    "insurance.group_number": normalize.normalize_identifier,
    "insurance.claim_number": normalize.normalize_identifier,
    "doctor.registration_number": normalize.normalize_identifier,
    "hospital.license_number": normalize.normalize_identifier,
    "patient.patient_id": normalize.normalize_identifier,
    "billing.invoice_number": normalize.normalize_identifier,
    "patient.date_of_birth": normalize.normalize_date,
    "treatment.admission_date": normalize.normalize_date,
    "treatment.discharge_date": normalize.normalize_date,
    "billing.invoice_date": normalize.normalize_date,
    "insurance.policy_start_date": normalize.normalize_date,
    "insurance.policy_end_date": normalize.normalize_date,
    "billing.currency": normalize.normalize_currency,
}

_MONEY_PATHS = {
    "billing.total_amount",
    "billing.discount",
    "billing.paid_amount",
}


def _typed_values(user_input: UserInput) -> Dict[str, str]:
    """Dotted path -> raw typed string, for the fields the patient filled in."""
    mapping = {
        "patient.name": user_input.patient.name,
        "patient.date_of_birth": user_input.patient.date_of_birth,
        "patient.gender": user_input.patient.gender,
        "patient.phone": user_input.patient.phone,
        "patient.email": user_input.patient.email,
        "patient.address": user_input.patient.address,
        "insurance.provider": user_input.insurance.provider,
        "insurance.policy_number": user_input.insurance.policy_number,
        "insurance.member_id": user_input.insurance.member_id,
        "insurance.group_number": user_input.insurance.group_number,
        "insurance.policy_holder": user_input.insurance.policy_holder,
        "hospital.name": user_input.hospital.name,
        "hospital.address": user_input.hospital.address,
        "hospital.phone": user_input.hospital.phone,
        "doctor.name": user_input.doctor.name,
        "doctor.registration_number": user_input.doctor.registration_number,
        "doctor.specialization": user_input.doctor.specialization,
        "treatment.diagnosis": user_input.treatment.diagnosis,
        "treatment.admission_date": user_input.treatment.admission_date,
        "treatment.discharge_date": user_input.treatment.discharge_date,
        "treatment.treatment": user_input.treatment.treatment,
        "billing.total_amount": user_input.billing.total_amount,
        "billing.currency": user_input.billing.currency,
        "billing.invoice_number": user_input.billing.invoice_number,
    }
    return {path: str(value) for path, value in mapping.items() if not is_blank(value)}


def _document_values(understanding: DocumentUnderstanding) -> Dict[str, Any]:
    """Dotted path -> value read from the documents."""
    return {
        "patient.name": understanding.patient_name,
        "patient.date_of_birth": understanding.patient_date_of_birth,
        "patient.gender": understanding.patient_gender,
        "patient.phone": understanding.patient_phone,
        "patient.address": understanding.patient_address,
        "patient.patient_id": understanding.patient_id,
        "insurance.provider": understanding.insurance_provider,
        "insurance.policy_number": understanding.insurance_policy_number,
        "insurance.member_id": understanding.insurance_member_id,
        "insurance.group_number": understanding.insurance_group_number,
        "insurance.claim_number": understanding.insurance_claim_number,
        "insurance.policy_holder": understanding.insurance_policy_holder,
        "hospital.name": understanding.hospital_name,
        "hospital.address": understanding.hospital_address,
        "hospital.phone": understanding.hospital_phone,
        "hospital.license_number": understanding.hospital_license_number,
        "doctor.name": understanding.doctor_name,
        "doctor.registration_number": understanding.doctor_registration_number,
        "doctor.specialization": understanding.doctor_specialization,
        "doctor.designation": understanding.doctor_designation,
        "treatment.diagnosis": understanding.diagnosis,
        "treatment.icd_code": understanding.icd_code,
        "treatment.treatment": understanding.treatment,
        "treatment.procedure": understanding.procedure,
        "treatment.admission_date": understanding.admission_date,
        "treatment.discharge_date": understanding.discharge_date,
        "treatment.clinical_notes": understanding.clinical_notes,
        "billing.total_amount": understanding.total_amount,
        "billing.currency": understanding.currency,
        "billing.invoice_number": understanding.invoice_number,
        "billing.invoice_date": understanding.invoice_date,
    }


def _apply(path: str, raw: Any) -> Any:
    """Normalise one value according to the rules for its path."""
    if path in _MONEY_PATHS:
        return normalize.parse_amount(raw)
    if path in _STRING_RULES:
        return _STRING_RULES[path](raw)
    return clean_text(raw)


def _resolve(
    typed: Dict[str, str],
    documents: Dict[str, Any],
    model: Dict[str, Any],
    low_confidence: set[str],
    sample_claim: bool,
) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, str], List[str], List[str]]:
    """Deterministic merge. Returns (values, sources, evidence, missing, uncertain)."""
    values: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    evidence: Dict[str, str] = {}
    uncertain: List[str] = []

    for path in FIELD_HELP:
        typed_raw = typed.get(path)
        doc_raw = documents.get(path)
        model_raw = model.get(path)

        chosen: Any = None
        source = ""
        if typed_raw is not None:
            chosen, source = typed_raw, "user"
        elif not is_blank(doc_raw):
            chosen, source = doc_raw, "document"
        elif not is_blank(model_raw):
            chosen, source = model_raw, "document"
            if sample_claim:
                source = "sample"

        if source == "" or is_blank(chosen):
            continue

        value = _apply(path, chosen)
        if is_blank(value):
            continue

        values[path] = value
        sources[path] = "sample" if sample_claim and source == "document" else source
        if path in low_confidence:
            uncertain.append(path)
            evidence[path] = "low confidence in the document"
        elif source == "document":
            evidence[path] = "read from uploaded document"

        # Typed value conflicts with a document value -> human should confirm.
        if typed_raw is not None and not is_blank(doc_raw):
            typed_value = _apply(path, typed_raw)
            doc_value = _apply(path, doc_raw)
            if isinstance(typed_value, float) and isinstance(doc_value, float):
                conflict = abs(typed_value - doc_value) > 0.01
            else:
                conflict = not normalize.similar(str(typed_value), str(doc_value))
            if conflict and path not in uncertain:
                uncertain.append(path)
                evidence[path] = "typed value differs from the document value"

    # Line items: keep the itemised breakdown from the invoice.
    if understanding_line_items := documents.get("__line_items__"):
        # ``values`` is applied with dotted-path writes, which bypass Pydantic
        # coercion, so build real models here rather than plain dicts.
        values["billing.line_items"] = [
            item if isinstance(item, LineItem) else LineItem(**item)
            for item in understanding_line_items
        ]
        sources["billing.line_items"] = "document"

    missing = [path for path in FIELD_HELP if is_blank(values.get(path))]
    return values, sources, evidence, missing, sorted(set(uncertain))


def _derive(claim: ClaimData) -> List[str]:
    """Consistent, non-invented values computed from what we already have."""
    derived: List[str] = []

    if is_blank(claim.billing.total_amount) and claim.billing.line_items:
        claim.billing.total_amount = round(
            sum(item.amount for item in claim.billing.line_items), 2
        )
        if claim.billing.total_amount > 0:
            derived.append("billing.total_amount")

    if is_blank(claim.billing.currency):
        for hint in ("inr", "rupee", "rs"):
            blob = f"{claim.hospital.name} {claim.insurance.provider}".lower()
            if hint in blob:
                claim.billing.currency = "INR"
                derived.append("billing.currency")
                break

    if is_blank(claim.claim.claim_type):
        claim.claim.claim_type = "Hospitalisation Cash Claim"
        derived.append("claim.claim_type")
    if is_blank(claim.claim.claimed_by):
        claim.claim.claimed_by = "Patient"
        derived.append("claim.claimed_by")

    return derived


def _build(values: Dict[str, Any], understanding: DocumentUnderstanding) -> ClaimData:
    claim = ClaimData()
    for path, value in values.items():
        normalize.set_path(claim, path, value)
    claim.billing.line_items = values.get("billing.line_items") or understanding.line_items
    return claim


def _model_block(payload: Dict[str, Any], title: str) -> str:
    if not payload:
        return f"## {title}\n(nothing provided)"
    lines = [f"## {title}"]
    for path, value in payload.items():
        lines.append(f"- {path}: {value}")
    return "\n".join(lines)


def _conflict_lines(typed: Dict[str, str], documents: Dict[str, Any]) -> str:
    lines: List[str] = []
    for path, typed_value in typed.items():
        doc_value = documents.get(path)
        if is_blank(doc_value):
            continue
        typed_norm = _apply(path, typed_value)
        doc_norm = _apply(path, doc_value)
        if isinstance(typed_norm, float) and isinstance(doc_norm, float):
            differs = abs(typed_norm - doc_norm) > 0.01
        else:
            differs = not normalize.similar(str(typed_norm), str(doc_norm))
        if differs:
            lines.append(
                f"- {path}: typed as '{typed_norm}' but the documents show '{doc_norm}'. "
                "Use the typed value and add this field to `uncertain_fields`."
            )
    if not lines:
        return "The typed values and the document values agree, or only one source has a value."
    return "\n".join(lines)


async def run(
    understanding: DocumentUnderstanding,
    user_input: UserInput,
    sample_claim: bool = False,
) -> Tuple[ClaimData, bool, str]:
    """Merge typed + document data into a single :class:`ClaimData`.

    Returns ``(claim_data, used_ai, message)``.
    """
    typed = _typed_values(user_input)
    documents = _document_values(understanding)
    documents["__line_items__"] = [item.model_dump() for item in understanding.line_items]
    low_confidence = set(understanding.low_confidence_fields)

    model_values: Dict[str, Any] = {}
    used_ai = False
    degrade_note = ""
    if llm.ai_mode() != "offline_deterministic":
        prompt = PROMPT_TEMPLATE.format(
            document_block=_model_block(
                {k: v for k, v in documents.items() if not is_blank(v) and k != "__line_items__"},
                "1. Values read from the uploaded documents",
            ),
            user_block=_model_block(typed, "2. Values typed by the patient into the form"),
            conflict_block=_conflict_lines(typed, documents),
            field_map="\n".join(f"- {path}: {meaning}" for path, meaning in FIELD_HELP.items()),
            schema=llm.schema_hint(ClaimData),
        )
        model_result, degrade_note = await llm.try_structured(
            model_name=settings.model_extraction,
            system_instruction=SYSTEM_INSTRUCTION,
            prompt=prompt,
            response_model=ClaimData,
            temperature=0.0,
        )
        if model_result is not None:
            model_values = model_result.model_dump()
            used_ai = True
    if not used_ai:
        logger.info("Gemini unavailable - extraction agent used deterministic merge only")

    values, sources, evidence, missing, uncertain = _resolve(
        typed, documents, model_values, low_confidence, sample_claim
    )
    claim = _build(values, understanding)

    for path in _derive(claim):
        sources.setdefault(path, "derived")

    # A normalised claim may have no conflict left, so re-verify the flags.
    uncertain = [
        path
        for path in uncertain
        if not is_blank(normalize.get_path(claim, path))
    ]
    for path in understanding.low_confidence_fields:
        if not is_blank(normalize.get_path(claim, path)) and path not in uncertain:
            uncertain.append(path)
    uncertain = sorted(set(uncertain))

    missing = [
        path
        for path in FIELD_HELP
        if is_blank(normalize.get_path(claim, path)) and path not in claim.billing.line_items
    ]
    if is_blank(claim.billing.line_items):
        missing.append("billing.line_items")

    claim.missing_fields = sorted(set(missing))
    claim.uncertain_fields = uncertain
    claim.field_sources = sources
    claim.field_evidence = evidence

    if sample_claim:
        message = "Merged the sample patient details with the uploaded documents."
    elif used_ai:
        message = f"Merged {len(typed)} typed and {len(documents) - 1} extracted field(s)."
    else:
        message = "Merged typed and document fields (deterministic mode, no AI)."

    return claim, used_ai, f"{message} {degrade_note}".strip()
