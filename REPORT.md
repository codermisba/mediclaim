# MediClaim · ClaimGen AI — Project Report

---

## 1. Title

**MediClaim · ClaimGen AI — a multi-agent, multimodal insurance claim drafting
system built on Google Gemini, FastAPI and React.**

| | |
|---|---|
| Project | MediClaim / ClaimGen AI |
| Version | 1.0.0 |
| Location | `E:\WEB\mediclaim\claimgen-ai-solo` |
| Backend | FastAPI + Google Gen AI SDK, deployed on **Render** |
| Frontend | React 18 + Vite 5, deployed on **Vercel** |
| Local API | http://127.0.0.1:8080 |
| Local UI | http://localhost:5174 |
| Size | ~5,900 lines of Python, ~1,740 lines of frontend, 14 API endpoints |

---

## 2. Objective

### 2.1 Problem

Filling out an insurance claim form is manual data entry. The information
already exists — it is scattered across a hospital bill, a discharge summary, a
policy schedule and an insurance card. Someone re-types it into a claim form,
and every re-typing is a chance to introduce a typo that becomes a rejection.

### 2.2 Objective

Build a system that **reads the documents a patient already has and drafts the
claim form**, so the human's job becomes *verification* rather than data entry.

### 2.3 Explicit non-goals

These are design constraints, not omissions:

- **No medical or clinical judgement.** The system transcribes and checks
  consistency. It does not diagnose, treat or opine on care.
- **No claim approval, rejection or adjudication.** Output is a draft.
- **No fabrication, ever.** A blank field stays blank and is reported as
  missing. The pipeline halts with `needs_input` rather than guessing.
- **No chain-of-thought between agents.** They exchange Pydantic/JSON objects
  only, so each stage is auditable and independently testable.
- **The model never controls the PDF layout.** It fills structured fields;
  ReportLab renders the form deterministically.

### 2.4 Success criteria

| Criterion | Target | Result |
|---|---|---|
| All required fields extracted from 4 documents | 26/26 | 26/26 |
| Invoice line items recovered exactly | 6 items, total 48,750.00 | 6 items, 48,750.00 |
| Total preserved through pipeline | exact | exact, cross-checked in validation |
| Deterministic PDF output | valid, paginated | 3 pages, 9.5 KB, valid `%PDF-` |
| Works with no API key | yes | yes, fully labelled offline mode |
| Survives a Gemini outage mid-run | no data loss | yes, degrades and discloses |
| UI build | clean | 41 modules, no warnings |

---

## 3. Framework

### 3.1 Technology choices and why

| Layer | Choice | Reason |
|---|---|---|
| API | **FastAPI** | Async (the pipeline is I/O bound on model calls), automatic OpenAPI docs at `/docs`, Pydantic validation on every boundary. |
| Model SDK | **google-genai** (official) | Structured output via JSON schema, native multimodal parts, `max_output_tokens`. |
| Model | **gemini-3.8-flash** | The 2.5 models are retired (404 for new keys). Flash is fast, multimodal and cheap for extraction work. |
| Contracts | **Pydantic v2** | One schema per agent output. The model is constrained to it and the result is validated on arrival — a malformed response fails the stage instead of corrupting downstream state. |
| PDF | **ReportLab** | Pure Python, deterministic, no headless browser needed. |
| UI | **React 18 + Vite 5** | Fast dev server, small production bundle (~54 KB gzipped). |
| Styling | **Hand-written CSS design system** | No dependency; full control; consistent tokens. |
| Storage | **JSON files** | Zero-setup for a demo. Documented as ephemeral on Render's free tier. |

### 3.2 Repository layout

