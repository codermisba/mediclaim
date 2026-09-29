# Deploy MediClaim: Render (backend) + Vercel (frontend)

Two services, one repository. This repo already contains `render.yaml` and
`frontend/vercel.json`, so most of the setup is reading and clicking.

| | Service | Root directory | Source |
|---|---|---|---|
| Backend | `mediclaim-api` on **Render** | `backend` | `render.yaml` |
| Frontend | Vercel project | `frontend` | `frontend/vercel.json` |

**Order matters:** deploy the backend first so you have its URL to give Vercel.

---

## 0. Push the code

```powershell
cd E:\WEB\mediclaim\claimgen-ai-solo

git add .
git status                      # review before committing
git commit -m "Switch to Hugging Face provider, add landing page"
git push origin main
```

**Secrets check before every push** - `.env` must never be tracked:

```powershell
git ls-files | findstr /i ".env"     # must print nothing except .env.example
```

---

## 1. Backend on Render

1. **render.com** → **New** → **Blueprint** → connect this GitHub repo
   (`codermisba/mediclaim`).
2. Render reads `render.yaml` and creates a web service with
   `rootDir: backend`, Python 3.12 and health check `/api/live`.
3. Open the service → **Environment** → add:

   | Key | Value | Notes |
   |---|---|---|
   | `HF_TOKEN` | `hf_...` | **Secret.** Create at <https://huggingface.co/settings/tokens> - *Fine-grained*, **Read** access. |
   | `CORS_ORIGINS` | `https://your-app.vercel.app` | No trailing slash. Exact match to what the browser sends. |

   Everything else (provider, models, limits) already comes from `render.yaml`.
4. **Deploy**. First build takes ~2 minutes.

Verify:

```
https://mediclaim-2aov.onrender.com/api/live    -> {"status":"ok"}
https://mediclaim-2aov.onrender.com/api/health  -> "mode": "huggingface", "status": "ok"
```

> Use **`/api/live`** for Render's health check, never `/api/health`.
> `/api/health` makes a real model request to prove the model works; Render polls
> health every minute, which would burn your free-tier rate limit for nothing.

### If `/api/health` says degraded

The response names the failing model and the fix. Typical cases:

| Message | Fix |
|---|---|
| `HF rejected the token` | Regenerate the token; set it in Render → Environment → **Env Variables**, not in `render.yaml`. |
| `model is not available` | Change `HF_MODEL_EXTRACTION` / `_REASONING` / `_REVIEW` in `render.yaml` and redeploy. |
| `rate limiting this token` | Switch to a less busy model, or wait. |

### Free-tier caveats

- **Sleeps after ~15 min idle.** First request after that can take 30-60s.
  The UI guards against overlapping polls during wake-up.
- **Ephemeral disk.** Uploads and saved claims vanish on restart/redeploy. Set
  `PERSIST_CLAIMS=false` for stateless, or attach a Render disk for real use.
- **One worker.** `--workers 1` is deliberate - the pipeline mutates an
  in-process claim record.

---

## 2. Frontend on Vercel

1. **vercel.com** → **Add New** → **Project** → import `codermisba/mediclaim`.
2. **Root Directory** = `frontend` ← this is the step people miss.
3. Framework preset **Vite**. Vercel reads `frontend/vercel.json`, so build
   command `npm run build` and output `dist` are already correct.
4. **Settings → Environment Variables**:

   | Key | Value |
   |---|---|
   | `VITE_API_BASE` | `https://mediclaim-2aov.onrender.com` |

5. **Deploy.**

`frontend/src/api.js` resolves the API like this:

```js
const API = import.meta.env.VITE_API_BASE || ''
```

Unset (local dev) → same-origin requests, proxied by Vite to
`BACKEND_URL` in `frontend/.env.local`.
Set (Vercel) → the browser calls Render directly, which is why `CORS_ORIGINS`
must contain the Vercel origin.

> `VITE_API_BASE` is a **build-time** variable. Changing it requires a redeploy
> of the frontend, not just a save.

---

## 3. Final wiring

After both are up:

1. Render → Environment → set `CORS_ORIGINS=https://your-app.vercel.app` → **Save** (auto-redeploys).
2. Vercel → Environment Variables → confirm `VITE_API_BASE` → **Redeploy**.
3. Open the Vercel URL. The top-right badge should read **Hugging Face connected**,
   and DevTools → Console should show no CORS errors.

Local development stays unchanged: backend `8080`, frontend `5174`, Vite proxy
handles the API path.

---

## 4. Rollback

- **Render**: Deploys → pick a previous build → **Rollback**.
- **Vercel**: Deployments → ⋯ → **Promote to Production**.

---

## 5. What this deployment does *not* include

- **Auth.** Anyone with the URL can create claims. Add auth before real patient data.
- **Durable storage.** Claims are JSON on an ephemeral filesystem.
- **File scanning.** Uploads are size- and type-checked only.
- **Compliance.** This drafts claims; it does not adjudicate them.
