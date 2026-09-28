"""Pydantic schemas used as the contract between the API and every agent.

Design rules that apply to *all* agent output models:

* Agents never emit ``null`` for "unknown". They emit the empty value
  (``""`` / ``0.0`` / ``[]``) and add the dotted field path to ``missing_fields``.
* Every model is Gemini structured-output safe: only ``str``, ``float``,
  ``int``, ``bool``, ``List[...]`` and nested models are used. No ``Optional``,
  no unions, no free-form JSON blobs.
* ``services.gemini`` sanitises the generated JSON schema before handing it to
  the API, so ``Field`` descriptions are kept and everything exotic is dropped.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Field vocabulary
# ---------------------------------------------------------------------------

#: Dotted paths that must exist for a claim to be submittable. The validation
#: agent treats this list as the source of truth, together with its labels.
REQUIRED_CLAIM_FIELDS: Dict[str, str] = {
    "patient.name": "Patient full name",
    "patient.date_of_birth": "Patient date of birth",
    "patient.gender": "Patient gender",
    "patient.phone": "Patient phone number",
    "insurance.provider": "Insurance provider / company name",
    "insurance.policy_number": "Insurance policy number",
    "insurance.member_id": "Insurance member ID",
    "hospital.name": "Hospital / clinic name",
    "hospital.address": "Hospital address",
    "doctor.name": "Treating doctor name",
    "doctor.registration_number": "Doctor registration number",
    "treatment.diagnosis": "Diagnosis",
    "treatment.admission_date": "Admission date",
    "treatment.discharge_date": "Discharge date",
    "billing.total_amount": "Total billed amount",
    "billing.currency": "Currency",
}

#: Useful-but-not-blocking fields. Their absence becomes a *warning*.
OPTIONAL_CLAIM_FIELDS: Dict[str, str] = {
    "patient.address": "Patient address",
    "patient.email": "Patient email",
    "insurance.claim_number": "Insurance claim number",
    "insurance.group_number": "Insurance group number",
    "insurance.policy_holder": "Policy holder name",
    "hospital.phone": "Hospital phone number",
    "hospital.license_number": "Hospital licence number",
    "doctor.specialization": "Doctor specialization",
    "doctor.designation": "Doctor designation",
    "treatment.procedure": "Procedure performed",
    "treatment.icd_code": "ICD diagnosis code",
    "treatment.clinical_notes": "Clinical notes",
    "billing.invoice_number": "Invoice / bill number",
    "billing.invoice_date": "Invoice date",
    "billing.line_items": "Itemised billing breakdown",
    "claim.declared_by": "Claim declared by (patient / hospital)",
}


class AgentModel(BaseModel):
    """Base model for every structured payload exchanged between agents."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# ---------------------------------------------------------------------------
# 1. Agent payload models
# ---------------------------------------------------------------------------


class LineItem(AgentModel):
    """A single billable line on an invoice."""

    description: str = ""
    category: str = ""
    quantity: float = 0.0
    unit_price: float = 0.0
    amount: float = 0.0


