"""Deterministic offline fallback used **only** when ``GEMINI_API_KEY`` is unset.

MediClaim is a Gemini-first application - this module is not a replacement for
the model and is never used when a key is configured. Its only job is to keep
the end-to-end demo runnable (and the backend testable) without a key:

* PDFs: read the *embedded text layer* with ``pypdf`` and pull a small set of
  obvious label/value pairs. Scanned PDFs and every image are simply reported
  as unreadable, so nothing is ever invented.
* Every value found is recorded with ``field_sources='offline_heuristic'`` and a
  warning is attached to the claim so the UI can label the result honestly.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Sequence, Tuple

from models.schemas import DocumentMeta, DocumentUnderstanding, LineItem
from services import normalize

logger = logging.getLogger("mediclaim.offline")

#: label -> (claim path, converter)
_LABEL_PATTERNS: List[Tuple[str, str, str]] = [
    (r"patient\s*name|^name$", "patient.name", "name"),
    (r"date\s*of\s*birth|d\.?o\.?b\.?|(?:date of birth)", "patient.date_of_birth", "date"),
    (r"\bgender\b|\bsex\b", "patient.gender", "text"),
    (r"(?:mobile|contact\s*(?:number)?|telephone|patient\s*phone)", "patient.phone", "text"),
    (r"(?:patient\s*address|address)", "patient.address", "text"),
    (r"(?:patient\s*id|uhid|mrn|record\s*id|patient\s*code)", "patient.patient_id", "id"),
    (r"(?:insurer|insurance\s*(?:company|provider)|policy\s*holder\s*insurer|company)", "insurance.provider", "text"),
    (r"policy\s*(?:no|number|number)\.?", "insurance.policy_number", "id"),
    (r"member\s*id|member\s*no|insured\s*id", "insurance.member_id", "id"),
    (r"group\s*(?:no|number|id)", "insurance.group_number", "id"),
    (r"claim\s*(?:no|number)", "insurance.claim_number", "id"),
    (r"policy\s*holder", "insurance.policy_holder", "name"),
    (r"(?:hospital|clinic|facility|centre|center)\s*name|^hospital$", "hospital.name", "text"),
    (r"hospital\s*address|facility\s*address", "hospital.address", "text"),
    (r"(?:hospital|facility|clinic)\s*(?:phone|tel)|\bphone\b|\btel\b|contact\s*number",
     "hospital.phone", "text"),
    (r"(?:hospital|facility)\s*(?:registration|licen[cs]e)\s*(?:no|number)", "hospital.license_number", "id"),
    (r"(?:consultant|treating\s*physician|doctor|attending)\s*(?:name)?", "doctor.name", "name"),
    (r"(?:registration|reg|licence|license|mci)\s*(?:no|number)?", "doctor.registration_number", "id"),
    (r"speciali[sz]ation|speciality|department", "doctor.specialization", "text"),
    (r"designation|qualification", "doctor.designation", "text"),
    (r"diagnosis|final\s*diagnosis|provisional\s*diagnosis", "treatment.diagnosis", "text"),
    # Anchored: a diagnosis such as "Acute appendicitis (ICD-10 K35.80)" must not
    # be mistaken for an ICD label.
    (r"^icd(?:\s*-\s*10)?\s*(?:code)?\b", "treatment.icd_code", "id"),
    (r"procedure|procedure\s*performed|surgical\s*procedure", "treatment.procedure", "text"),
    (r"treatment", "treatment.treatment", "text"),
    (r"admission\s*date|date\s*of\s*admission|admitted\s*on|\badmission\b", "treatment.admission_date", "date"),
    (r"discharge\s*date|date\s*of\s*discharge|discharged\s*on|\bdischarge\b", "treatment.discharge_date", "date"),
    (r"invoice\s*(?:no|number)|bill\s*(?:no|number)|receipt\s*(?:no|number)", "billing.invoice_number", "id"),
    (r"invoice\s*date|bill\s*date|date\s*of\s*invoice", "billing.invoice_date", "date"),
    # ``(?<!sub)`` keeps "Subtotal" from being mistaken for the payable total.
    (r"grand\s*total|net\s*payable|total\s*amount|amount\s*payable|(?<!sub)\btotal\b", "billing.total_amount", "amount"),
    (r"currency", "billing.currency", "currency"),
]

#: A value must look like a real date before it is written to a date field, so
#: that headings such as "Advice on discharge" never become discharge dates.
_DATE_LIKE = re.compile(
    r"\d{1,4}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,4}"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b.{0,12}\d{2,4}",
    re.IGNORECASE,
)

_CURRENCY_HINTS = {
    "rs": "INR", "inr": "INR", "rupee": "INR", "rupees": "INR", "₹": "INR",
    "usd": "USD", "$": "USD", "dollar": "USD", "eur": "EUR", "€": "EUR",
    "gbp": "GBP", "£": "GBP", "aed": "AED", "dirham": "AED",
}

#: Conversions applied to the raw value read for a label.
_CONVERTERS = {
    "name": normalize.normalize_person_name,
    "text": normalize.clean_text,
    "id": normalize.normalize_identifier,
    "date": normalize.normalize_date,
    "amount": normalize.parse_amount,
    "currency": normalize.normalize_currency,
}


def extract_pdf_text(path: str) -> str:
    """Best-effort embedded-text extraction. Returns "" for scanned PDFs."""
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - optional dependency
        logger.warning("pypdf is not installed; offline text extraction disabled")
        return ""
    try:
        reader = PdfReader(path)
    except Exception as exc:
        logger.warning("Could not open %s: %s", path, exc)
        return ""
    chunks: List[str] = []
    try:
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
    except Exception as exc:
        logger.warning("Could not read text of %s: %s", path, exc)
    return "\n".join(chunks)


def _label_value_pairs(text: str) -> List[Tuple[str, str, str, str]]:
    """Every ``(label, value, path, kind)`` field found in the text.

    Handles three layouts: ``Label: value``, ``Label  value`` (same line), and
    the label-then-value form used by table cells, where the label sits on one
    line and its value on the next.
    """
    lines = [raw.strip() for raw in text.splitlines()]
    pairs: List[Tuple[str, str, str, str]] = []
    for index, line in enumerate(lines):
        if not line or len(line) > 220:
            continue
        label, value, value_index = "", "", index
        if ":" in line:
            head, _, tail = line.partition(":")
            if head.strip() and tail.strip():
                label, value = head.strip(), tail.strip()
        if not label:
            match = re.match(r"^([A-Za-z][A-Za-z0-9 .()/&_-]{2,40}?)\s{2,}(\S.*)$", line)
            if match:
                label, value = match.group(1).strip(), match.group(2).strip()
        if not label and _match_label(line)[0]:
            following_index = index + 1
            following = lines[following_index] if following_index < len(lines) else ""
            if following and len(following) <= 220 and not _match_label(following)[0]:
                label, value, value_index = line, following, following_index
        if not label:
            continue

        path, kind = _match_label(label)
        if not path:
            continue
        value = _drop_trailing_fields(_join_wrapped(lines, value_index, value, kind))
        pairs.append((label, value, path, kind))
    return pairs


#: Letterheads pack several fields onto one line: "Phone: +91 80 1234  |  Email: a@b.c".
_FIELD_SEPARATOR = re.compile(r"\s*[|•·]\s*(?=[A-Za-z][A-Za-z .()/&_-]{1,30}\s*:)")


def _drop_trailing_fields(value: str) -> str:
    """Keep only the first field when a line packs several ``Label: value`` pairs."""
    return _FIELD_SEPARATOR.split(value, maxsplit=1)[0].strip()


#: Prose fields are re-joined across line breaks only up to this length.
_MAX_JOINED = 400

#: If a value still ends mid-sentence this far past the cap, stop joining.
_SENTENCE_END = (".", ",", ";", ":", ")", "%")


def _join_wrapped(lines: List[str], value_index: int, value: str, kind: str) -> str:
    """Re-join prose that a line break split across two text lines.

    PDF text extraction hard-wraps paragraphs, so a value such as the treatment
    description arrives as two lines. Only prose fields are joined, and only
    while the value looks unfinished, so a following label is never swallowed.
    """
    if kind != "text":
        return value
    cursor = value_index + 1
    while (
        len(value) < _MAX_JOINED
        and not value.rstrip().endswith(_SENTENCE_END)
        and cursor < len(lines)
    ):
        following = lines[cursor].strip()
        cursor += 1
        if not following or _match_label(following)[0] or len(following) > 220:
            break
        value = f"{value.rstrip()} {following}"
    return value.strip()


def _match_label(label: str) -> Tuple[str, str]:
    lowered = label.lower().strip(" .:-")
    for pattern, path, kind in _LABEL_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return path, kind
    return "", ""


#: Table header cells - hitting one means the buffer before it is table chrome.
_HEADER_CELLS = {
    "#", "sl", "sl no", "sl. no", "sr no", "s no", "description", "particulars",
    "category", "head", "qty", "quantity", "unit", "unit price", "rate",
    "amount", "total", "charges", "items", "break up", "breakup", "summary",
}

_QTY_CELL = re.compile(r"^\d{1,4}$")
_MONEY_CELL = re.compile(r"^(?:[A-Za-z]{2,3}\s*)?-?\s*[\d,]+(?:\.\d{1,2})?$")


def _is_money_cell(cell: str) -> bool:
    """A cell holding a monetary amount such as ``25,000.00`` or ``INR 1,000``."""
    return bool(_MONEY_CELL.match(cell)) and any(ch.isdigit() for ch in cell)


def _is_header_cell(cell: str) -> bool:
    """True for table headings, ignoring units such as ``Unit Price (INR)``."""
    key = re.sub(r"\s*\(.*?\)", " ", cell.lower())
    return re.sub(r"\s+", " ", key).strip(" .:") in _HEADER_CELLS


def _parse_line_items(text: str) -> List[LineItem]:
    """Read an itemised invoice table out of the PDF text layer.

    Table cells arrive one per line (row number, description - possibly wrapped
    over several lines - category, quantity, unit price, amount), so a row is
    located by its trailing ``quantity / unit price / amount`` triple and the
    description is read from the cells buffered in front of it.
    """
    lines = [raw.strip() for raw in text.splitlines()]
    items: List[LineItem] = []
    buffer: List[str] = []
    index = 0
    while index < len(lines):
        cell = lines[index]
        qty_cell, unit_cell, amount_cell = (
            cell,
            lines[index + 1] if index + 1 < len(lines) else "",
            lines[index + 2] if index + 2 < len(lines) else "",
        )
        if (
            _QTY_CELL.match(qty_cell)
            and _is_money_cell(unit_cell)
            and _is_money_cell(amount_cell)
        ):
            amount = normalize.parse_amount(amount_cell)
            if amount > 0 and buffer:
                cells = list(buffer)
                category = cells[-1] if len(cells) > 1 else ""
                description = " ".join(cells[:-1]) if len(cells) > 1 else cells[0]
                # Wrapped descriptions can start with the row number.
                description = re.sub(r"^\d{1,3}\s+(?=[A-Za-z])", "", description).strip()
                if len(description) >= 3:
                    items.append(
                        LineItem(
                            description=description,
                            category=category if category.lower() != description.lower() else "",
                            quantity=normalize.parse_amount(qty_cell),
                            unit_price=normalize.parse_amount(unit_cell),
                            amount=amount,
                        )
                    )
            buffer = []
            index += 3
            continue
        if not cell:
            index += 1
            continue
        if _is_header_cell(cell):
            # The header marks the end of any page furniture above the table.
            buffer = []
            index += 1
            continue
        buffer.append(cell)
        index += 1
    return items


def _detect_currency(text: str) -> str:
    for token, code in _CURRENCY_HINTS.items():
        if re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", text, flags=re.IGNORECASE):
            return code
    return ""


#: Document-type fingerprints. A filename hit is worth more than a body hit,
#: because these documents all mention insurance/member ids in passing.
_KIND_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("discharge summary", ("discharge summary", "condition on discharge", "discharge date")),
    ("hospital invoice / medical bill", ("invoice", "medical bill", "bill no", "amount payable", "total due")),
    ("policy document", ("policy schedule", "policy document", "sum insured", "coverage", "policy no")),
    ("prescription", ("prescription", "rx")),
    ("lab report", ("lab report", "haemoglobin", "test result", "pathology")),
    ("insurance claim form", ("claim form", "claim no", "insured person")),
    ("insurance card / health card", ("insurance card", "health card", "member id", "policy no")),
]


def _detect_kind(filename: str, text: str) -> str:
    """Best-effort document type from filename and text fingerprints.

    Scoring rather than first-match matters here: a discharge summary and a
    policy schedule both contain "member id" and "policy no", so whichever rule
    happens to be listed first would win for every insurance document.
    """
    name = filename.lower()
    body = text.lower()
    best_label, best_score = "document", 0
    for label, keywords in _KIND_RULES:
        score = 0
        for keyword in keywords:
            if keyword in name:
                score += 3
            elif keyword in body:
                score += 1
        if score > best_score:
            best_label, best_score = label, score
    return best_label


def read_documents_offline(
    documents: Sequence[DocumentMeta],
) -> Tuple[DocumentUnderstanding, Dict[str, str]]:
    """Heuristic, label-based read of the documents' text layers."""
    result = DocumentUnderstanding()
    payload = result.model_dump()
    detected: Dict[str, str] = {}
    line_items: List[LineItem] = []

    for document in documents:
        if not document.mime_type.startswith("application/pdf"):
            detected[document.filename] = "image (not read in offline mode)"
            continue
        text = extract_pdf_text(document.stored_path)
        if not text.strip():
            detected[document.filename] = "PDF without readable text (likely scanned)"
            continue

        detected[document.filename] = _detect_kind(document.filename, text)
        seen_paths: set[str] = set()

        for label, value, path, kind in _label_value_pairs(text):
            converted = _CONVERTERS[kind](value)
            if normalize.is_blank(converted):
                continue
            if kind == "date" and not _DATE_LIKE.search(value):
                # Headings and prose can reach here ("Advice on discharge");
                # refuse to store them as a date.
                continue
            # ``_match_label`` yields nested ClaimData paths (e.g. "treatment.diagnosis")
            # while ``payload`` is the flat DocumentUnderstanding dump, so translate.
            attr = _attr_for(path)
            if normalize.is_blank(normalize.get_path(payload, attr)):
                normalize.set_path(payload, attr, converted)
                seen_paths.add(path)
            elif not normalize.similar(str(normalize.get_path(payload, attr)), str(converted)):
                # Same label, different value across documents: keep the first
                # and let the validation agent flag the conflict.
                result.low_confidence_fields.append(path)

        if not line_items:
            items = _parse_line_items(text)
            if items:
                line_items = items
                if normalize.is_blank(payload.get("total_amount")):
                    payload["total_amount"] = round(
                        sum(item.amount for item in items), 2
                    )

        if normalize.is_blank(payload.get("currency")):
            currency = _detect_currency(text)
            if currency:
                payload["currency"] = currency
                seen_paths.add("billing.currency")

        if not any(entry.startswith(f"{document.filename}:") for entry in result.documents_seen):
            result.documents_seen.append(f"{document.filename}: {detected[document.filename]}")

    # `payload` is a snapshot taken before the loop, so it still holds the
    # original empty lists. Copying those keys back would silently discard what
    # the loop collected, so only the scalar fields are restored here.
    for key, value in payload.items():
        if key in ("line_items", "documents_seen", "missing_fields", "uncertain_fields"):
            continue
        setattr(result, key, value)

    result.line_items = line_items

    result.total_amount = float(payload.get("total_amount") or 0.0)
    result.missing_fields = sorted(
        {
            path
            for path in (
                "patient.name", "patient.date_of_birth", "patient.gender", "patient.phone",
                "patient.address", "insurance.provider", "insurance.policy_number",
                "insurance.member_id", "hospital.name", "hospital.address", "hospital.phone",
                "doctor.name", "doctor.registration_number", "doctor.specialization",
                "treatment.diagnosis", "treatment.admission_date", "treatment.discharge_date",
                "billing.total_amount", "billing.currency",
            )
            if normalize.is_blank(getattr(result, _attr_for(path), ""))
        }
    )
    return result, detected


