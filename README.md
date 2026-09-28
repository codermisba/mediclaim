# MediClaim · ClaimGen AI

A multi-agent, multimodal insurance-claim drafting application.

You upload the documents you already have (hospital bill, discharge summary, policy
schedule, insurance card photo) and a pipeline of specialised agents reads them,
normalises what they find, checks it against what is required, and drafts a
claim form you can download as a PDF.

**MediClaim produces a DRAFT. It does not give medical, clinical or insurance
advice, and it does not approve, reject or adjudicate any claim.** An authorised
person must verify every field against the original records before submission.

---

## 1. Where to put your API key

The key lives in a single file at the project root:

```
E:\WEB\mediclaim\claimgen-ai-solo\.env
```

Create it from the template:

```powershell
cd E:\WEB\mediclaim\claimgen-ai-solo
copy .env.example .env
```

Then open `.env` and replace the placeholder with your real key:

```env
GEMINI_API_KEY=PASTE_YOUR_REAL_KEY_HERE
```

Get a key from https://aistudio.google.com/apikey

- Never commit a real key; `.gitignore` already excludes `.env`.
- The backend also auto-loads `backend/.env` if you would rather keep it local.
- **Leaving the key blank is supported.** The app then runs in clearly labelled
  `offline_deterministic` mode: no AI calls are made, and the deterministic
  fallback reads the embedded text layer of PDFs only (see section 7).

---

## 2. Requirements

- Python 3.11 or newer (3.12 tested)
- Node.js 18 or newer (22 tested)

---

## 3. Start the backend

```powershell
cd E:\WEB\mediclaim\claimgen-ai-solo\backend

# create the environment (once)
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# install dependencies
py -m pip install --upgrade pip
py -m pip install -r requirements.txt

# run it
py -m uvicorn main:app --reload
```

The API is now on **http://127.0.0.1:8000** and the docs at
**http://127.0.0.1:8000/docs**.

> **If port 8000 is already in use** (another dev server, or a leftover process
> from a previous session) the backend exits with
> `WinError 10013 - an attempt was made to access a socket in a way forbidden by
> its access permissions`. Pick another port and tell the frontend about it in
> `frontend/.env.local`:
>
> ```powershell
> py -m uvicorn main:app --reload --port 8020
> ```
> ```ini
> # frontend/.env.local
> BACKEND_URL=http://127.0.0.1:8020
> FRONTEND_PORT=5173
> ```
>
> To see what is holding a port:
> `Get-NetTCPConnection -State Listen -LocalPort 8000`

---

## 4. Start the frontend

In a second terminal:

```powershell
cd E:\WEB\mediclaim\claimgen-ai-solo\frontend
npm install
npm run dev
```

Open **http://localhost:5173**.

Vite proxies every `/api` call to the backend, so the browser only makes
same-origin requests. Put `BACKEND_URL` in `frontend/.env.local` (or set
`$env:BACKEND_URL` in the shell) if your backend is not on port 8000. These
values configure the dev server only and are never bundled into the browser
build.

---

## 5. Try it in 30 seconds

1. Open http://localhost:5173
2. Leave **Use sample data** selected and press **Create claim**.
   Four realistic documents are generated on the fly and attached.
3. Press **Run full pipeline**. The six stages stream live.
4. When it finishes you get the merged claim data, the validation result, the
   generated claim and the final review.
5. Press **Download PDF** for a deterministic, paginated claim form.

---

## 6. How it works

Six sequential stages, each with one responsibility. They exchange **structured
JSON only** - no stage is allowed to read another stage's reasoning.

| # | Stage | Agent | What it does |
|---|-------|-------|--------------|
| 0 | Input | `input_agent` | Normalises and counts what you supplied. Invents nothing. |
| 1 | Document analysis | `document_agent` | Reads the multimodal documents (PDF text, images, scans) and reports what each one is. |
| 2 | Extraction | `extraction_agent` | Merges typed details with document details, resolving conflicts field by field and flagging anything uncertain. |
| 3 | Validation | `validation_agent` | Checks required fields, internal consistency, dates, totals and identifiers. |
| 4 | Generation | `generation_agent` | Builds the claim payload the renderer consumes. |
| 5 | Review | `review_agent` | Compares the draft back against the source and lists what a human must confirm. |

Design rules that are enforced in code:

- **The model never controls the PDF layout.** It only fills structured fields;
  ReportLab renders the document deterministically, so the same claim always
  produces the same form.
- **Nothing is ever guessed to fill a gap.** A blank stays blank and is reported
  as missing, so the pipeline can stop with `needs_input`.
- **No medical or clinical judgement** is made, and no claim is ever approved.
- Each stage reports `used_ai` so you can always see what came from Gemini and
  what came from the deterministic fallback.

---

## 7. Running without an API key

If `GEMINI_API_KEY` is unset the app says so in the UI and every stage is marked
`warning`. It then:

- reads only the **embedded text layer** of PDFs (via `pypdf`);
- never reads images or scanned pages, and says so rather than guessing;
- produces a fully working demo end to end, including the PDF.