class DocumentUnderstanding(AgentModel):
    """Output of the Document Understanding Agent (stage 1)."""

    patient_name: str = ""
    patient_date_of_birth: str = ""
    patient_gender: str = ""
    patient_phone: str = ""
    patient_address: str = ""
    patient_id: str = ""

    insurance_provider: str = ""
    insurance_policy_number: str = ""
    insurance_member_id: str = ""
    insurance_group_number: str = ""
    insurance_claim_number: str = ""
    insurance_policy_holder: str = ""

    hospital_name: str = ""
    hospital_address: str = ""
    hospital_phone: str = ""
    hospital_license_number: str = ""

    doctor_name: str = ""
    doctor_registration_number: str = ""
    doctor_specialization: str = ""
    doctor_designation: str = ""

    diagnosis: str = ""
    icd_code: str = ""
    treatment: str = ""
    procedure: str = ""
    admission_date: str = ""
    discharge_date: str = ""
    clinical_notes: str = ""

    total_amount: float = 0.0
    currency: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    line_items: List[LineItem] = Field(default_factory=list)

    documents_seen: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    low_confidence_fields: List[str] = Field(default_factory=list)
    #: flat field name -> the filename the value was read from (evidence).
    evidence: Dict[str, str] = Field(default_factory=dict)
    #: files that could not be read at all.
    unrecognised_documents: List[str] = Field(default_factory=list)

    def to_nested(self) -> Dict[str, Any]:
        """Return the flat extraction re-grouped into named sections.

        The flat layout above is what the model is asked to fill (it keeps the
        JSON schema small and unambiguous); this helper produces the grouped
        view the API and the UI display, i.e.::

            {"patient": {...}, "insurance": {...}, "hospital": {...},
             "doctor": {...}, "medical": {...}, "billing": {...},
             "missing_fields": [...]}
        """
        return {
            "patient": {
                "name": self.patient_name,
                "date_of_birth": self.patient_date_of_birth,
                "gender": self.patient_gender,
                "phone": self.patient_phone,
                "address": self.patient_address,
                "patient_id": self.patient_id,
            },
            "insurance": {
                "provider": self.insurance_provider,
                "policy_number": self.insurance_policy_number,
                "member_id": self.insurance_member_id,
                "group_number": self.insurance_group_number,
                "claim_number": self.insurance_claim_number,
                "policy_holder": self.insurance_policy_holder,
            },
            "hospital": {
                "name": self.hospital_name,
                "address": self.hospital_address,
                "phone": self.hospital_phone,
                "license_number": self.hospital_license_number,
            },
            "doctor": {
                "name": self.doctor_name,
                "registration_number": self.doctor_registration_number,
                "specialization": self.doctor_specialization,
                "designation": self.doctor_designation,
            },
            "medical": {
                "diagnosis": self.diagnosis,
                "icd_code": self.icd_code,
                "treatment": self.treatment,
                "procedure": self.procedure,
                "admission_date": self.admission_date,
                "discharge_date": self.discharge_date,
                "notes": self.clinical_notes,
            },
            "billing": {
                "total_amount": self.total_amount,
                "currency": self.currency,
                "invoice_number": self.invoice_number,
                "invoice_date": self.invoice_date,
                "line_items": [item.model_dump() for item in self.line_items],
            },
            "documents_seen": list(self.documents_seen),
            "missing_fields": list(self.missing_fields),
        }


class PatientInfo(AgentModel):
    name: str = ""
    date_of_birth: str = ""
    gender: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    patient_id: str = ""


class InsuranceInfo(AgentModel):
    provider: str = ""
    policy_number: str = ""
    member_id: str = ""
    group_number: str = ""
    claim_number: str = ""
    policy_holder: str = ""
    policy_start_date: str = ""
    policy_end_date: str = ""


class HospitalInfo(AgentModel):
    name: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    license_number: str = ""
    facility_type: str = ""


class DoctorInfo(AgentModel):
    name: str = ""
    registration_number: str = ""
    specialization: str = ""
    designation: str = ""
    phone: str = ""


class TreatmentInfo(AgentModel):
    diagnosis: str = ""
    icd_code: str = ""
    treatment: str = ""
    procedure: str = ""
    admission_date: str = ""
    discharge_date: str = ""
    clinical_notes: str = ""
    treatment_type: str = ""


class BillingInfo(AgentModel):
    total_amount: float = 0.0
    currency: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    line_items: List[LineItem] = Field(default_factory=list)
    discount: float = 0.0
    paid_amount: float = 0.0


class ClaimMeta(AgentModel):
    claim_number: str = ""
    claim_type: str = ""
    claimed_by: str = ""
    place_of_treatment: str = ""


class ClaimData(AgentModel):
    """The single, merged, normalised claim dataset (stage 2 output)."""

    patient: PatientInfo = Field(default_factory=PatientInfo)
    insurance: InsuranceInfo = Field(default_factory=InsuranceInfo)
    hospital: HospitalInfo = Field(default_factory=HospitalInfo)
    doctor: DoctorInfo = Field(default_factory=DoctorInfo)
    treatment: TreatmentInfo = Field(default_factory=TreatmentInfo)
    billing: BillingInfo = Field(default_factory=BillingInfo)
    claim: ClaimMeta = Field(default_factory=ClaimMeta)
    missing_fields: List[str] = Field(default_factory=list)
    uncertain_fields: List[str] = Field(default_factory=list)
    #: dotted field path -> "user" | "document" | "sample" | "derived"
    field_sources: Dict[str, str] = Field(default_factory=dict)
    #: dotted field path -> filename the value was read from
    field_evidence: Dict[str, str] = Field(default_factory=dict)


