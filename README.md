Yes. Here is the **entire README as one single Markdown block**, ready to copy directly into `README.md`.

````markdown
# MediClaim · ClaimGen AI

A multi-agent, multimodal insurance-claim drafting application.

MediClaim lets you upload the documents you already have, such as:

- Hospital bills
- Discharge summaries
- Insurance policy schedules
- Insurance card photos
- Other supporting claim documents

A pipeline of specialised AI agents reads the documents, normalises the extracted information, checks required fields and consistency, and generates a structured insurance claim draft that can be downloaded as a PDF.

> **Important:** MediClaim produces a **DRAFT** only. It does not provide medical, clinical, legal, or insurance advice. It does not approve, reject, or adjudicate any claim. An authorised person must verify every field against the original records before submission.

---

## Features

- Multi-agent claim-processing pipeline
- Multimodal document analysis
- PDF and image document support
- Structured JSON communication between agents
- Field-level conflict resolution
- Required-field validation
- Date, amount, and identifier consistency checks
- Deterministic PDF claim generation
- Human-review checklist
- Gemini AI integration
- Offline deterministic fallback mode
- Sample data for quick testing
- Live pipeline stage status
- FastAPI backend
- React + Vite frontend
- Configurable Gemini models
- Upload and document limits
- Persistent or in-memory claim storage

---

## Architecture

MediClaim uses six sequential stages:

```text
Documents / User Input
        │
        ▼
┌─────────────────────┐
│  0. Input Agent     │
│  Normalisation      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  1. Document Agent  │
│  Document Analysis  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  2. Extraction      │
│  Agent              │
│  Data Extraction    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  3. Validation      │
│  Agent              │
│  Consistency Check  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  4. Generation      │
│  Agent              │
│  Claim Payload      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  5. Review Agent    │
│  Human Verification │
└──────────┬──────────┘
           │
           ▼
      Claim Draft PDF
````

Each stage exchanges **structured JSON only**. No stage is allowed to read another stage's internal reasoning.

---

## Agent Pipeline

| # | Stage             | Agent              | Responsibility                                                                                    |
| - | ----------------- | ------------------ | ------------------------------------------------------------------------------------------------- |
| 0 | Input             | `input_agent`      | Normalises inputs and counts supplied documents. Invents nothing.                                 |
| 1 | Document Analysis | `document_agent`   | Reads multimodal documents and identifies their contents.                                         |
| 2 | Extraction        | `extraction_agent` | Merges typed information with document information and resolves field-level conflicts.            |
| 3 | Validation        | `validation_agent` | Checks required fields, dates, totals, identifiers, and internal consistency.                     |
| 4 | Generation        | `generation_agent` | Builds the structured claim payload consumed by the PDF renderer.                                 |
| 5 | Review            | `review_agent`     | Compares the draft against source information and identifies fields requiring human verification. |

---

## Design Principles

### 1. Deterministic PDF Generation

The AI model never controls the PDF layout.

The model only produces structured claim fields. ReportLab is responsible for rendering the final PDF.

This ensures that the same claim data produces a predictable document layout.

### 2. No Guessing

Missing information is never fabricated.

If a required value cannot be extracted or verified, it remains blank and is reported as missing.

```text
Missing information
        ↓
Blank field
        ↓
Validation warning
        ↓
needs_input
```

### 3. Human Verification

The generated claim is always treated as a draft.

An authorised person must verify the generated information against the original documents before submission.

### 4. No Medical or Clinical Judgement

MediClaim does not:

* Diagnose medical conditions
* Interpret medical findings
* Recommend treatments
* Determine claim eligibility
* Approve claims
* Reject claims
* Adjudicate claims

### 5. AI Transparency

Every pipeline stage reports whether AI was used.

```text
used_ai = true
```

or:

```text
used_ai = false
```

This makes it clear which parts were processed using Gemini and which parts used the deterministic fallback.

---

# Getting Started

## 1. Clone the Repository

```powershell
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd claimgen-ai-solo
```

---

## 2. Requirements

Make sure the following are installed:

| Requirement | Version               |
| ----------- | --------------------- |
| Python      | 3.11 or newer         |
| Node.js     | 18 or newer           |
| npm         | Included with Node.js |

Tested with:

* Python 3.12
* Node.js 22

---

# API Key Configuration

The Gemini API key is stored in a single `.env` file at the project root.

Example:

```text
E:\WEB\mediclaim\claimgen-ai-solo\.env
```

Create it from the template:

```powershell
cd E:\WEB\mediclaim\claimgen-ai-solo

