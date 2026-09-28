import { Empty } from './Primitives.jsx'

const pretty = (path) =>
  String(path || '')
    .split('.')
    .filter(Boolean)
    .map((part) => part.replace(/_/g, ' '))
    .join(' › ')

function Issues({ title, issues, tone }) {
  if (!issues?.length) return null
  return (
    <div style={{ marginTop: 12 }}>
      <p className="tiny muted" style={{ margin: '0 0 6px', fontWeight: 700 }}>
        {title} ({issues.length})
      </p>
      {issues.map((issue, index) => (
        <div className={`issue ${issue.severity || tone}`} key={index}>
          {issue.field ? <b>{pretty(issue.field)}</b> : null}
          <div>{issue.message}</div>
          {issue.suggestion ? (
            <div className="muted" style={{ marginTop: 3 }}>
              {issue.suggestion}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  )
}

/** Validation output: what is missing, what conflicts, what is merely optional. */
export default function ValidationPanel({ claim }) {
  const result = claim?.validation
  if (!result) {
    return (
      <div className="card">
        <header>
          <h2>Validation</h2>
        </header>
        <Empty>Nothing validated yet.</Empty>
      </div>
    )
  }

  return (
    <div className="card">
      <header>
        <h2>Validation</h2>
        <span className="spacer" style={{ flex: 1 }} />
        <span className={`pill ${result.valid ? 'ready_for_review' : 'needs_input'}`}>
          {result.valid ? 'required fields complete' : 'action needed'}
        </span>
        <span className="tiny muted">{result.checked_fields} fields checked</span>
      </header>
      <div className="body">
        {result.missing_required?.length ? (
          <div>
            <p className="tiny muted" style={{ margin: '0 0 6px', fontWeight: 700, color: '#b45309' }}>
              REQUIRED FIELDS STILL MISSING ({result.missing_required.length})
            </p>
            <div className="issue warning">
              {result.missing_required.map((path) => (
                <div key={path}>
                  <b>{pretty(path)}</b>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {result.missing_optional?.length ? (
          <div>
            <p className="tiny muted" style={{ margin: '12px 0 6px', fontWeight: 700 }}>
              OPTIONAL, NOT SUPPLIED ({result.missing_optional.length})
            </p>
            <p className="tiny muted" style={{ margin: 0 }}>
              {result.missing_optional.map(pretty).join(' · ')}
            </p>
          </div>
        ) : null}

        <Issues title="INCONSISTENCIES" issues={result.inconsistencies} tone="error" />
        <Issues title="WARNINGS" issues={result.warnings} tone="warning" />

        {result.valid &&
        !result.inconsistencies?.length &&
        !result.warnings?.length &&
        !result.missing_required?.length ? (
          <p className="tiny muted" style={{ margin: 0 }}>
            No problems found.
          </p>
        ) : null}
      </div>
    </div>
  )
}