This mode exists so the project is testable and reviewable without spending
tokens. It is not a replacement for the model. To use it even when a key is
present, set `FORCE_OFFLINE=1` in `.env`.

---

## 7a. Models, quotas and outages

Gemini model names change and retire, and free-tier keys run out of quota.
Three things keep that from turning into a dead end:

1. **`/api/health` actually calls your models.** A key being accepted proves
   nothing - a retired model name still authenticates - so the health endpoint
   sends one tiny request per configured model and reports `status: degraded`
   with a per-model reason when one cannot be used.

   ```powershell
   Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 5
   ```

2. **The error says which kind of problem it is.** Failures are classified as
   `auth` (bad key), `model` (retired or not enabled), `quota` (exhausted or
   rate limited), `overloaded` (transient 503), or `content`. Only transient
   classes are retried, and only they get exponential backoff, so a retired
   model fails in one call instead of three.

3. **A quota outage does not throw away completed work.** Every agent computes
   its deterministic result *before* calling the model, so if the model is
   momentarily unavailable that stage falls back to it, is marked `warning`, and
   a banner explains why. The document analysis Gemini already finished is not
   lost. A retired model or a bad key still fails loudly, because hiding those
   would hide a bug you need to fix.

> The 2.5 models (`gemini-2.5-flash`, `gemini-2.5-pro`) have been **retired**
> and now fail with `404 NOT_FOUND` on new keys. The defaults are the 3.x
> generation (`gemini-3.8-flash`); override with the `GEMINI_MODEL_*` values.

---

## 8. Layout

```
claimgen-ai-solo/
├─ .env.example              copy to .env and add your key here
├─ backend/
│  ├─ main.py                FastAPI app and all routes
│  ├─ config.py              environment-driven settings
│  ├─ models/schemas.py      Pydantic contracts for every agent and the API
│  ├─ agents/                the six pipeline agents
│  ├─ services/
│  │  ├─ pipeline.py         stage orchestration
│  │  ├─ gemini.py           Gemini client, retries, schema handling
│  │  ├─ offline.py          deterministic fallback reader
│  │  ├─ normalize.py        dates, amounts, identifiers, paths
│  │  ├─ pdf_generator.py    deterministic ReportLab claim form
│  │  ├─ sample_data.py      generated demo documents
│  │  └─ store.py            persistence and uploads
│  ├─ _smoke_test.py         end-to-end backend check
│  └─ data/                  claims, uploads and generated samples
└─ frontend/                 React + Vite UI
```

---

## 9. Useful commands

```powershell
# backend end-to-end check (no server needed)
cd backend
py _smoke_test.py

# production frontend build
cd frontend
npm run build
```

---

## 10. Configuration reference

All settings live in `.env`; see `.env.example` for the full list.

| Variable | Default | Purpose |
|----------|---------|---------|
| `GEMINI_API_KEY` | - | Your key. Blank means offline mode. |
| `GEMINI_MODEL_EXTRACTION` | `gemini-3.8-flash` | Document reading and extraction. |
| `GEMINI_MODEL_REASONING` | `gemini-3.8-flash` | Where judgement genuinely helps. |
| `GEMINI_MODEL_REVIEW` | `gemini-3.8-flash` | Final field-by-field comparison. |
| `GEMINI_TEMPERATURE_*` | `0.0` / `0.1` | Low on purpose: this is data entry. |
| `FORCE_OFFLINE` | `0` | Set `1` to ignore the key and run deterministically. |
| `MAX_UPLOAD_MB` | `20` | Per-file upload cap. |
| `MAX_DOCUMENTS_PER_CLAIM` | `10` | Document cap per claim. |
| `CORS_ORIGINS` | localhost:5173 | Allowed browser origins. |
| `PERSIST_CLAIMS` | `true` | Set `false` to keep everything in memory. |

---

## 11. Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| Backend exits with `WinError 10013` on startup | Port 8000 is owned by another process. Use `--port 8020` and set `BACKEND_URL` in `frontend/.env.local`. |
| Frontend shows network errors | The backend is not running, or `BACKEND_URL` points at the wrong port. |
| `Gemini is only partly available` banner | `/api/health` lists the failing model and the reason. Usually a retired model name or an exhausted quota. |
| `404 NOT_FOUND ... no longer available` | That model is retired. Move to the 3.x names in `.env` and restart. |
| `Gemini quota exhausted` | The key is out of quota or rate limited. Wait for the window to reset, use another model, or set `FORCE_OFFLINE=1`. |
| Stage shows `warning` + "deterministic mode (no AI)" | Either no key, or Gemini was unreachable for that stage. Expected and disclosed, not a crash. |
| Banner says "offline deterministic mode" | `GEMINI_API_KEY` is blank or `.env` was not saved. Restart the backend. |
| Upload rejected | The file is over `MAX_UPLOAD_MB`, there are already 10 documents, or the type is unsupported. |
#   m e d i c l a i m  
 