copy .env.example .env
```

Open `.env` and add your Gemini API key:

```env
GEMINI_API_KEY=PASTE_YOUR_REAL_KEY_HERE
```

Get a Gemini API key from:

[https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)

> **Security:** Never commit your real API key to GitHub. The `.gitignore` file should exclude `.env`.

The backend can also automatically load:

```text
backend/.env
```

if you prefer to keep the API key local to the backend.

---

# Running Without an API Key

Leaving `GEMINI_API_KEY` blank is supported.

The application then runs in:

```text
offline_deterministic
```

mode.

No AI calls are made.

The deterministic fallback:

* Reads the embedded text layer of PDFs
* Extracts available text
* Runs the complete pipeline
* Performs validation
* Generates the final PDF

However, offline mode does **not** read images or scanned PDF pages.

This mode is intended for testing and demonstrations without consuming AI quota.

You can also force offline mode even when an API key exists:

```env
FORCE_OFFLINE=1
```

---

# Running the Backend

Open a terminal and navigate to the backend:

```powershell
cd E:\WEB\mediclaim\claimgen-ai-solo\backend
```

## Create the Virtual Environment

Run this once:

```powershell
py -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Install Dependencies

```powershell
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

## Start the Backend

```powershell
py -m uvicorn main:app --reload
```

The backend will be available at:

```text
http://127.0.0.1:8000
```

FastAPI documentation:

```text
http://127.0.0.1:8000/docs
```

---

# Running the Backend on Another Port

If port `8000` is already being used, you may see:

```text
WinError 10013
An attempt was made to access a socket in a way forbidden by its access permissions
```

Run the backend on another port, for example:

```powershell
py -m uvicorn main:app --reload --port 8020
```

The backend will then run at:

```text
http://127.0.0.1:8020
```

Create or update:

```text
frontend/.env.local
```

with:

```ini
BACKEND_URL=http://127.0.0.1:8020
FRONTEND_PORT=5173
```

To see what is using port `8000`:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000
```

---

# Running the Frontend

Open a second terminal:

```powershell
cd E:\WEB\mediclaim\claimgen-ai-solo\frontend
```

Install dependencies:

```powershell
npm install
```

Start the development server:

```powershell
npm run dev
```

Open:

```text
http://localhost:5173
```

Vite proxies `/api` requests to the backend, so the browser uses same-origin API requests during development.

If the backend is running on another port, configure:

```text
frontend/.env.local
```

For example:

```ini
BACKEND_URL=http://127.0.0.1:8020
FRONTEND_PORT=5173
```

These values configure the development server and are not bundled into the browser build.

---

# Try It in 30 Seconds

1. Open:

   ```text
   http://localhost:5173
   ```

2. Leave **Use sample data** selected.

3. Press **Create claim**.

   Four realistic sample documents are generated automatically.

4. Press **Run full pipeline**.

   The six stages stream their progress live.

5. When processing finishes, you get:

   * Merged claim data
   * Validation result
   * Generated claim
   * Final review
   * Human verification requirements

6. Press **Download PDF** to generate the deterministic, paginated claim form.

---

# How It Works

MediClaim consists of six sequential stages.

## Stage 0 — Input Agent

```text
input_agent
```

Responsibilities:

* Normalise supplied inputs
* Count uploaded documents
* Identify available input types
* Preserve user-provided information
* Never invent missing information

---

## Stage 1 — Document Analysis Agent

```text
document_agent
```

Responsibilities:

* Analyse uploaded documents
* Read PDF text
* Process supported images and scans when AI is available
* Identify document types
* Extract document-level observations

---

## Stage 2 — Extraction Agent

```text
extraction_agent
```

Responsibilities:

* Merge user-entered information
* Merge document information
* Resolve conflicts field by field
* Identify uncertain values
* Preserve missing fields

Example:

```text
Hospital Bill
     ↓
Patient Name

Policy Schedule
     ↓
Policy Number

Insurance Card
     ↓
Member ID

Discharge Summary
     ↓
Admission / Discharge Dates
```

---

## Stage 3 — Validation Agent

```text
validation_agent
```

Responsibilities:

* Check required fields
* Validate dates
* Check amounts and totals
* Check identifiers
* Detect inconsistencies
* Identify missing information

Possible results:

```text
valid
```

or:

```text
needs_input
```

---

## Stage 4 — Generation Agent

```text
generation_agent
```

Responsibilities:

* Create the final structured claim payload
* Convert validated information into the format expected by the PDF renderer
* Avoid controlling document layout

---

## Stage 5 — Review Agent

```text
review_agent
```

Responsibilities:

* Compare generated fields with source information
* Identify fields requiring human verification
* Highlight unresolved discrepancies
* Produce the final review checklist

---

# Models, Quotas and Outages

Gemini model names and availability can change over time.

MediClaim therefore keeps model configuration in environment variables instead of hard-coding model names throughout the application.