```
claimgen-ai-solo/
├─ render.yaml              Render blueprint (backend)
├─ DEPLOY.md                deployment guide
├─ REPORT.md                this document
├─ README.md                setup + usage
├─ .env.example             all configuration
├─ backend/
│  ├─ main.py               FastAPI app, 14 routes          515 lines
│  ├─ config.py             env-driven settings             141
│  ├─ models/schemas.py     every agent/API contract        593
│  ├─ agents/               the six pipeline agents
│  │  ├─ base.py            stage timing, errors            78
│  │  ├─ input_agent.py                                   77
│  │  ├─ document_agent.py                                148
│  │  ├─ extraction_agent.py                              383
│  │  ├─ validation_agent.py                              463
│  │  ├─ generation_agent.py                              288
│  │  └─ review_agent.py                                  333
│  ├─ services/
│  │  ├─ pipeline.py        orchestration + degradation    238
│  │  ├─ gemini.py          client, retries, classify     433
│  │  ├─ offline.py         deterministic PDF reader      379
│  │  ├─ normalize.py       dates, money, identifiers     299
│  │  ├─ pdf_generator.py   deterministic form            669
│  │  ├─ sample_data.py     generated demo documents       540
│  │  └─ store.py           persistence                    135
│  └─ _smoke_test.py        end-to-end check               124
└─ frontend/
   ├─ vercel.json           Vercel config
   └─ src/                  8 components + App + api       1737
```

---

## 4. Agents — block diagram

### 4.1 Pipeline

```
                    ┌──────────────────────────────────────────┐
   Documents  ─────▶│  0 · INPUT AGENT                        │
   (PDF/PNG/JPG)     │  normalise + count, invent nothing     │
   Typed fields ───▶└────────────────────┬─────────────────────┘
                                         │ ClaimRecord
                                         ▼
                    ┌──────────────────────────────────────────┐
                    │  1 · DOCUMENT ANALYSIS AGENT             │
                    │  multimodal read: what is each document?│
                    │  → DocumentUnderstanding                 │
                    └────────────────────┬─────────────────────┘
                                         │
                                         ▼
                    ┌──────────────────────────────────────────┐
                    │  2 · EXTRACTION AGENT                   │
                    │  merge typed + document data            │
                    │  resolve conflicts per field            │
                    │  → ClaimData (+ sources, evidence)      │
                    └────────────────────┬─────────────────────┘
                                         │
                    ┌────────────────────┴─────────┐
                    │  3 · VALIDATION AGENT         │
                    │  rules: required, dates,      │
                    │  totals, IDs, chronology      │
                    │  + model: semantic clashes    │
                    │  → ValidationResult           │
                    └────────────────────┬─────────┘
                                         │ all required present?
                              ┌──────────┴──────────┐
                             NO                   YES
                              │                    │
                    ┌─────────▼────────┐  ┌────────▼─────────────────┐
                    │ status:          │  │  4 · GENERATION AGENT    │
                    │ needs_input      │  │  deterministic builder  │
                    │ + list of gaps   │  │  → GeneratedClaim        │
                    │ NOTHING guessed  │  └────────┬─────────────────┘
                    └──────────────────┘           │
                                                    ▼
                                           ┌────────────────────────┐
                                           │  5 · REVIEW AGENT      │
                                           │  compare draft against │
                                           │  source, list what a   │
                                           │  human must confirm     │
                                           │  → ReviewResult        │
                                           └────────┬───────────────┘
                                                    ▼
                                           ┌────────────────────────┐
                                           │  ReportLab (no LLM)    │
                                           │  deterministic PDF     │
                                           └────────────────────────┘
```

### 4.2 Two execution paths per stage

Every stage has the same shape: compute the deterministic answer **first**,
then try the model. This is the single most important structural decision in
the project — it is what makes the app resilient.

```
        stage input
             │
     ┌───────┴────────┐
     │ deterministic  │  always runs; rules, patterns, arithmetic
     │ (offline.py /  │  no network, no quota, fully reproducible
     │  normalize.py) │
     └───────┬────────┘
             │
     ┌───────┴────────┐  gemini.try_structured()
     │  Gemini call   │──► 200 ──► validate against Pydantic ──► merge
     └───────┬────────┘                                    used_ai = True
             │ quota / overload
             ▼
     keep deterministic answer ──► used_ai = False, stage = warning
             │                        (disclosed in UI, never silent)
             ▼
     retired model / bad key ──► raise, stage = failed
```

