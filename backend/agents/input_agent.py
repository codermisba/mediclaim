"""Input Agent (stage 1 of the pipeline).

Collects everything the user supplied - typed form fields, free-text notes and
uploaded files - and normalises the typed values in place so that every later
stage sees the same clean representation no matter where a value came from.

Deliberately deterministic: nothing is inferred here. The agent only reports
what actually arrived, which is what the "Input" pipeline stage displays.
"""

from __future__ import annotations

import logging
from typing import Tuple

from models.schemas import ClaimRecord
from services import normalize

logger = logging.getLogger("mediclaim.agent.input")

AGENT_NAME = "Input Agent"

SYSTEM_INSTRUCTION = (
    "You normalise the details a policyholder typed into the claim form. "
    "You never add information and you never change the meaning of a value: "
    "only spacing, casing, date format, amount formatting and currency codes."
)


def run(record: ClaimRecord) -> Tuple[ClaimRecord, str, str]:
    """Normalise the typed input in place.

    Returns ``(record, message, detail)`` where ``message`` is the short
    user-facing status and ``detail`` is the supporting count.
    """
    typed = record.input_data
    typed.patient.name = normalize.normalize_person_name(typed.patient.name)
    typed.patient.date_of_birth = normalize.normalize_date(typed.patient.date_of_birth)
    typed.patient.gender = normalize.normalize_gender(typed.patient.gender)
    typed.patient.phone = normalize.clean_text(typed.patient.phone)
    typed.patient.email = normalize.clean_text(typed.patient.email).lower()
    typed.patient.address = normalize.clean_text(typed.patient.address)

    typed.insurance.provider = normalize.clean_text(typed.insurance.provider)
    typed.insurance.policy_number = normalize.normalize_identifier(typed.insurance.policy_number)
    typed.insurance.member_id = normalize.normalize_identifier(typed.insurance.member_id)
    typed.insurance.group_number = normalize.normalize_identifier(typed.insurance.group_number)
    typed.insurance.policy_holder = normalize.normalize_person_name(
        typed.insurance.policy_holder
    )

    typed.hospital.name = normalize.normalize_person_name(typed.hospital.name)
    typed.hospital.address = normalize.clean_text(typed.hospital.address)
    typed.hospital.phone = normalize.clean_text(typed.hospital.phone)

    typed.doctor.name = normalize.normalize_person_name(typed.doctor.name)
    typed.doctor.registration_number = normalize.normalize_identifier(
        typed.doctor.registration_number
    )
    typed.doctor.specialization = normalize.clean_text(typed.doctor.specialization)

    typed.treatment.diagnosis = normalize.clean_text(typed.treatment.diagnosis)
    typed.treatment.treatment = normalize.clean_text(typed.treatment.treatment)
    typed.treatment.admission_date = normalize.normalize_date(typed.treatment.admission_date)
    typed.treatment.discharge_date = normalize.normalize_date(typed.treatment.discharge_date)

    amount = normalize.parse_amount(typed.billing.total_amount)
    typed.billing.total_amount = normalize.format_amount(amount) if amount > 0 else ""
    typed.billing.currency = normalize.normalize_currency(typed.billing.currency)
    typed.billing.invoice_number = normalize.clean_text(typed.billing.invoice_number)

    typed.notes = normalize.clean_text(typed.notes)

    filled = sum(
        1
        for section in (
            typed.patient, typed.insurance, typed.hospital,
            typed.doctor, typed.treatment, typed.billing,
        )
        for value in section.model_dump().values()
        if not normalize.is_blank(value)
    )
    documents = len(record.documents)

    if not filled and not documents and not typed.notes:
        message = "No details received yet"
        detail = "Fill in the form or upload at least one document"
    elif documents:
        message = f"Received {documents} document(s) and {filled} typed field(s)"
        detail = "Details are ready for the agents"
    else:
        message = f"Received {filled} typed field(s)"
        detail = "No documents uploaded - values must come from the form"

    logger.info("Input stage: %s (%s)", message, detail)
    return record, message, detail


__all__ = ["AGENT_NAME", "SYSTEM_INSTRUCTION", "run"]