The application also provides a health endpoint that actually tests configured models.

A valid API key alone does not guarantee that a configured model is available.

---

# Model Health Check

The `/api/health` endpoint performs actual model requests.

Run:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 5
```

The endpoint reports model availability and classifies failures.

Possible failure classes include:

| Class        | Meaning                                    |
| ------------ | ------------------------------------------ |
| `auth`       | Invalid or unauthorised API key            |
| `model`      | Model unavailable, retired, or not enabled |
| `quota`      | Quota exhausted or rate limited            |
| `overloaded` | Temporary service overload                 |
| `content`    | Content-related request failure            |

Only transient failures are retried with exponential backoff.

Permanent configuration failures are reported immediately.

---

# Graceful AI Fallback

Every agent computes its deterministic result before making an AI request.

If Gemini becomes temporarily unavailable, the stage can fall back to its deterministic result.

```text
                Gemini Request
                      │
            ┌─────────┴─────────┐
            │                   │
         Success              Failure
            │                   │
            ▼                   ▼
        AI Result       Deterministic Result
                                │
                                ▼
                             Warning
```

Previously completed AI work is not discarded.

The application clearly indicates when a stage has fallen back to deterministic processing.

---

# Offline Deterministic Mode

When:

```env
GEMINI_API_KEY=
```

the application automatically uses deterministic processing.

Offline mode can:

* Read PDF text layers
* Process structured document information
* Run validation
* Generate claim data
* Generate PDFs

Offline mode cannot:

* Analyse images
* Read scanned PDF pages
* Perform multimodal AI analysis

The UI clearly labels the application as running in offline deterministic mode.

---

# Configuration

All settings are stored in `.env`.

See `.env.example` for the complete configuration reference.

| Variable                  | Default            | Purpose                                         |
| ------------------------- | ------------------ | ----------------------------------------------- |
| `GEMINI_API_KEY`          | —                  | Gemini API key. Blank enables offline mode.     |
| `GEMINI_MODEL_EXTRACTION` | `gemini-3.8-flash` | Model used for document reading and extraction. |
| `GEMINI_MODEL_REASONING`  | `gemini-3.8-flash` | Model used where reasoning is required.         |
| `GEMINI_MODEL_REVIEW`     | `gemini-3.8-flash` | Model used for final field-level review.        |
| `GEMINI_TEMPERATURE_*`    | `0.0 / 0.1`        | Low temperature for consistent data processing. |
| `FORCE_OFFLINE`           | `0`                | Set to `1` to disable AI processing.            |
| `MAX_UPLOAD_MB`           | `20`               | Maximum upload size per file.                   |
| `MAX_DOCUMENTS_PER_CLAIM` | `10`               | Maximum number of documents per claim.          |
| `CORS_ORIGINS`            | `localhost:5173`   | Allowed browser origins.                        |
| `PERSIST_CLAIMS`          | `true`             | Enables claim persistence.                      |

---

# Project Structure

```text
claimgen-ai-solo/
│
├── .env.example
├── .gitignore
├── README.md
│
├── backend/
│   ├── main.py
│   ├── config.py
│   │
│   ├── models/
│   │   └── schemas.py
│   │
│   ├── agents/
│   │   ├── input_agent.py
│   │   ├── document_agent.py
│   │   ├── extraction_agent.py
│   │   ├── validation_agent.py
│   │   ├── generation_agent.py
│   │   └── review_agent.py
│   │
│   ├── services/
│   │   ├── pipeline.py
│   │   ├── gemini.py
│   │   ├── offline.py
│   │   ├── normalize.py
│   │   ├── pdf_generator.py
│   │   ├── sample_data.py
│   │   └── store.py
│   │
│   ├── _smoke_test.py
│   │
│   └── data/
│       ├── claims/
│       ├── uploads/
│       └── generated/
│
└── frontend/
    ├── package.json
    ├── vite.config.*
    ├── src/
    └── public/
```

---

# Useful Commands

## Backend End-to-End Test

The backend includes an end-to-end smoke test that does not require the server to be running.

```powershell
cd backend
py _smoke_test.py
```

---

## Production Frontend Build

```powershell
cd frontend
npm run build
```

---

# API Documentation

When the backend is running, FastAPI provides interactive API documentation.

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

OpenAPI schema:

```text
http://127.0.0.1:8000/openapi.json
```

Health endpoint:

```text
http://127.0.0.1:8000/api/health
```

---

# Troubleshooting

## Backend exits with `WinError 10013`

### Cause

Port `8000` is already being used.

### Solution

Run the backend on another port:

```powershell
py -m uvicorn main:app --reload --port 8020
```

Then update:

```text
frontend/.env.local
```

```ini
BACKEND_URL=http://127.0.0.1:8020
FRONTEND_PORT=5173
```

---

## Frontend Shows Network Errors

Check that:

1. The backend is running.
2. The frontend is running.
3. `BACKEND_URL` points to the correct backend port.
4. The backend health endpoint is accessible.

Test:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

---

## Gemini Is Only Partly Available

Check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 5
```