### 4.3 Agent responsibilities

| # | Agent | Input → Output | Owns |
|---|---|---|---|
| 0 | `input_agent` | `UserInput` → normalised counts | Never invents; reports what is present |
| 1 | `document_agent` | documents → `DocumentUnderstanding` | Multimodal reading, document typing |
| 2 | `extraction_agent` | `+ UserInput` → `ClaimData` | Merge + per-field conflict resolution |
| 3 | `validation_agent` | `ClaimData` → `ValidationResult` | Required fields, dates, totals, IDs, semantics |
| 4 | `generation_agent` | `+ ValidationResult` → `GeneratedClaim` | Narrative, line items, identifiers |
| 5 | `review_agent` | `+ DocumentUnderstanding` → `ReviewResult` | Final human-review checklist |

---

## 5. Collaboration

### 5.1 How agents cooperate

**Through the record, not through each other.** `pipeline.py` owns a single
`ClaimRecord` and passes it down. Agents never import each other and never call
each other directly:

```python
# services/pipeline.py
async with stage(record, "extraction", "Extracting claim information"):
    claim_data, used_ai, message = await extraction_agent.run(
        record.claim_data, record.document_understanding, record.input_data
    )
record.claim_data = claim_data
```

This gives three properties that matter:

1. **Testability.** An agent can be called with a hand-built `ClaimRecord`.
2. **Auditability.** Every stage's output is persisted, so a finished claim can
   be inspected field by field after the fact.
3. **Serialisation.** The UI can render partial progress because state is
   written to disk after every stage, not held in a pipeline frame.

### 5.2 Shared contracts

All communication is one of the eight Pydantic models in
`models/schemas.py`. A stage that returns something not matching its schema
fails loudly at the boundary — a malformed model response can never leak
downstream.

| Contract | Produced by | Consumed by |
|---|---|---|
| `DocumentUnderstanding` | document agent | extraction, review |
| `ClaimData` | extraction agent | validation, generation, review |
| `ValidationResult` | validation agent | generation, review, PDF |
| `GeneratedClaim` | generation agent | review, PDF |
| `ReviewResult` | review agent | UI, PDF |
| `ClaimRecord` | pipeline (shared state) | API, UI, PDF |

### 5.3 Human in the loop

Collaboration does not end with the model. The `review_agent` exists
specifically to produce the checklist a human works through, and the PDF is
banner-stamped as a draft. A claim leaves the system as *work to be verified*,
never as a decision.

---

## 6. Design

### 6.1 Determinism as a requirement

The same claim must always produce the same PDF. Two consequences:

- The model may fill fields but may **never** emit markup, HTML or layout
  instructions. `pdf_generator.py` renders from the schema alone.
- Every date, amount and identifier passes through `normalize.py`
  (`parse_date`, `format_money`, `strip_credentials`) so equivalent inputs
  cannot produce different strings.

### 6.2 Truthfulness over completeness

The central tension in a claims tool is *fill in the blanks* versus *never
invent*. This project resolves it firmly toward truthfulness:

- A missing required field → `missing_required` → status `needs_input`, the
  pipeline halts, and the PDF is not generated.
- A field the model is unsure about → `uncertain_fields`, surfaced in the UI.
- Evidence is retained: `field_sources` (typed / document / derived) and
  `field_evidence` (filename + snippet) per field.

### 6.3 Resilience: honest degradation

A quota window can run out mid-pipeline. Two design rules follow:

**Never discard completed work.** If stage 5 cannot reach Gemini, stages 1-4
keep their results. The claim still reaches `ready_for_review`.

