import { StageIcon } from './Primitives.jsx'

const ORDER = ['input', 'document_analysis', 'extraction', 'validation', 'generation', 'review']

const FALLBACK = {
  input: 'Checking what you supplied',
  document_analysis: 'Reading the uploaded documents',
  extraction: 'Pulling fields out of the documents',
  validation: 'Checking required fields and consistency',
  generation: 'Building the structured claim form',
  review: 'Comparing the claim against its source data',
}

const SETTLED = new Set(['completed', 'warning', 'skipped'])

/** Live pipeline progress: a bar plus a connected stage timeline. */
export default function PipelineStages({ claim }) {
  const stages = claim?.stages ?? []
  const byKey = Object.fromEntries(stages.map((s) => [s.key, s]))
  const running = stages.some((s) => s.status === 'processing')
  const offlineMode = claim?.ai_mode === 'offline_deterministic'
  const done = ORDER.filter((key) => SETTLED.has(byKey[key]?.status)).length
  const pct = Math.round((done / ORDER.length) * 100)

  return (
    <div className="card">
      <header>
        <h2>Agent pipeline</h2>
        <span className="spacer" style={{ flex: 1 }} />
        {running ? (
          <span className="tiny muted" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="spinner" /> running
          </span>
        ) : null}
        <span className="tiny muted" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {done}/{ORDER.length} stages
        </span>
      </header>
      <div className="body">
        <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <i style={{ width: `${pct}%` }} />
        </div>
        {offlineMode ? (
          <p className="tiny muted" style={{ margin: '0 0 12px' }}>
            Stages marked <span className="pill warning">warning</span> ran without Gemini, so their
            results came from the deterministic fallback rather than the model.
          </p>
        ) : null}
        {stages.length === 0 ? (
          <div className="stack" aria-hidden="true">
            <div className="skeleton" style={{ width: '55%' }} />
            <div className="skeleton" style={{ width: '75%' }} />
            <div className="skeleton" style={{ width: '62%' }} />
          </div>
        ) : (
          <ul className="stages">
            {ORDER.map((key) => {
              const stage = byKey[key]
              const status = stage?.status ?? 'pending'
              return (
                <li key={key} className={status === 'completed' ? 'done' : undefined}>
                  <StageIcon status={status} />
                  <div>
                    <div className="name">
                      {stage?.label ?? key}
                      {stage?.agent ? (
                        <span className="tiny muted" style={{ fontWeight: 500 }}>
                          {' '}
                          &middot; {stage.agent}
                        </span>
                      ) : null}
                    </div>
                    <div className="msg">{stage?.message || FALLBACK[key]}</div>
                    {stage?.detail ? <div className="msg tiny detail">{stage.detail}</div> : null}
                  </div>
                  <span className="time">
                    {stage?.duration_ms ? `${(stage.duration_ms / 1000).toFixed(1)}s` : ''}
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