The response identifies the failing model and failure category.

Common causes include:

* Retired model name
* Invalid API key
* Exhausted quota
* Rate limiting
* Temporary service overload

---

## `404 NOT_FOUND` for a Gemini Model

The configured model may no longer be available.

Update the corresponding model variables in `.env` using currently supported Gemini model names.

For example:

```env
GEMINI_MODEL_EXTRACTION=gemini-3.8-flash
GEMINI_MODEL_REASONING=gemini-3.8-flash
GEMINI_MODEL_REVIEW=gemini-3.8-flash
```

Then restart the backend.

> Model names can change over time. Check the current Gemini documentation if a configured model becomes unavailable.

---

## Gemini Quota Exhausted

If Gemini API quota is exhausted, MediClaim can fall back to deterministic processing for supported documents.

You can:

* Wait for the quota window to reset
* Use another available model
* Use another API key where appropriate
* Enable offline mode

```env
FORCE_OFFLINE=1
```

Restart the backend after changing the configuration.

---

## Stage Shows `warning`

A stage showing:

```text
warning
```

with:

```text
deterministic mode (no AI)
```

means that the stage used the deterministic fallback.

This can happen when:

* No API key is configured
* `FORCE_OFFLINE=1`
* Gemini is temporarily unavailable
* The configured model cannot process the request

---

## Banner Says "Offline Deterministic Mode"

Check:

```env
GEMINI_API_KEY=YOUR_KEY
```

Make sure:

* `.env` exists
* The API key is correct
* The file is saved
* The backend has been restarted

---

## Upload Rejected

Possible causes:

* File exceeds `MAX_UPLOAD_MB`
* More than `MAX_DOCUMENTS_PER_CLAIM` documents were uploaded
* Unsupported file type
* Invalid document

Default limits:

```env
MAX_UPLOAD_MB=20
MAX_DOCUMENTS_PER_CLAIM=10
```

---

# Security

Never commit secrets to GitHub.

Your `.gitignore` should exclude:

```text
.env
.env.local
backend/.env
frontend/.env.local
```

Never place API keys directly inside:

* React source code
* JavaScript files
* Python source files
* Public GitHub repositories
* Client-side configuration intended for browser exposure

Keep secret API keys on the backend.

---

# Data and Privacy

MediClaim processes potentially sensitive insurance and healthcare-related documents.

When deploying the application, review:

* Where uploaded files are stored
* How long claim data is retained
* Who can access uploaded documents
* API provider data-processing policies
* Production authentication requirements
* Access control
* Logging configuration
* Backup policies
* Data deletion policies

Do not use real patient or insurance documents in an unsecured development deployment.

---

# Limitations

MediClaim is a claim-drafting system and has important limitations.

It does not:

* Guarantee that extracted information is correct
* Replace human document verification
* Provide medical advice
* Provide clinical interpretation
* Provide legal advice
* Determine insurance coverage
* Determine claim eligibility
* Approve claims
* Reject claims
* Adjudicate claims
* Guarantee acceptance by an insurer

All generated information must be verified against the original documents before submission.

---

# Technology Stack

## Frontend

* React
* Vite
* JavaScript

## Backend

* Python
* FastAPI
* Pydantic
* Uvicorn

## AI

* Google Gemini
* Multimodal document analysis
* Structured JSON generation
* Deterministic fallback processing

## Document Processing

* PDF text extraction
* Image/document analysis
* ReportLab PDF generation
* Structured data normalisation

---

# Development Workflow

```text
1. Start Backend
       │
       ▼
2. Start Frontend
       │
       ▼
3. Upload Documents
       │
       ▼
4. Create Claim
       │
       ▼
5. Run Pipeline
       │
       ▼
6. Review Validation Results
       │
       ▼
7. Review Generated Claim
       │
       ▼
8. Verify Against Original Documents
       │
       ▼
9. Download PDF
       │
       ▼
10. Authorised Person Submits Claim
```

---

# Disclaimer

**MediClaim · ClaimGen AI is a claim-drafting and document-processing application.**

The generated claim is a draft and may contain missing, incorrect, or ambiguous information.

Users must verify all generated information against the original source documents before submitting any claim.

MediClaim does not provide medical, clinical, legal, or insurance advice and does not approve, reject, or adjudicate insurance claims.

---

# License

Add your preferred license here.

For example:

```text
MIT License
```

```
```