**Never hide the degradation.** A stage that did not use the model is marked
`warning`, its detail says `deterministic mode (no AI)`, and the claim carries
`ai_notice` which the UI renders as a banner. Silence would be the one
unacceptable outcome.

Note the asymmetry: quota/overload degrades, but a **retired model or a bad key
fails loudly** — those are user configuration bugs, and silently falling back
would hide a problem the user must fix.

### 6.4 Model lifecycle management

Model names rot. `services/gemini.py` classifies every failure:

| Kind | Cause | Retry? | Result |
|---|---|---|---|
| `auth` | bad key | no | fail, tell them to check the key |
| `model` | retired / not enabled | no | fail, name a working model |
| `quota` | exhausted / rate limited | no | degrade to deterministic |
| `overloaded` | transient 500/503 | yes, 2s→4s→8s (cap 20s) | then degrade |
| `content` | empty / non-JSON | yes | then fail |

`GET /api/health` sends one tiny real request per configured model, because a
key being accepted proves nothing — a retired model name still authenticates
cleanly. Results are cached 5 minutes so a UI polling the banner does not spend
quota. `GET /api/live` is a separate, model-free route for the platform health
check.

### 6.5 UI design

A single accent colour, one radius ramp, a 4px spacing grid, tabular numerals
for money, and `prefers-reduced-motion` respected. The pipeline renders as a
connected timeline with a progress bar so a 30-second run feels legible, and
every state is visible: pending, processing, completed, warning, failed,
degraded, offline.

---

## 7. Flow

### 7.1 Request flow

```
Browser
  │  POST /api/claim/create  {use_sample_data: true}
  ▼
FastAPI  ── sample_data.py generates 4 realistic documents
  │        (bill, discharge summary, policy schedule, card photo)
  │     writes ClaimRecord (status: draft) to data/claims/
  ▼
  │  POST /api/claim/process
  ▼
Background asyncio task ─────────────────────────────┐
  │  for each stage:                                │
  │    mark processing → persist → do work →         │
  │    mark done + duration_ms → persist            │
  │                                                 │
  │  UI polls GET /api/claim/{id} every 1.5s ───────┘
  ▼
stage 1 document  →  Gemini (4 attachments, 1 call)
stage 2 extraction →  Gemini (1 call)
stage 3 validation →  deterministic rules, then Gemini
stage 4 generation →  deterministic builder, then Gemini
stage 5 review     →  deterministic compare, then Gemini
  │
  ▼
pdf_generator.build_claim_pdf()  ── ReportLab, no LLM ──▶ 3-page PDF
  │
  ▼
status: ready_for_review
```

### 7.2 Field provenance

Every extracted field carries where it came from, which is what makes the output
auditable rather than merely plausible:

```json
"patient.name":  { "source": "document",  "evidence": "medical-bill.pdf: 'Patient Name'" }
"patient.phone": { "source": "typed" }
"billing.total_amount": { "source": "derived", "from": "line items" }
```

### 7.3 Degradation flow (observed in testing)

```
document_analysis  27.3s  warning   overloaded → deterministic reader
extraction         17.4s  completed  Gemini succeeded, 8 typed + 31 extracted
validation          0.4s  warning   quota → deterministic rules
generation          0.5s  warning   quota → deterministic builder
review              0.5s  warning   quota → deterministic compare
                   ──────
                   status: ready_for_review   ai_notice: disclosed
                   PDF: 9,577 bytes           extraction kept!
```

Before this change the same run ended `error` with the successful document
analysis thrown away.

---

## 8. Code

### 8.1 Selective code walkthrough

**Gemini call with classification and backoff** — `services/gemini.py`

```python
for attempt in range(1, attempts + 1):
    try:
        response = await asyncio.to_thread(
            client.models.generate_content, model=model_name,
            contents=contents, config=config,
        )
        return _coerce(response.text, response_model, model_name)
    except GeminiError as exc:
        last_error = exc
    except Exception as exc:
        last_error = classify_exception(exc, model_name)

    # A retired model, a bad key or an exhausted quota fails identically on
    # every retry, so stop now and let the user fix the cause.
    if last_error.kind in FATAL_KINDS:
        raise last_error

    if attempt < attempts:
        delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
        await asyncio.sleep(delay)
```