class Issue(AgentModel):
    """A single validation / review finding."""

    field: str = ""
    severity: Literal["info", "warning", "error"] = "warning"
    message: str = ""
    suggestion: str = ""
    source: str = ""


class InputPackage(AgentModel):
    """Output of the Input Agent (stage 0).

    A normalized, counted summary of everything the user supplied. It carries
    no new facts - it only proves what arrived, so the later agents know what
    they are working with.
    """

    patient_name: str = ""
    typed_field_count: int = 0
    document_count: int = 0
    document_filenames: List[str] = Field(default_factory=list)
    notes_present: bool = False
    has_documents: bool = False
    ready_for_analysis: bool = False
    message: str = ""


class NotesExtraction(AgentModel):
    """Facts pulled out of the user's free-text notes by Gemini."""

    patient_name: str = ""
    patient_date_of_birth: str = ""
    patient_gender: str = ""
    patient_phone: str = ""
    patient_address: str = ""

    insurance_provider: str = ""
    insurance_policy_number: str = ""
    insurance_member_id: str = ""

    hospital_name: str = ""
    hospital_address: str = ""
    hospital_phone: str = ""

    doctor_name: str = ""
    doctor_registration_number: str = ""
    doctor_specialization: str = ""

    diagnosis: str = ""
    treatment: str = ""
    procedure: str = ""
    admission_date: str = ""
    discharge_date: str = ""

    total_amount: float = 0.0
    currency: str = ""
    invoice_number: str = ""

    notes_summary: str = ""
    missing_fields: List[str] = Field(default_factory=list)


class SemanticIssue(AgentModel):
    """An issue found by an optional Gemini consistency pass."""

    field: str = ""
    severity: Literal["info", "warning", "error"] = "warning"
    message: str = ""


class SemanticCheck(AgentModel):
    """Result of the optional Gemini 'do these two facts agree?' pass."""

    ok: bool = True
    issues: List[SemanticIssue] = Field(default_factory=list)
    checked_pairs: int = 0


class ValidationResult(AgentModel):
    """Output of the Validation Agent (stage 3)."""

    valid: bool = True
    missing_required: List[str] = Field(default_factory=list)
    missing_optional: List[str] = Field(default_factory=list)
    inconsistencies: List[Issue] = Field(default_factory=list)
    warnings: List[Issue] = Field(default_factory=list)
    checked_fields: int = 0


class ClaimLineItem(AgentModel):
    description: str = ""
    category: str = ""
    amount: float = 0.0


class GeneratedClaim(AgentModel):
    """Output of the Claim Generation Agent (stage 4).

    This is the exact payload the deterministic PDF renderer consumes. The
    model has no control over layout, only over these values.
    """

    claim_number: str = ""
    claim_type: str = "Hospitalisation Cash Claim"
    claim_amount: float = 0.0
    currency: str = "INR"
    currency_symbol: str = ""
    service_period: str = ""
    narrative: str = ""
    line_items: List[ClaimLineItem] = Field(default_factory=list)
    sub_total: float = 0.0
    discount: float = 0.0
    total: float = 0.0
    place_of_treatment: str = ""
    claimed_by: str = ""
    documents_used: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    uncertain_fields: List[str] = Field(default_factory=list)
    generated_at: str = ""


class ReviewResult(AgentModel):
    """Output of the Review Agent (stage 5)."""

    status: Literal["READY_FOR_REVIEW", "NEEDS_CORRECTION"] = "READY_FOR_REVIEW"
    summary: str = ""
    issues: List[Issue] = Field(default_factory=list)
    checked_fields: int = 0


# ---------------------------------------------------------------------------
# 2. User input + API request models
# ---------------------------------------------------------------------------