_ATTR_BY_PATH = {
    "patient.name": "patient_name",
    "patient.date_of_birth": "patient_date_of_birth",
    "patient.gender": "patient_gender",
    "patient.phone": "patient_phone",
    "patient.address": "patient_address",
    "patient.patient_id": "patient_id",
    "insurance.provider": "insurance_provider",
    "insurance.policy_number": "insurance_policy_number",
    "insurance.member_id": "insurance_member_id",
    "insurance.group_number": "insurance_group_number",
    "insurance.claim_number": "insurance_claim_number",
    "insurance.policy_holder": "insurance_policy_holder",
    "hospital.name": "hospital_name",
    "hospital.address": "hospital_address",
    "hospital.phone": "hospital_phone",
    "hospital.license_number": "hospital_license_number",
    "doctor.name": "doctor_name",
    "doctor.registration_number": "doctor_registration_number",
    "doctor.specialization": "doctor_specialization",
    "doctor.designation": "doctor_designation",
    "treatment.diagnosis": "diagnosis",
    "treatment.icd_code": "icd_code",
    "treatment.treatment": "treatment",
    "treatment.procedure": "procedure",
    "treatment.admission_date": "admission_date",
    "treatment.discharge_date": "discharge_date",
    "billing.total_amount": "total_amount",
    "billing.currency": "currency",
    "billing.invoice_number": "invoice_number",
    "billing.invoice_date": "invoice_date",
}


def _attr_for(path: str) -> str:
    """Map a nested ClaimData field path to the flat DocumentUnderstanding attr.

    Returns ``""`` for paths with no flat counterpart; callers must skip those
    rather than write an empty key.
    """
    return _ATTR_BY_PATH.get(path, "")