**Graceful degradation** — `services/gemini.py`

```python
async def try_structured(**kwargs):
    try:
        return await run_structured(**kwargs), ""
    except GeminiError as exc:
        if exc.kind not in DEGRADE_KINDS:   # auth / model -> raise
            raise
        return None, (
            f"Gemini was unavailable for this stage ({exc.kind}: {exc.message}) "
            "so the deterministic engine was used instead. Results are still "
            "flagged for human review."
        )
```

**Never let a stage look successful without the model** — `services/pipeline.py`

```python
if not used_ai:
    # True both offline and when a stage degraded, so a stage that never
    # called the model must never look like a clean success.
    status = "warning" if status == "completed" else status
    detail = (detail + " - " if detail else "") + "deterministic mode (no AI)"
    if record.ai_mode == "gemini" and not record.ai_notice:
        record.ai_notice = "At least one stage could not reach Gemini ..."
```

**Hallucination gate** — `agents/validation_agent.py`

```python
result.valid = not result.missing_required and not blocking
```

### 8.2 API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/live` | Cheap liveness probe (no model calls) |
| GET | `/api/health` | Full status + per-model diagnostics |
| GET | `/api/config` | Public configuration |
| GET | `/api/claims` | Dashboard list |
| GET | `/api/claims/sample` | Sample claim preview |
| GET | `/api/claims/sample/documents/{name}` | Download a sample document |
| POST | `/api/claim/create` | Create (sample or manual) |
| PUT | `/api/claim/{id}` | Update typed fields |
| DELETE | `/api/claim/{id}` | Delete claim + documents |
| GET | `/api/claim/{id}` | `{claim_id, pipeline_running, claim}` |
| POST | `/api/claim/upload` | Attach documents |
| DELETE | `/api/claim/upload/{cid}/{did}` | Remove a document |
| POST | `/api/claim/process` | Run all six stages |
| POST | `/api/claim/validate` | Validation stage only |
| POST | `/api/claim/generate` | Generation stage only |
| POST | `/api/claim/review` | Review stage only |
| GET | `/api/claim/{id}/pdf` | Deterministic claim form PDF |

### 8.3 Frontend

8 components (`NewClaimForm`, `ClaimOverview`, `PipelineStages`,
`DocumentPanel`, `ClaimDataPanel`, `ValidationPanel`, `GeneratedPanel`,
`ReviewPanel`) plus `App` (state, polling, actions) and `api` (fetch wrapper).
Polling is guarded against overlap because a free-tier host can take 50s to
wake.

---

## 9. Output

### 9.1 Verified run (Gemini live, quota exhausted)

```
status  : ready_for_review
valid   : True   checked=26   missing_required: []
items   : 6 line items, total 48,750.00 INR
patient : Aarav Sharma
number  : MC-20260928-E696C8
review  : READY_FOR_REVIEW (17 fields compared, 0 issues)
PDF     : HTTP 200, 9,581 bytes, magic b'%PDF-', 3 pages
stages  : input ✓, doc-analysis ⚠, extraction ✓, validation ⚠, generation ⚠, review ⚠
notice  : degradation disclosed
```

### 9.2 Deterministic run (no API key)

```
status  : ready_for_review,  valid=True, checked=26, missing_required: []
stages  : all warning, each labelled "deterministic mode (no AI)"
read    : 3 of 3 PDFs (text layer) — the PNG is reported as not analysed
PDF     : HTTP 200, 9,571 bytes
```

### 9.3 PDF output

Three pages, deterministic: header with draft banner, claim particulars
grid, patient, insurance, treatment, itemised charges with a total row, and
reviewer notes. Every page carries the draft disclaimer.

### 9.4 Frontend build

