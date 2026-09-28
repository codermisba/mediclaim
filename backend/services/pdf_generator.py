"""Deterministic PDF rendering.

The model never produces the PDF. Gemini produces a
:class:`~models.schemas.GeneratedClaim` JSON object, this module turns that
object into a printable, professional claim form. Same input JSON in, same page
out - which is exactly what makes an insurance document auditable.

Layout is built with ReportLab platypus primitives (no model-invented styling).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    CondPageBreak,
    Spacer,
    Table,
    TableStyle,
)

from models.schemas import ClaimData, ClaimRecord, GeneratedClaim
from services import normalize

logger = logging.getLogger("mediclaim.pdf")

# --- palette -----------------------------------------------------------------
INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
LINE = colors.HexColor("#cbd5e1")
BAND = colors.HexColor("#f1f5f9")
ACCENT = colors.HexColor("#4f46e5")
ACCENT_SOFT = colors.HexColor("#eef2ff")
ALERT = colors.HexColor("#b45309")
ALERT_SOFT = colors.HexColor("#fffbeb")
OK = colors.HexColor("#047857")

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 16 * mm
#: ``SimpleDocTemplate`` builds its own frame with 6pt of padding on every side,
#: so the width actually available to flowables is 12pt less than the page minus
#: the margins. Every table/column width must be derived from this, otherwise
#: ReportLab raises a spurious "too large on page" LayoutError.
FRAME_PADDING = 6
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN - 2 * FRAME_PADDING

DISCLAIMER = (
    "This document is an AI-generated DRAFT prepared from the information supplied by the "
    "policyholder and the documents provided with this request. It has not been reviewed, "
    "verified or approved by any insurer, and it does not constitute a decision on any claim. "
    "An authorised person must check every field against the original medical records, "
    "prescriptions and receipts before submitting it. MediClaim provides no medical, clinical "
    "or insurance advice, and does not approve, reject, assess or adjudicate claims."
)

DRAFT_BANNER = "DRAFT FOR REVIEW - NOT AN APPROVED OR AUTHORISED CLAIM"

_styles = getSampleStyleSheet()


def _style(name: str, **kwargs) -> ParagraphStyle:
    base = dict(fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=INK)
    base.update(kwargs)
    return ParagraphStyle(name, **base)


S = {
    "doc_title": _style("doc_title", fontName="Helvetica-Bold", fontSize=17, leading=20,
                        alignment=TA_CENTER, textColor=INK),
    "doc_sub": _style("doc_sub", fontSize=8.5, leading=11, alignment=TA_CENTER, textColor=MUTED),
    "banner": _style("banner", fontName="Helvetica-Bold", fontSize=8, leading=10,
                     alignment=TA_CENTER, textColor=ALERT),
    "section": _style("section", fontName="Helvetica-Bold", fontSize=9, leading=12,
                      textColor=colors.white),
    "label": _style("label", fontName="Helvetica", fontSize=6.8, leading=8.4, textColor=MUTED),
    "value": _style("value", fontName="Helvetica", fontSize=8.4, leading=10.6, textColor=INK),
    "value_bold": _style("value_bold", fontName="Helvetica-Bold", fontSize=8.4, leading=10.6,
                         textColor=INK),
    "body": _style("body", fontSize=8.4, leading=11.4, alignment=TA_JUSTIFY),
    "small": _style("small", fontSize=7.4, leading=9.4, textColor=MUTED),
    "th": _style("th", fontName="Helvetica-Bold", fontSize=7.6, leading=9.6, textColor=colors.white),
    "td": _style("td", fontSize=7.8, leading=9.8),
    "td_right": _style("td_right", fontSize=7.8, leading=9.8, alignment=TA_RIGHT),
    "total_label": _style("total_label", fontName="Helvetica-Bold", fontSize=8.6, leading=11),
    "total_value": _style("total_value", fontName="Helvetica-Bold", fontSize=9.4, leading=11.6,
                          alignment=TA_RIGHT),
    "disclaimer": _style("disclaimer", fontSize=6.6, leading=8.4, textColor=MUTED,
                         alignment=TA_JUSTIFY),
}


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def _p(text: str, style: str = "value") -> Paragraph:
    return Paragraph(_escape(text or "-"), S[style])


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _bar(text: str, style: str, background: str, pad_top: int = 0, pad_bottom: int = 0) -> List:
    """A full-width coloured bar holding a single line of text.

    Deliberately *not* a one-row ``Table``: a single-row table cannot be split
    and will not move to the next page on its own, so a heading landing near the
    page bottom makes ReportLab raise ``LayoutError``. A ``Paragraph`` moves and
    splits like any other flowable, and ``backcolor`` gives the same bar.
    """
    hex_colour = background.hexval()[2:] if isinstance(background, colors.Color) else str(background).lstrip("#")
    return [
        CondPageBreak(40),
        Spacer(1, pad_top),
        Paragraph(
            f'<font backcolor="#{hex_colour}">'
            f'{"&nbsp; " * 2}{_escape(text)}'
            f"</font>",
            S[style],
        ),
        Spacer(1, pad_bottom),
    ]


def _section(title: str) -> List:
    """A full-width coloured section heading bar."""
    return _bar(title.upper(), "section", ACCENT, pad_top=3, pad_bottom=3)


def _field_grid(pairs: List[Tuple[str, str]], columns: int = 2) -> Table:
    """A label/value grid with wrapped cells and hairline separators.

    Each cell holds a *list of flowables* rather than a nested one-row table:
    a nested table cannot be split across a page boundary, which makes
    ReportLab raise a LayoutError as soon as a grid lands near the page bottom.
    """
    cells: List[List[object]] = []
    row: List[object] = []
    for label, value in pairs:
        cell: List[object] = [
            Paragraph(_escape(label), S["label"]),
            Paragraph(
                _escape(value) if normalize.clean_text(value) else
                '<font color="#94a3b8">Not provided</font>',
                S["value"],
            ),
        ]
        row.append(cell)
        if len(row) == columns:
            cells.append(row)
            row = []
    if row:
        while len(row) < columns:
            row.append("")
        cells.append(row)

    table = Table(cells, colWidths=[CONTENT_WIDTH / columns] * columns, splitByRow=1)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                ("LINEAFTER", (0, 1), (-1, -2), 0.4, colors.HexColor("#e2e8f0")),
            ]
        )
    )
    return table


def _key_values(pairs: List[Tuple[str, str]]) -> Table:
    """Full-width two-column table, used for itemised billing."""
    rows = [[Paragraph(_escape(label), S["label"]), _p(value, "value")] for label, value in pairs]
    table = Table(rows, colWidths=[CONTENT_WIDTH * 0.34, CONTENT_WIDTH * 0.66])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("BACKGROUND", (0, 0), (0, -1), BAND),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ]
        )
    )
    return table


def _totals_block(generated: GeneratedClaim) -> Table:
    currency = generated.currency
    rows: List[List[object]] = [
        [Paragraph("Itemised subtotal", S["label"]),
         Paragraph(f"{currency} {generated.sub_total:,.2f}", S["td_right"])],
    ]
    if generated.discount > 0:
        rows.append(
            [Paragraph("Discount applied", S["label"]),
             Paragraph(f"- {currency} {generated.discount:,.2f}", S["td_right"])]
        )
    rows.append(
        [Paragraph("Total amount claimed", S["total_label"]),
         Paragraph(f"{currency} {generated.total:,.2f}", S["total_value"])]
    )
    table = Table(rows, colWidths=[CONTENT_WIDTH * 0.68, CONTENT_WIDTH * 0.32])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BACKGROUND", (0, -1), (-1, -1), ACCENT_SOFT),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, ACCENT),
            ]
        )
    )
    return table


def _billing_table(generated: GeneratedClaim) -> Table:
    currency = generated.currency
    header = [
        Paragraph("#", S["th"]),
        Paragraph("Description", S["th"]),
        Paragraph("Category", S["th"]),
        Paragraph(f"Amount ({currency})", S["th"]),
    ]
    rows = [header]
    for index, item in enumerate(generated.line_items, start=1):
        rows.append(
            [
                Paragraph(str(index), S["td"]),
                Paragraph(_escape(item.description), S["td"]),
                Paragraph(_escape(item.category or "-"), S["td"]),
                Paragraph(f"{item.amount:,.2f}", S["td_right"]),
            ]
        )
    table = Table(
        rows,
        colWidths=[
            CONTENT_WIDTH * 0.06,
            CONTENT_WIDTH * 0.50,
            CONTENT_WIDTH * 0.24,
            CONTENT_WIDTH * 0.20,
        ],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("ALIGN", (3, 1), (3, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
                ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, ACCENT),
            ]
        )
    )
    return table


def _notice(text: str, tone: str = "warning") -> Table:
    background = ALERT_SOFT if tone == "warning" else ACCENT_SOFT
    border = ALERT if tone == "warning" else ACCENT
    style = _style(f"notice_{tone}", fontSize=7.6, leading=9.8, textColor=INK, alignment=TA_LEFT)
    table = Table([[Paragraph(_escape(text), style)]], colWidths=[CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.7, border),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _signature_block() -> Table:
    blank = Paragraph(" ", S["value"])
    left = [
        Paragraph("Signature of Claimant / Authorised Person", S["label"]),
        Spacer(1, 16),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#94a3b8")),
        Spacer(1, 2),
        Paragraph("Name in block letters", S["label"]),
        Spacer(1, 12),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#94a3b8")),
        Spacer(1, 2),
        Paragraph("Date", S["label"]),
    ]
    right = [
        Paragraph("For hospital / provider use only", S["label"]),
        Spacer(1, 16),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#94a3b8")),
        Spacer(1, 2),
        Paragraph("Authorised signatory and stamp", S["label"]),
        Spacer(1, 12),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#94a3b8")),
        Spacer(1, 2),
        Paragraph("Date", S["label"]),
    ]
    table = Table([[left, blank, right]], colWidths=[
        CONTENT_WIDTH * 0.46, CONTENT_WIDTH * 0.08,
        CONTENT_WIDTH * 0.46,
    ])
    table.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 6),
                    ("RIGHTPADDING", (-1, 0), (-1, 0), 6)])
    )
    return table


# ---------------------------------------------------------------------------
# Page furniture
# ---------------------------------------------------------------------------


def _page_furniture(record: ClaimRecord, generated: GeneratedClaim, total_pages: int):
    """Return the on_page callback that draws header, footer and page numbers."""

    def draw(canvas, doc) -> None:
        canvas.saveState()
        width = PAGE_WIDTH

        canvas.setFillColor(ACCENT)
        canvas.rect(0, PAGE_HEIGHT - 8 * mm, width, 8 * mm, stroke=0, fill=1)

        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(INK)
        canvas.drawString(MARGIN, PAGE_HEIGHT - 14.5 * mm, "MediClaim")
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(
            width - MARGIN,
            PAGE_HEIGHT - 14.5 * mm,
            f"Claim ref: {generated.claim_number or '-'}",
        )
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, PAGE_HEIGHT - 16.5 * mm, width - MARGIN, PAGE_HEIGHT - 16.5 * mm)

        # Footer
        canvas.line(MARGIN, 16 * mm, width - MARGIN, 16 * mm)
        canvas.setFont("Helvetica", 6.6)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            MARGIN,
            12.6 * mm,
            f"Generated {generated.generated_at[:19].replace('T', ' ')} UTC"
            f"  |  claim id {record.claim_id}",
        )
        canvas.drawRightString(
            width - MARGIN, 12.6 * mm, f"Page {doc.page} of {total_pages}"
        )
        canvas.setFont("Helvetica-Bold", 6.4)
        canvas.setFillColor(ALERT)
        canvas.drawCentredString(width / 2, 9.4 * mm, DRAFT_BANNER)
        canvas.restoreState()

    return draw


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------


def build_story(record: ClaimRecord, claim: ClaimData, generated: GeneratedClaim) -> List:
    story: List = []
    content_width = CONTENT_WIDTH

    # ---- Title -------------------------------------------------------------
    story.append(Paragraph("INSURANCE CLAIM FORM", S["doc_title"]))
    story.append(Spacer(1, 2))
    story.append(
        Paragraph(
            "DRAFT - automatically prepared from patient-supplied information and uploaded documents",
            S["doc_sub"],
        )
    )
    story.append(Spacer(1, 6))
    story.append(_notice(DRAFT_BANNER, tone="warning"))
    story.append(Spacer(1, 8))

    # ---- Claim information -------------------------------------------------
    story.extend(_section("Claim information"))
    story.append(Spacer(1, 3))
    claim_rows = [
        ("Claim reference number", generated.claim_number),
        ("Claim type", generated.claim_type),
        ("Amount claimed", f"{generated.currency} {generated.claim_amount:,.2f}"),
        ("Claim amount in words", _amount_in_words(generated.claim_amount, generated.currency)),
        ("Service / treatment period", generated.service_period),
        ("Place of treatment", generated.place_of_treatment),
        ("Claim submitted by", generated.claimed_by),
        ("Invoice / bill reference", claim.billing.invoice_number),
        ("Invoice date", normalize.human_date(claim.billing.invoice_date) if claim.billing.invoice_date else ""),
        ("Date generated (UTC)", normalize.human_date(generated.generated_at, "%d %b %Y %H:%M")),
    ]
    story.append(_key_values(claim_rows))
    story.append(Spacer(1, 9))

    # ---- Patient -----------------------------------------------------------
    story.extend(_section("Patient information"))
    story.append(Spacer(1, 3))
    story.append(
        _field_grid(
            [
                ("Full name", claim.patient.name),
                ("Date of birth", normalize.human_date(claim.patient.date_of_birth)),
                ("Gender", claim.patient.gender),
                ("Contact number", claim.patient.phone),
                ("Email", claim.patient.email),
                ("Hospital record / patient ID", claim.patient.patient_id),
                ("Address", claim.patient.address),
            ]
        )
    )
    story.append(Spacer(1, 9))

    # ---- Insurance ---------------------------------------------------------
    story.extend(_section("Insurance details"))
    story.append(Spacer(1, 3))
    story.append(
        _field_grid(
            [
                ("Insurance provider", claim.insurance.provider),
                ("Policy number", claim.insurance.policy_number),
                ("Member ID", claim.insurance.member_id),
                ("Group number", claim.insurance.group_number),
                ("Policy holder", claim.insurance.policy_holder),
                ("Insurer claim reference", claim.insurance.claim_number),
                ("Policy period",
                 _policy_period(claim.insurance.policy_start_date, claim.insurance.policy_end_date)),
            ]
        )
    )
    story.append(Spacer(1, 9))

    # ---- Hospital ----------------------------------------------------------
    story.extend(_section("Hospital / provider information"))
    story.append(Spacer(1, 3))
    story.append(
        _field_grid(
            [
                ("Hospital / clinic name", claim.hospital.name),
                ("Facility type", claim.hospital.facility_type),
                ("Contact number", claim.hospital.phone),
                ("Registration / licence number", claim.hospital.license_number),
                ("Address", claim.hospital.address),
            ]
        )
    )
    story.append(Spacer(1, 9))

    # ---- Doctor ------------------------------------------------------------
    story.extend(_section("Treating doctor"))
    story.append(Spacer(1, 3))
    story.append(
        _field_grid(
            [
                ("Doctor name", claim.doctor.name),
                ("Registration number", claim.doctor.registration_number),
                ("Specialization", claim.doctor.specialization),
                ("Designation", claim.doctor.designation),
                ("Contact number", claim.doctor.phone),
            ]
        )
    )
    story.append(Spacer(1, 9))

    # ---- Medical -----------------------------------------------------------
    story.extend(_section("Medical information"))
    story.append(Spacer(1, 3))
    story.append(
        _field_grid(
            [
                ("Admission date", normalize.human_date(claim.treatment.admission_date)),
                ("Discharge date", normalize.human_date(claim.treatment.discharge_date)),
                ("Treatment type", claim.treatment.treatment_type),
                ("ICD code", claim.treatment.icd_code),
            ]
        )
    )
    story.append(Spacer(1, 3))
    story.append(
        _key_values(
            [
                ("Diagnosis", claim.treatment.diagnosis),
                ("Treatment", claim.treatment.treatment),
                ("Procedure performed", claim.treatment.procedure),
                ("Clinical notes", claim.treatment.clinical_notes),
            ]
        )
    )
    story.append(Spacer(1, 9))

    # ---- Narrative ---------------------------------------------------------
    if generated.narrative:
        story.extend(_section("Claim narrative"))
        story.append(Spacer(1, 4))
        story.append(Paragraph(_escape(generated.narrative), S["body"]))
        story.append(Spacer(1, 9))

    # ---- Billing -----------------------------------------------------------
    story.extend(_section("Billing details"))
    story.append(Spacer(1, 4))
    if generated.line_items:
        story.append(_billing_table(generated))
        story.append(Spacer(1, 4))
        story.append(_totals_block(generated))
    else:
        story.append(
            _key_values(
                [
                    ("Total amount claimed", f"{generated.currency} {generated.claim_amount:,.2f}"),
                    ("Amount in words", _amount_in_words(generated.claim_amount, generated.currency)),
                    ("Itemised breakdown", "Not available in the source documents"),
                ]
            )
        )
    story.append(Spacer(1, 5))
    story.append(
        _key_values(
            [
                ("Discount", f"{generated.currency} {generated.discount:,.2f}" if generated.discount else "None"),
                ("Amount already paid by patient",
                 f"{generated.currency} {claim.billing.paid_amount:,.2f}" if claim.billing.paid_amount else "Not stated"),
            ]
        )
    )
    story.append(Spacer(1, 9))

    # ---- Source documents --------------------------------------------------
    documents = [document.filename for document in record.documents]
    if documents:
        story.extend(_section("Source documents used"))
        story.append(Spacer(1, 4))
        story.append(
            _key_values(
                [(f"Document {index}", name) for index, name in enumerate(documents, start=1)]
                + [("Total documents supplied", str(len(documents)))]
            )
        )
        story.append(Spacer(1, 9))

    # ---- Verification notes ------------------------------------------------
    notes = _verification_notes(record)
    if notes:
        story.extend(_section("Items to verify before submission"))
        story.append(Spacer(1, 4))
        for note in notes:
            story.append(_notice(note, tone="info"))
            story.append(Spacer(1, 3))
        story.append(Spacer(1, 6))

    # ---- Signature ---------------------------------------------------------
    story.extend(_section("Declaration and signature"))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "I declare that the information given in this form is true and correct to the best "
            "of my knowledge and belief, and that the documents listed above are genuine. I "
            "understand that this form is a draft prepared with AI assistance and must be "
            "independently verified before it is submitted to the insurer.",
            S["body"],
        )
    )
    story.append(Spacer(1, 6))
    story.append(_signature_block())
    story.append(Spacer(1, 10))

    # ---- Disclaimer --------------------------------------------------------
    story.append(HRFlowable(width="100%", thickness=0.6, color=LINE))
    story.append(Spacer(1, 4))
    story.append(Paragraph(_escape(DISCLAIMER), S["disclaimer"]))
    return story


def _policy_period(start: str, end: str) -> str:
    if start and end:
        return f"{normalize.human_date(start)} to {normalize.human_date(end)}"
    if start:
        return f"From {normalize.human_date(start)}"
    if end:
        return f"Until {normalize.human_date(end)}"
    return ""


_ONES = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
         "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
         "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
_SCALES = [(1_000_000_000, "Billion"), (1_000_000, "Million"), (1_000, "Thousand"), (1, "")]


def _three_digits(value: int) -> str:
    words = ""
    if value >= 100:
        words += _ONES[value // 100] + " Hundred"
        value %= 100
        if value:
            words += " "
    if value >= 20:
        words += _TENS[value // 10]
        if value % 10:
            words += " " + _ONES[value % 10]
    elif value:
        words += _ONES[value]
    return words


def _amount_in_words(amount: float, currency: str) -> str:
    """Amount in words, for the 'total payable' field of a claim form."""
    if amount <= 0:
        return "-"
    whole = int(amount)
    paise = int(round((amount - whole) * 100))
    if whole == 0:
        text = f"Zero {currency}"
    else:
        parts = []
        for scale, name in _SCALES:
            if whole >= scale:
                parts.append(f"{_three_digits(whole // scale)} {name}".strip())
                whole %= scale
        text = " ".join(parts) + f" {currency}".rstrip()
    if paise:
        text += f" and {_two_digits(paise)} {'Paisa' if currency == 'INR' else 'Cents'}"
    return text.strip() + " only"


def _two_digits(value: int) -> str:
    if value < 20:
        return _ONES[value]
    return _TENS[value // 10] + (" " + _ONES[value % 10] if value % 10 else "")


def _verification_notes(record: ClaimRecord) -> List[str]:
    """Short, actionable reminders printed on the draft."""
    notes: List[str] = []
    if record.validation:
        for path in record.validation.missing_required[:6]:
            from models.schemas import OPTIONAL_CLAIM_FIELDS, REQUIRED_CLAIM_FIELDS

            label = {**REQUIRED_CLAIM_FIELDS, **OPTIONAL_CLAIM_FIELDS}.get(
                path, path.replace(".", " ")
            )
            notes.append(f"Required field not provided: {label}.")
        for issue in [i for i in record.validation.inconsistencies if i.severity == "error"][:4]:
            notes.append(issue.message)
        for issue in record.validation.warnings[:4]:
            notes.append(issue.message)
    if record.review:
        for issue in record.review.issues[:5]:
            notes.append(issue.message)
    seen = set()
    unique = []
    for note in notes:
        if note and note not in seen:
            seen.add(note)
            unique.append(note)
    return unique[:12]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


class _ClaimDocTemplate(SimpleDocTemplate):
    """SimpleDocTemplate that remembers how many pages the last build used."""

    last_page_count: int = 0


def _new_document(path: Path) -> _ClaimDocTemplate:
    return _ClaimDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title="Insurance Claim Form",
        author="MediClaim - ClaimGen AI",
        subject="DRAFT insurance claim form generated with AI assistance",
    )


def build_claim_pdf(record: ClaimRecord, output_dir: Path) -> str:
    """Render the claim form for ``record`` and return the written filename.

    Built twice: the first pass counts pages so "Page X of Y" is correct on
    every page, the second pass writes the real file. Each pass gets a
    **freshly built** story - ReportLab mutates flowables as it lays them out
    (row heights, split state, ``_postponed`` flags), so reusing the same
    objects for a second build makes it fail with a bogus ``LayoutError``.
    """
    if record.claim_data is None or record.generated is None:
        raise ValueError("A claim needs validated data and a generated claim before a PDF exists.")

    claim: ClaimData = record.claim_data
    generated: GeneratedClaim = record.generated
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"claim_{generated.claim_number or record.claim_id}.pdf".replace("/", "-")
    path = output_dir / filename

    # Pass 1 - into memory, purely to learn the page count.
    probe = _new_document(Path(str(path)))
    probe.build(
        build_story(record, claim, generated),
        onFirstPage=lambda c, d: None,
        onLaterPages=lambda c, d: None,
    )
    total_pages = probe.page

    # Pass 2 - the real file, with correct page numbering.
    document = _new_document(path)
    furniture = _page_furniture(record, generated, total_pages)
    document.build(
        build_story(record, claim, generated),
        onFirstPage=furniture,
        onLaterPages=furniture,
    )
    logger.info("PDF written to %s (%s pages)", path, total_pages)
    return filename
