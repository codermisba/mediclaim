# Deployment guide — Render (backend) + Vercel (frontend)

Deploy the API to **Render** and the UI to **Vercel**. Everything needed is
already in this repository:

| Piece | File | What it does |
|-------|------|--------------|
| Backend blueprint | `render.yaml` | Python service, health check, env vars |
| Frontend config | `frontend/vercel.json` | Vite build, SPA rewrites, asset caching |
| Frontend env template | `frontend/.env.example` | `VITE_API_BASE` |

---

## 0. Push the code to GitHub

Both Render and Vercel deploy from a Git repository, so this comes first.

```powershell
cd E:\WEB\mediclaim\claimgen-ai-solo
git init
git add .
git commit -m "MediClaim / ClaimGen AI: multi-agent claim drafting app"
gh repo create mediclaim-claimgen --private --source . --push
```

`.gitignore` already excludes `.env`, `.env.local`, `node_modules`, `dist`,
`.venv`, `__pycache__` and `backend/data/**`, so **your Gemini key is not
committed**. Double-check before pushing:

```powershell
git ls-files | Select-String "\.env$"   # must return nothing
```

---

## 1. Backend on Render

1. Render dashboard → **New** → **Blueprint**.
2. Connect the repository you just pushed.
3. Render reads `render.yaml` and creates a service named `mediclaim-api`
   with `rootDir: backend`.
4. Open the service → **Environment** and add:

   | Key | Value |
   |-----|-------|
   | `GEMINI_API_KEY` | *(your real key — this is a secret)* |
   | `CORS_ORIGINS` | `https://<your-vercel-app>.vercel.app` |

   The first deploy runs with the app in deterministic mode until you add the
   key; the UI says so plainly and the pipeline still works end to end.
5. Deploy. When it finishes you get `https://mediclaim-api.onrender.com`.

Check it:

```
https://mediclaim-api.onrender.com/api/live      -> {"status":"ok"}
https://mediclaim-api.onrender.com/api/health    -> full model diagnostics
```

> Use `/api/live` for the platform health check, not `/api/health`.
> `/api/health` deliberately calls your Gemini models, and Render polls the
> health endpoint every minute - that would burn quota for nothing.

### Free-tier caveats (please read)

- **The service sleeps** after ~15 minutes idle. The first request after that
  can take 30-60s while it wakes. The UI handles this: it will not fire
  overlapping polls while a request is in flight.
- **The filesystem is ephemeral.** Uploaded documents and saved claims are lost
  on redeploy or restart. That is fine for a demo. For real use set
  `PERSIST_CLAIMS=false` (stateless) or attach a Render disk / object storage.
- **One worker.** `--workers 1` is deliberate: the pipeline mutates an
  in-process claim record, so multiple workers would each hold their own copy.

---

## 2. Frontend on Vercel

1. Vercel dashboard → **Add New** → **Project** → import the same repository.
2. Set **Root Directory** to `frontend` (important).
3. Framework preset: **Vite**. Build command `npm run build`, output `dist`
   (`vercel.json` already sets both).
4. **Environment Variables** → add:

   | Key | Value |
   |-----|-------|
   | `VITE_API_BASE` | `https://mediclaim-api.onrender.com` |

5. Deploy. You get `https://<your-app>.vercel.app`.

`api.js` reads `VITE_API_BASE`:

```js
const API = import.meta.env.VITE_API_BASE || ''
```

Unset (local dev) it falls back to same-origin requests that Vite proxies. Set
(it, on Vercel) the browser calls the API directly, which is why the backend's
`CORS_ORIGINS` must contain the Vercel URL.

---

## 3. Order matters

Do the backend first so you have the real URL to paste into
`CORS_ORIGINS` and `VITE_API_BASE`. Then redeploy the frontend (or just edit
the env var, which triggers a rebuild).

Final check in the browser: the badge in the top right should read
**Gemini connected** and the console should show no CORS errors.

---

## 4. Rolling back

Render: **Deploys** → pick a previous build → **Rollback**.
Vercel: **Deployments** → ⋯ → **Promote to Production**.

---

## 5. What is *not* covered

- **Authentication.** Anyone who can reach the deployed URL can create claims.
  Add auth before putting real patient data in it.
- **Database.** Claims are JSON files on local disk (ephemeral on Render).
- **File scanning / antivirus.** Uploads are size- and type-checked only.
- **Compliance.** This drafts claims; it does not adjudicate them. A qualified
  human must verify every field. Do not treat it as a source of truth.