class UserInputPatient(AgentModel):
    name: str = ""
    date_of_birth: str = ""
    gender: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""


class UserInputInsurance(AgentModel):
    provider: str = ""
    policy_number: str = ""
    member_id: str = ""
    group_number: str = ""
    policy_holder: str = ""


class UserInputHospital(AgentModel):
    name: str = ""
    address: str = ""
    phone: str = ""


class UserInputDoctor(AgentModel):
    name: str = ""
    registration_number: str = ""
    specialization: str = ""


class UserInputTreatment(AgentModel):
    diagnosis: str = ""
    admission_date: str = ""
    discharge_date: str = ""
    treatment: str = ""


class UserInputBilling(AgentModel):
    total_amount: str = ""
    currency: str = ""
    invoice_number: str = ""


class UserInput(AgentModel):
    """Everything the user typed into the claim creation form."""

    patient: UserInputPatient = Field(default_factory=UserInputPatient)
    insurance: UserInputInsurance = Field(default_factory=UserInputInsurance)
    hospital: UserInputHospital = Field(default_factory=UserInputHospital)
    doctor: UserInputDoctor = Field(default_factory=UserInputDoctor)
    treatment: UserInputTreatment = Field(default_factory=UserInputTreatment)
    billing: UserInputBilling = Field(default_factory=UserInputBilling)
    notes: str = ""


class CreateClaimRequest(AgentModel):
    title: str = ""
    use_sample_data: bool = False
    input_data: UserInput = Field(default_factory=UserInput)


class UpdateClaimRequest(AgentModel):
    title: str = ""
    input_data: UserInput | None = None
    regenerate: bool = False


class ClaimIdRequest(AgentModel):
    claim_id: str


# ---------------------------------------------------------------------------
# 3. Claim record / pipeline state
# ---------------------------------------------------------------------------

StageStatus = Literal[
    "pending", "processing", "completed", "warning", "failed", "skipped"
]
StageKey = Literal[
    "input", "document_analysis", "extraction", "validation", "generation", "review"
]


class PipelineStage(AgentModel):
    key: StageKey
    label: str
    status: StageStatus = "pending"
    #: Short, user-facing status. Never internal reasoning.
    message: str = "Waiting to start"
    agent: str = ""
    duration_ms: int = 0
    detail: str = ""


class DocumentMeta(AgentModel):
    document_id: str = ""
    filename: str = ""
    #: server-side path, internal only (stripped before sending to the frontend)
    stored_path: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    uploaded_at: str = ""
    #: what the document understanding agent thought it was
    detected_type: str = ""
    pages_or_frames: str = ""
    status: Literal["uploaded", "analysed", "failed"] = "uploaded"
    note: str = ""


class ClaimSummaryLine(AgentModel):
    claim_id: str = ""
    claim_number: str = ""
    patient_name: str = ""
    insurance_provider: str = ""
    total_amount: float = 0.0
    currency: str = ""
    status: str = "draft"
    missing_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    document_count: int = 0
    title: str = ""


class ClaimRecord(AgentModel):
    """Everything known about one claim. Persisted as JSON."""

    claim_id: str
    title: str = "Untitled claim"
    status: Literal[
        "draft", "processing", "needs_input", "ready", "ready_for_review", "error"
    ] = "draft"
    created_at: str = ""
    updated_at: str = ""
    ai_mode: Literal["gemini", "offline_deterministic"] = "gemini"
    input_data: UserInput = Field(default_factory=UserInput)
    documents: List[DocumentMeta] = Field(default_factory=list)
    stages: List[PipelineStage] = Field(default_factory=list)
    document_understanding: DocumentUnderstanding | None = None
    claim_data: ClaimData | None = None
    validation: ValidationResult | None = None
    generated: GeneratedClaim | None = None
    review: ReviewResult | None = None
    pdf_filename: str = ""
    error: str = ""
    #: Set when a stage had to fall back to the deterministic engine because
    #: Gemini was temporarily unusable. Never a substitute for `error` - the
    #: pipeline still completed, but the user should know why a stage is
    #: marked `warning` instead of `completed`.
    ai_notice: str = ""

    def to_summary(self) -> ClaimSummaryLine:
        data = self.claim_data
        return ClaimSummaryLine(
            claim_id=self.claim_id,
            claim_number=self.generated.claim_number if self.generated else "",
            patient_name=data.patient.name if data else "",
            insurance_provider=data.insurance.provider if data else "",
            total_amount=self.generated.claim_amount if self.generated else 0.0,
            currency=self.generated.currency if self.generated else "",
            status=self.status,
            missing_count=len(self.validation.missing_required) if self.validation else 0,
            created_at=self.created_at,
            updated_at=self.updated_at,
            document_count=len(self.documents),
            title=self.title,
        )

    def get_stage(self, key: str) -> PipelineStage | None:
        for stage in self.stages:
            if stage.key == key:
                return stage
        return None