```
✓ 41 modules transformed
dist/index.html                 0.43 kB
dist/assets/index-*.css        12.17 kB │ gzip:  3.62 kB
dist/assets/index-*.js        174.49 kB │ gzip: 54.55 kB
✓ built in 2.71s
```

### 9.5 Defects found and fixed during verification

Testing against the live API and real models was what surfaced most of these;
the offline path had hidden them.

| # | Defect | Fix |
|---|---|---|
| 1 | `AttributeError: 'str' has no attribute 'diagnosis'` — nested paths applied to a flat dict | route through `_attr_for` |
| 2 | 11 unmapped nested paths wrote an empty-string key | completed the path map; reject empty paths |
| 3 | Line items became dicts, then crashed validation | coerce to `LineItem` at the boundary |
| 4 | Nothing readable extracted from any PDF | taught the reader label/value, wrapped-prose and pipe-separated forms |
| 5 | `icd_code = "PRESENTINGCOMPLAINT"`; hospital phone read as patient phone | anchored the pattern; bare `Phone` is a hospital field |
| 6 | `LayoutError: too large on page 1` | frame-aware width, splittable tables, fresh story per pass |
| 7 | Dashboard list had no `claim_id` | added to the summary model |
| 8 | `2.5-flash`/`2.5-pro` retired → 404 on every call | moved defaults to the 3.x generation |
| 9 | Health check reported "connected" while all calls 404'd | probe the configured models for real |
| 10 | Retired model retried 3× with zero delay | error classification + backoff |
| 11 | Quota error destroyed completed AI work | graceful degradation, disclosed |
| 12 | `documents_seen` always empty ("read 0 documents") | stale snapshot was clobbering the list |
| 13 | Discharge summary and policy both typed "insurance card" | scored detection, filename weighted 3× |
| 14 | Deleting a claim flashed a 404 | skip the refresh for a deleted claim |
| 15 | Stage status `completed` rendered as blank | backend uses `completed`, UI expected `done` |
| 16 | Health polling spent model quota | cache the probe for 5 minutes |
| 17 | Free-tier wake time caused overlapping polls | in-flight guard |

---

## 10. Report — conclusion

### 10.1 What was delivered

A working multi-agent claim drafting system: six specialised agents, a
multimodal Gemini integration, a deterministic PDF renderer, a polished React
UI, an end-to-end test, and deployment configuration for Render and Vercel.

### 10.2 What was learned

1. **The deterministic path is not a fallback, it is insurance.** Building the
   rule engine first is what made degradation possible at all, and what made
   the project testable without an API key.
2. **Optimism about external services is expensive.** The retired models, the
   false health check and the quota outage were all invisible until real calls
   were made. Live verification is not optional.
3. **A truthful failure beats a comfortable one.** "Deterministic mode (no AI)"
   on a stage, with a banner, is more useful than a green tick that hides the
   model was never called.
4. **Structure carries resilience.** Because agents pass a record rather than
   talking to each other, any stage can fail without losing the others' work.

### 10.3 Limitations

- Gemini paths are verified on `gemini-3.8-flash` only; the reasoning-stage pro
  option is configured but unverified on this key.
- Quota on the test key is exhausted, so sustained multi-run testing was not
  possible.
- Storage is JSON on local disk — ephemeral on Render's free tier.
- No authentication: the deployed URL is open to anyone.
- Only English, and only the four sample document layouts.

### 10.4 Recommended next steps

1. Add authentication before handling real patient data.
2. Replace JSON files with Postgres and object storage for durable claims.
3. Add a regression test for the document-type classifier, which is the most
   heuristic component.
4. Add Playwright end-to-end tests to replace manual UI verification.
5. Re-verify the pro reasoning model once quota allows.

### 10.5 Safety statement

MediClaim produces a **draft**. It performs no medical assessment, approves no
claim, and must not be treated as a source of truth. Every generated field
requires verification by an authorised human against the original records
before submission to an insurer.
