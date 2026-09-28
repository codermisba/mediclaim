"""Sample / demo data.

Generates a complete, internally consistent set of sample documents so the
application can be demonstrated end to end the moment it starts:

* ``medical-bill.pdf``          - hospital invoice with itemised charges
* ``discharge-summary.pdf``     - clinical record with diagnosis and dates
* ``insurance-policy.pdf``      - policy and membership details
* ``insurance-card.png``        - insurance card image (Gemini-only, no text layer)

The PDFs are produced with ReportLab and therefore carry a real text layer, so
the deterministic offline reader can use them too. The PNG genuinely requires
Gemini - that is intentional, it demonstrates the multimodal path.

The same figures appear in ``SAMPLE_INPUT`` so a user can start from the
"patient + hospital typed by hand" flow described in the project brief.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from config import SAMPLE_DIR
from models.schemas import SampleData, SampleDocument, UserInput

logger = logging.getLogger("mediclaim.sample")

# ---------------------------------------------------------------------------
# The one consistent truth for the sample claim
# ---------------------------------------------------------------------------

SAMPLE_PATIENT = {
    "name": "Aarav Sharma",
    "date_of_birth": "12/04/1987",
    "gender": "Male",
    "phone": "+91 98765 43210",
    "email": "aarav.sharma@example.com",
    "address": "42 Rosewood Apartments, Indiranagar, Bengaluru 560001",
}

SAMPLE_INSURANCE = {
    "provider": "HealthFirst Insurance Ltd",
    "policy_number": "HF-2024-88123",
    "member_id": "HF-M-449201",
    "group_number": "GRP-77",
    "policy_holder": "Aarav Sharma",
    "plan": "Individual Health Cover - Gold",
    "sum_insured": "500000",
    "valid_from": "01/01/2026",
    "valid_to": "31/12/2026",
}

SAMPLE_HOSPITAL = {
    "name": "CityCare Multispecialty Hospital",
    "address": "18 MG Road, Bengaluru 560001, Karnataka, India",
    "phone": "+91 80 4123 8899",
    "email": "billing@citycare.example",
    "license": "KCA-HOS-2011-4471",
}

SAMPLE_DOCTOR = {
    "name": "Dr. Meera Raghavan",
    "registration": "KMC-77241",
    "qualification": "MBBS, MS (General Surgery)",
    "designation": "Consultant General Surgeon",
    "department": "General Surgery",
}

SAMPLE_TREATMENT = {
    "diagnosis": "Acute appendicitis",
    "icd": "K35.80",
    "procedure": "Appendectomy (emergency)",
    "treatment": (
        "Emergency appendectomy with intravenous antibiotics, "
        "inpatient hospitalisation and post-operative recovery"
    ),
    "admission": "11/03/2026",
    "discharge": "14/03/2026",
    "chief_complaint": "Severe right lower quadrant abdominal pain since 2 days",
    "discharge_status": "Recovered",
}

# description, category, quantity, unit price
SAMPLE_LINE_ITEMS = [
    ("Emergency appendectomy - surgical procedure", "Surgery", 1.0, 25000.00),
    ("Private room - 3 nights", "Room charges", 3.0, 4000.00),
    ("CT abdomen with contrast, USG abdomen, CBC, electrolytes", "Diagnostics", 1.0, 4250.00),
    ("Inj. Ceftriaxone 1g IV, Inj. Metronidazole, Paracetamol, IV fluids", "Pharmacy", 1.0, 3500.00),
    ("Surgical consumables, sutures, surgical gloves", "Consumables", 1.0, 3000.00),
    ("Miscellaneous hospital charges", "Other", 1.0, 1000.00),
]

SAMPLE_BILLING = {
    "subtotal": 46400.00,
    "discount": 500.00,
    "tax": 2850.00,
    "total": 48750.00,
    "currency": "INR",
    "invoice_number": "INV-2026-33918",
    "invoice_date": "14/03/2026",
    "payment_mode": "Insurance (cashless settlement pending)",
}

SAMPLE_CLAIM_TITLE = "Sample claim - Aarav Sharma"

#: The typed half of the demo: exactly what the brief says the user enters.
SAMPLE_INPUT = UserInput(
    patient={
        "name": SAMPLE_PATIENT["name"],
        "date_of_birth": SAMPLE_PATIENT["date_of_birth"],
        "gender": SAMPLE_PATIENT["gender"],
        "phone": SAMPLE_PATIENT["phone"],
        "address": SAMPLE_PATIENT["address"],
    },
    insurance={},
    hospital={
        "name": SAMPLE_HOSPITAL["name"],
        "address": SAMPLE_HOSPITAL["address"],
        "phone": SAMPLE_HOSPITAL["phone"],
    },
    doctor={},
    treatment={},
    billing={},
    notes=(
        "I was admitted as an emergency for appendicitis and had surgery at "
        f"{SAMPLE_HOSPITAL['name']}. I have attached the hospital bill, the "
        "discharge summary, my insurance policy and a photo of my insurance card. "
        "My HealthFirst Gold policy should cover this."
    ),
)

#: What the user types in the doctor/treatment boxes, for the "full form" sample.
SAMPLE_INPUT_FULL = UserInput(
    patient={
        "name": SAMPLE_PATIENT["name"],
        "date_of_birth": SAMPLE_PATIENT["date_of_birth"],
        "gender": SAMPLE_PATIENT["gender"],
        "phone": SAMPLE_PATIENT["phone"],
        "email": SAMPLE_PATIENT["email"],
        "address": SAMPLE_PATIENT["address"],
    },
    insurance={
        "provider": SAMPLE_INSURANCE["provider"],
        "policy_number": SAMPLE_INSURANCE["policy_number"],
        "member_id": SAMPLE_INSURANCE["member_id"],
        "group_number": SAMPLE_INSURANCE["group_number"],
        "policy_holder": SAMPLE_INSURANCE["policy_holder"],
    },
    hospital={
        "name": SAMPLE_HOSPITAL["name"],
        "address": SAMPLE_HOSPITAL["address"],
        "phone": SAMPLE_HOSPITAL["phone"],
    },
    doctor={
        "name": SAMPLE_DOCTOR["name"],
        "registration_number": SAMPLE_DOCTOR["registration"],
        "specialization": SAMPLE_DOCTOR["department"],
    },
    treatment={
        "diagnosis": SAMPLE_TREATMENT["diagnosis"],
        "admission_date": SAMPLE_TREATMENT["admission"],
        "discharge_date": SAMPLE_TREATMENT["discharge"],
        "treatment": SAMPLE_TREATMENT["treatment"],
    },
    billing={
        "total_amount": f"{SAMPLE_BILLING['total']:.2f}",
        "currency": SAMPLE_BILLING["currency"],
        "invoice_number": SAMPLE_BILLING["invoice_number"],
    },
    notes=SAMPLE_INPUT.notes,
)

DESCRIPTIONS = {
    "medical-bill.pdf": "Final hospital invoice with itemised charges and the total.",
    "discharge-summary.pdf": "Discharge summary with diagnosis, procedure and stay dates.",
    "insurance-policy.pdf": "Insurance policy schedule with policy and member numbers.",
    "insurance-card.png": "Photograph of the physical insurance membership card.",
}


# ---------------------------------------------------------------------------
# PDF builders
# ---------------------------------------------------------------------------


def _build_medical_bill(path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        title="Hospital Invoice",
    )

    story: List = [
        Paragraph("CityCare Multispecialty Hospital", styles["Title"]),
        Paragraph("18 MG Road, Bengaluru 560001, Karnataka, India", styles["Normal"]),
        Paragraph("Phone: +91 80 4123 8899 &nbsp;|&nbsp; Email: billing@citycare.example", styles["Normal"]),
        Paragraph(f"Facility Licence No: {SAMPLE_HOSPITAL['license']}", styles["Normal"]),
        Spacer(1, 8 * mm),
        Paragraph("FINAL INVOICE", styles["Heading1"]),
    ]

    header = [
        ["Invoice Number", SAMPLE_BILLING["invoice_number"], "Invoice Date", SAMPLE_BILLING["invoice_date"]],
        ["Patient Name", SAMPLE_PATIENT["name"], "Patient ID", "CC-88213"],
        ["Date of Birth", SAMPLE_PATIENT["date_of_birth"], "Gender", SAMPLE_PATIENT["gender"]],
        ["Contact", SAMPLE_PATIENT["phone"], "Admission", SAMPLE_TREATMENT["admission"]],
        ["Discharge", SAMPLE_TREATMENT["discharge"], "Department", SAMPLE_DOCTOR["department"]],
        [
            "Consultant",
            f"{SAMPLE_DOCTOR['name']} ({SAMPLE_DOCTOR['qualification']})",
            "Reg. No",
            SAMPLE_DOCTOR["registration"],
        ],
        [
            "Insurance",
            SAMPLE_INSURANCE["provider"],
            "Policy / Member",
            f"{SAMPLE_INSURANCE['policy_number']} / {SAMPLE_INSURANCE['member_id']}",
        ],
    ]
    header_table = Table(header, colWidths=[30 * mm, 55 * mm, 30 * mm, 50 * mm])
    header_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f1f5f9")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story += [header_table, Spacer(1, 8 * mm), Paragraph("Diagnosis and treatment", styles["Heading2"])]
    story.append(
        Paragraph(
            f"Diagnosis: {SAMPLE_TREATMENT['diagnosis']} (ICD-10 {SAMPLE_TREATMENT['icd']}).<br/>"
            f"Procedure: {SAMPLE_TREATMENT['procedure']}.<br/>"
            f"Treatment: {SAMPLE_TREATMENT['treatment']}.",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Charges", styles["Heading2"]))

    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8)
    rows = [["#", "Description", "Category", "Qty", "Unit Price (INR)", "Amount (INR)"]]
    for index, (description, category, quantity, unit) in enumerate(SAMPLE_LINE_ITEMS, start=1):
        rows.append(
            [
                str(index),
                Paragraph(description, small),
                category,
                f"{quantity:g}",
                f"{unit:,.2f}",
                f"{quantity * unit:,.2f}",
            ]
        )
    charges = Table(
        rows,
        colWidths=[8 * mm, 78 * mm, 24 * mm, 12 * mm, 26 * mm, 27 * mm],
        repeatRows=1,
    )
    charges.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(charges)
    story.append(Spacer(1, 6 * mm))

    totals = [
        ["Subtotal", f"INR {SAMPLE_BILLING['subtotal']:,.2f}"],
        ["Discount", f"- INR {SAMPLE_BILLING['discount']:,.2f}"],
        ["Tax (GST 5%)", f"INR {SAMPLE_BILLING['tax']:,.2f}"],
        ["GRAND TOTAL", f"INR {SAMPLE_BILLING['total']:,.2f}"],
    ]
    totals_table = Table(totals, colWidths=[45 * mm, 45 * mm], hAlign="RIGHT")
    totals_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
                ("FONTSIZE", (0, 3), (-1, 3), 11),
                ("LINEABOVE", (0, 3), (-1, 3), 0.8, colors.HexColor("#0f172a")),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(totals_table)
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            f"Payment Mode: {SAMPLE_BILLING['payment_mode']}<br/>"
            "This is a computer generated invoice and does not require a signature.",
            styles["Normal"],
        )
    )
    doc.build(story)


def _build_discharge_summary(path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        title="Discharge Summary",
    )
    story: List = [
        Paragraph("CityCare Multispecialty Hospital", styles["Title"]),
        Paragraph("Discharge Summary", styles["Heading1"]),
        Spacer(1, 4 * mm),
    ]
    rows = [
        ["Patient Name", SAMPLE_PATIENT["name"]],
        ["Age / Gender", "38 years / Male"],
        ["Date of Birth", SAMPLE_PATIENT["date_of_birth"]],
        ["IP / Patient No.", "CC-88213"],
        ["Contact", SAMPLE_PATIENT["phone"]],
        ["Address", SAMPLE_PATIENT["address"]],
        ["Admission Date", SAMPLE_TREATMENT["admission"]],
        ["Discharge Date", SAMPLE_TREATMENT["discharge"]],
        ["Consulting Doctor", f"{SAMPLE_DOCTOR['name']}"],
        ["Doctor Qualification", SAMPLE_DOCTOR["qualification"]],
        ["Medical Registration No", SAMPLE_DOCTOR["registration"]],
        ["Department", SAMPLE_DOCTOR["department"]],
        ["Diagnosis", f"{SAMPLE_TREATMENT['diagnosis']} (ICD-10 {SAMPLE_TREATMENT['icd']})"],
        ["Presenting Complaint", SAMPLE_TREATMENT["chief_complaint"]],
        ["Procedure Performed", SAMPLE_TREATMENT["procedure"]],
        ["Treatment Given", SAMPLE_TREATMENT["treatment"]],
        ["Condition at Discharge", SAMPLE_TREATMENT["discharge_status"]],
        ["Insurer", SAMPLE_INSURANCE["provider"]],
        ["Policy Number", SAMPLE_INSURANCE["policy_number"]],
        ["Member ID", SAMPLE_INSURANCE["member_id"]],
    ]
    table = Table(rows, colWidths=[45 * mm, 120 * mm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "Advice on discharge: light diet, oral antibiotics for 5 days, avoid lifting "
            "heavy weights for 4 weeks, review in outpatient clinic after 7 days. "
            "Patient and attendant briefed and understood.",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("Authorised Signature", styles["Normal"]))
    story.append(Paragraph(f"_{SAMPLE_DOCTOR['name']}_", styles["Normal"]))
    story.append(
        Paragraph(
            f"{SAMPLE_DOCTOR['qualification']} - Reg. No. {SAMPLE_DOCTOR['registration']}",
            styles["Normal"],
        )
    )
    doc.build(story)


def _build_insurance_policy(path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        title="Insurance Policy Schedule",
    )
    story: List = [
        Paragraph(SAMPLE_INSURANCE["provider"], styles["Title"]),
        Paragraph("Individual Health Insurance Policy Schedule", styles["Heading1"]),
        Spacer(1, 4 * mm),
    ]
    rows = [
        ["Policy Holder", SAMPLE_INSURANCE["policy_holder"]],
        ["Insured Person", SAMPLE_PATIENT["name"]],
        ["Date of Birth", SAMPLE_PATIENT["date_of_birth"]],
        ["Gender", SAMPLE_PATIENT["gender"]],
        ["Address", SAMPLE_PATIENT["address"]],
        ["Policy Number", SAMPLE_INSURANCE["policy_number"]],
        ["Member ID", SAMPLE_INSURANCE["member_id"]],
        ["Group Number", SAMPLE_INSURANCE["group_number"]],
        ["Plan Name", SAMPLE_INSURANCE["plan"]],
        ["Sum Insured", f"INR {float(SAMPLE_INSURANCE['sum_insured']):,.2f}"],
        ["Policy Period", f"{SAMPLE_INSURANCE['valid_from']} to {SAMPLE_INSURANCE['valid_to']}"],
        ["Customer Care", "1800-123-4567"],
    ]
    table = Table(rows, colWidths=[45 * mm, 120 * mm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "This policy covers inpatient hospitalisation expenses subject to the terms, "
            "conditions, waiting periods, exclusions and pre-existing disease clauses stated "
            "in the policy document. Pre-authisation reference PA-2026-77120 is on file for the "
            "current admission. Cashless settlement is pending at the time of invoice.",
            styles["Normal"],
        )
    )
    doc.build(story)


def _build_insurance_card(path: Path) -> None:
    """A real raster image - only Gemini can read this one."""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1000, 630
    image = Image.new("RGB", (width, height), "#0b1b3a")
    draw = ImageDraw.Draw(image)

    def font(size: int, bold: bool = False):
        for name in (
            ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf") if bold else ("arial.ttf", "DejaVuSans.ttf"),
        ):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    # Header band
    draw.rectangle([0, 0, width, 96], fill="#12306b")
    draw.text((40, 24), "HealthFirst Insurance Ltd", font=font(40, True), fill="#ffffff")
    draw.text((40, 70), "INDIVIDUAL HEALTH COVER  -  MEMBERSHIP CARD", font=font(20), fill="#a9c2f0")

    # Card body
    draw.rounded_rectangle([40, 130, 960, 560], radius=18, fill="#f8fafc", outline="#3b82f6", width=3)
    label_font = font(21, True)
    value_font = font(27, True)
    rows = [
        ("POLICY HOLDER", SAMPLE_INSURANCE["policy_holder"]),
        ("INSURED PERSON", SAMPLE_PATIENT["name"]),
        ("DATE OF BIRTH", SAMPLE_PATIENT["date_of_birth"]),
        ("POLICY NUMBER", SAMPLE_INSURANCE["policy_number"]),
        ("MEMBER ID", SAMPLE_INSURANCE["member_id"]),
        ("GROUP NUMBER", SAMPLE_INSURANCE["group_number"]),
        ("PLAN", SAMPLE_INSURANCE["plan"]),
        ("SUM INSURED", "INR " + SAMPLE_INSURANCE["sum_insured"]),
        ("VALID FROM", SAMPLE_INSURANCE["valid_from"]),
        ("VALID TO", SAMPLE_INSURANCE["valid_to"]),
    ]
    y = 160
    for label, value in rows:
        draw.text((70, y), label, font=label_font, fill="#64748b")
        draw.text((360, y - 4), value, font=value_font, fill="#0f172a")
        y += 39

    draw.text((40, 585), "Customer Care 1800-123-4567   |   healthfirst.example", font=font(20), fill="#8fb0e8")
    image.save(str(path), "PNG")


_BUILDERS = {
    "medical-bill.pdf": _build_medical_bill,
    "discharge-summary.pdf": _build_discharge_summary,
    "insurance-policy.pdf": _build_insurance_policy,
    "insurance-card.png": _build_insurance_card,
}

SAMPLE_MIME = {
    "medical-bill.pdf": "application/pdf",
    "discharge-summary.pdf": "application/pdf",
    "insurance-policy.pdf": "application/pdf",
    "insurance-card.png": "image/png",
}


def ensure_sample_documents() -> Dict[str, Path]:
    """Generate the sample files once and return ``{filename: path}``."""
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    created: Dict[str, Path] = {}
    for filename, builder in _BUILDERS.items():
        path = SAMPLE_DIR / filename
        try:
            if not path.exists() or path.stat().st_size == 0:
                builder(path)
                logger.info("Generated sample document %s", filename)
            created[filename] = path
        except Exception as exc:  # noqa: BLE001 - a missing sample must not 500
            logger.error("Could not generate sample document %s: %s", filename, exc)
    return created


def sample_document_list() -> List[SampleDocument]:
    available = ensure_sample_documents()
    documents: List[SampleDocument] = []
    for filename, description in DESCRIPTIONS.items():
        path = available.get(filename)
        documents.append(
            SampleDocument(
                filename=filename,
                label=filename.replace("-", " ").replace(".pdf", "").replace(".png", "").title(),
                description=description,
                mime_type=SAMPLE_MIME.get(filename, "application/octet-stream"),
                available=bool(path and path.exists()),
            )
        )
    return documents


def get_sample_data() -> SampleData:
    """Everything the frontend needs to start a demo claim."""
    return SampleData(
        title=SAMPLE_CLAIM_TITLE,
        description=(
            "A complete worked example: an emergency appendectomy claim for Aarav "
            "Sharma. The typed form holds the patient and hospital details and the "
            "generated sample documents supply the clinical, billing and insurance "
            "information, so you can watch the agents extract it."
        ),
        input_data=SAMPLE_INPUT,
        documents=sample_document_list(),
    )


__all__ = [
    "get_sample_data",
    "sample_document_list",
    "ensure_sample_documents",
    "SAMPLE_INPUT",
    "SAMPLE_INPUT_FULL",
    "SAMPLE_CLAIM_TITLE",
    "SAMPLE_MIME",
]