def build_default_stages() -> List[PipelineStage]:
    """The fixed, ordered agent pipeline shown in the UI."""
    return [
        PipelineStage(
            key="input",
            label="Input",
            agent="Input Agent",
            status="pending",
            message="Collecting patient, insurance and document details",
        ),
        PipelineStage(
            key="document_analysis",
            label="Document Analysis",
            agent="Document Understanding Agent",
            status="pending",
            message="Reading uploaded documents and images",
        ),
        PipelineStage(
            key="extraction",
            label="Information Extraction",
            agent="Information Extraction Agent",
            status="pending",
            message="Merging typed details with extracted details",
        ),
        PipelineStage(
            key="validation",
            label="Validation",
            agent="Validation Agent",
            status="pending",
            message="Checking required fields and consistency",
        ),
        PipelineStage(
            key="generation",
            label="Claim Generation",
            agent="Claim Generation Agent",
            status="pending",
            message="Building the structured insurance claim form",
        ),
        PipelineStage(
            key="review",
            label="Final Review",
            agent="Review Agent",
            status="pending",
            message="Comparing the claim against its source data",
        ),
    ]


# ---------------------------------------------------------------------------
# 4. Sample / demo data
# ---------------------------------------------------------------------------


class SampleDocument(AgentModel):
    filename: str = ""
    label: str = ""
    description: str = ""
    mime_type: str = ""
    available: bool = False


class SampleData(AgentModel):
    title: str = ""
    description: str = ""
    input_data: UserInput = Field(default_factory=UserInput)
    documents: List[SampleDocument] = Field(default_factory=list)


class HealthResponse(AgentModel):
    status: str = "ok"
    ai_mode: str = ""
    app_name: str = ""
    version: str = ""
    models: Dict[str, str] = Field(default_factory=dict)
    model_checks: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    message: str = ""


class ApiError(AgentModel):
    detail: str = ""
    hint: str = ""
    code: str = ""


def as_dict(model: BaseModel) -> Dict[str, Any]:
    """Small helper used when serialising agent payloads to Gemini."""
    return model.model_dump(exclude_none=True)


__all__ = [
    "AgentModel",
    "LineItem",
    "DocumentUnderstanding",
    "PatientInfo",
    "InsuranceInfo",
    "HospitalInfo",
    "DoctorInfo",
    "TreatmentInfo",
    "BillingInfo",
    "ClaimMeta",
    "ClaimData",
    "Issue",
    "InputPackage",
    "NotesExtraction",
    "SemanticIssue",
    "SemanticCheck",
    "ValidationResult",
    "ClaimLineItem",
    "GeneratedClaim",
    "ReviewResult",
    "UserInputPatient",
    "UserInputInsurance",
    "UserInputHospital",
    "UserInputDoctor",
    "UserInputTreatment",
    "UserInputBilling",
    "UserInput",
    "CreateClaimRequest",
    "UpdateClaimRequest",
    "ClaimIdRequest",
    "StageStatus",
    "StageKey",
    "PipelineStage",
    "DocumentMeta",
    "ClaimSummaryLine",
    "ClaimRecord",
    "SampleDocument",
    "SampleData",
    "HealthResponse",
    "ApiError",
    "build_default_stages",
    "as_dict",
    "REQUIRED_CLAIM_FIELDS",
    "OPTIONAL_CLAIM_FIELDS",
]
