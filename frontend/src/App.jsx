import { useCallback, useEffect, useRef, useState } from 'react'
import api from './api.js'
import NewClaimForm from './components/NewClaimForm.jsx'
import DocumentPanel from './components/DocumentPanel.jsx'
import PipelineStages from './components/PipelineStages.jsx'
import ClaimDataPanel from './components/ClaimDataPanel.jsx'
import ValidationPanel from './components/ValidationPanel.jsx'
import GeneratedPanel from './components/GeneratedPanel.jsx'
import ReviewPanel from './components/ReviewPanel.jsx'
import ClaimOverview from './components/ClaimOverview.jsx'
import { Empty, ErrorBanner, Money, NoticeBanner, Pill } from './components/Primitives.jsx'

const POLL_MS = 1200
const LIVE = ['processing']

export default function App() {
  const [health, setHealth] = useState(null)
  const [claims, setClaims] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [claim, setClaim] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)
  const timer = useRef(null)
  // A free-tier host can take ~50s to wake, which is far longer than POLL_MS.
  // Without this guard, overlapping polls pile up and hammer the API.
  const inFlight = useRef(false)

  const refreshList = useCallback(async () => {
    try {
      const listing = await api.listClaims()
      setClaims(listing.claims ?? [])
      return listing
    } catch (err) {
      setError(err)
      return null
    }
  }, [])

  const refreshClaim = useCallback(async (id) => {
    try {
      const detail = await api.getClaim(id)
      setClaim(detail)
      return detail
    } catch (err) {
      setError(err)
      return null
    }
  }, [])

  // Poll the open claim while its pipeline is still running.
  useEffect(() => {
    clearInterval(timer.current)
    if (!activeId) return undefined
    if (claim && !LIVE.includes(claim.status)) return undefined
    timer.current = setInterval(async () => {
      if (inFlight.current) return
      inFlight.current = true
      try {
        const detail = await refreshClaim(activeId)
        if (detail && !LIVE.includes(detail.status)) {
          await refreshList()
        }
      } finally {
        inFlight.current = false
      }
    }, POLL_MS)
    return () => clearInterval(timer.current)
  }, [activeId, claim?.status, refreshClaim, refreshList])

  // Load once on mount, then re-check periodically: a quota window opening
  // should clear the "partially unavailable" banner without a page reload.
  // The backend caches its model probe for 5 minutes, so this is cheap.
  useEffect(() => {
    let cancelled = false
    const check = async () => {
      try {
        const status = await api.health()
        if (!cancelled) setHealth(status)
      } catch (err) {
        if (!cancelled) setError(err)
      }
    }
    check()
    const id = setInterval(check, 120000)
    refreshList()
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [refreshList])

  async function select(id) {
    setActiveId(id)
    await refreshClaim(id)
  }

  async function act(name, fn, { skipRefresh = false } = {}) {
    setBusy(name)
    setError(null)
    try {
      await fn()
      if (skipRefresh) return null
      const detail = await refreshClaim(activeId)
      await refreshList()
      return detail
    } catch (err) {
      setError(err)
      return null
    } finally {
      setBusy(null)
    }
  }

  async function runPipeline() {
    const detail = await act('process', () => api.process(activeId))
    if (detail) setClaim(detail)
  }

  const aiMode = claim?.ai_mode ?? health?.mode
  const offline = aiMode === 'offline_deterministic'
  const degraded = health?.status === 'degraded'
  const brokenModels = Object.entries(health?.model_checks ?? {}).filter(
    ([, check]) => check.ok !== 'true',
  )

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <h1>
            <span className="logo">M</span>
            MediClaim &middot; ClaimGen AI
          </h1>
          <div className="sub">
            Multi-agent insurance claim drafting &middot; draft output, human verification required
          </div>
        </div>
        <div className="spacer" />
        {health ? (
          <span
            className={`badge ${degraded ? 'off' : offline ? 'off' : 'on'}`}
            title={health.message ?? ''}
          >
            <span className="pip" />
            {degraded
              ? 'Gemini partially unavailable'
              : offline
                ? 'offline deterministic mode'
                : 'Gemini connected'}
          </span>
        ) : null}
        {health?.models ? (
          <span className="badge" title="Model used for extraction and review">
            {health.models.extraction}
          </span>
        ) : null}
      </div>

      {degraded ? (
        <NoticeBanner tone="warning" title="Gemini is only partly available">
          <div>{health.message}</div>
          <ul style={{ margin: '5px 0 0 16px' }}>
            {brokenModels.map(([name, check]) => (
              <li key={name}>
                <b>{name}</b>: {check.hint || check.detail}
              </li>
            ))}
          </ul>
        </NoticeBanner>
      ) : null}
      {claim?.ai_notice ? (
        <NoticeBanner tone="warning" title="Some stages ran without Gemini">
          {claim.ai_notice}
        </NoticeBanner>
      ) : null}

      <div className="layout">
        <div className="sidebar">
          <NewClaimForm
            onCreated={async (id) => {
              await refreshList()
              await select(id)
            }}
            onError={setError}
          />

          <div className="card">
            <header>
              <h2>Claims</h2>
              <span className="spacer" style={{ flex: 1 }} />
              <span className="muted tiny">{claims.length}</span>
            </header>
            {claims.length === 0 ? (
              <Empty>No claims yet.</Empty>
            ) : (
              <ul className="claim-list">
                {claims.map((line) => (
                  <li key={line.claim_id}>
                    <button
                      className={line.claim_id === activeId ? 'active' : ''}
                      onClick={() => select(line.claim_id)}
                    >
                      <span className="t">{line.title || line.claim_number || 'Untitled claim'}</span>
                      <span className="m">
                        <Pill status={line.status} />
                        <span>{line.document_count} docs</span>
                        {line.total_amount ? (
                          <span>
                            <Money amount={line.total_amount} currency={line.currency} />
                          </span>
                        ) : null}
                        {line.missing_count ? <span>{line.missing_count} missing</span> : null}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <main className="content">
          <ErrorBanner error={error} onClose={() => setError(null)} />

          {!claim ? (
            <div className="card">
              <Empty>
                Create a claim from the sample data to watch the agents work, or start your own.
              </Empty>
            </div>
          ) : (
            <>
              <div className="card claim-header">
                <header>
                  <h2>{claim.title}</h2>
                  <Pill status={claim.status} />
                  <span className="spacer" style={{ flex: 1 }} />
                  <span className="tiny muted mono">{claim.claim_id}</span>
                </header>
                <div className="body">
                  {offline ? (
                    <div className="notice">
                      <b>GEMINI_API_KEY is not set, so the agents are running deterministically.</b>
                      They only read the text layer of your PDFs; images and scanned pages are not
                      analysed, and no AI calls are made. Copy <code>.env.example</code> to{' '}
                      <code>.env</code>, add your key, and restart the backend to switch to Gemini.
                    </div>
                  ) : null}

                  <div className="row action-toolbar">
                    <button
                      className="btn primary"
                      disabled={busy !== null}
                      onClick={runPipeline}
                    >
                      {busy === 'process' ? <span className="spinner" /> : null}
                      {claim.status === 'draft' || claim.status === 'error' || claim.status === 'needs_input'
                        ? 'Run full pipeline'
                        : 'Re-run pipeline'}
                    </button>
                    <button
                      className="btn ghost"
                      disabled={busy !== null}
                      onClick={() => act('validate', () => api.validate(claim.claim_id))}
                    >
                      Validate only
                    </button>
                    <button
                      className="btn ghost"
                      disabled={busy !== null}
                      onClick={() => act('generate', () => api.generate(claim.claim_id))}
                    >
                      Generate claim
                    </button>
                    <button
                      className="btn ghost"
                      disabled={busy !== null}
                      onClick={() => act('review', () => api.review(claim.claim_id))}
                    >
                      Review
                    </button>
                    {claim.generated ? (
                      <a className="btn ghost" href={api.pdfUrl(claim.claim_id)} target="_blank" rel="noreferrer">
                        Download PDF
                      </a>
                    ) : null}
                    <span className="spacer" style={{ flex: 1 }} />
                    <button
                      className="btn danger"
                      disabled={busy !== null}
                      onClick={async () => {
                        if (!window.confirm('Delete this claim and its documents?')) return
                        // The claim is gone, so refreshing it would 404 and flash
                        // a spurious error banner.
                        await act(
                          'delete',
                          () => api.deleteClaim(claim.claim_id),
                          { skipRefresh: true },
                        )
                        setClaim(null)
                        setActiveId(null)
                        await refreshList()
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>

              <PipelineStages claim={claim} />
              <DocumentPanel claim={claim} onChanged={() => refreshClaim(claim.claim_id)} onError={setError} />

              {claim.status === 'needs_input' ? (
                <div className="notice">
                  <b>Some required information is missing.</b> Add it to the claim (or upload a
                  document containing it) and run the pipeline again. Nothing is ever guessed to fill
                  a gap.
                </div>
              ) : null}

              <ClaimOverview claim={claim} />

              <ClaimDataPanel claim={claim} />
              <ValidationPanel claim={claim} />
              <GeneratedPanel claim={claim} />
              <ReviewPanel claim={claim} />
            </>
          )}
        </main>
      </div>
      <div className="footer">
        MediClaim &middot; ClaimGen AI {health?.version ? `v${health.version}` : ''} &middot; drafts
        only &mdash; every field must be verified by an authorised human before submission.
      </div>
    </div>
  )
}
