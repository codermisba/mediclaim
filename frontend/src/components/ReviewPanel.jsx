import { Empty } from './Primitives.jsx'

/** Final review: the model's verdict plus everything a human must confirm. */
export default function ReviewPanel({ claim }) {
  const review = claim?.review
  if (!review) {
    return (
      <div className="card">
        <header>
          <h2>Final review</h2>
        </header>
        <Empty>No review yet.</Empty>
      </div>
    )
  }

  const ready = review.status === 'READY_FOR_REVIEW'

  return (
    <div className="card">
      <header>
        <h2>Final review</h2>
        <span className="spacer" style={{ flex: 1 }} />
        <span className={`pill ${ready ? 'ready_for_review' : 'error'}`}>
          {String(review.status).replace(/_/g, ' ')}
        </span>
        <span className="tiny muted">{review.checked_fields} fields compared</span>
      </header>
      <div className="body">
        <p style={{ marginTop: 0 }}>{review.summary}</p>

        {review.issues?.length ? (
          review.issues.map((issue, index) => (
            <div className={`issue ${issue.severity || 'info'}`} key={index}>
              {issue.field ? <b>{String(issue.field).replace(/[>]/g, ' › ')}</b> : null}
              <div>{issue.message}</div>
              {issue.suggestion ? (
                <div className="muted" style={{ marginTop: 3 }}>
                  {issue.suggestion}
                </div>
              ) : null}
            </div>
          ))
        ) : (
          <p className="tiny muted" style={{ margin: 0 }}>
            Nothing outstanding.
          </p>
        )}

        <div className="notice" style={{ marginTop: 13, marginBottom: 0 }}>
          <b>Before you submit this claim:</b> check every field against the original medical
          records, prescriptions and receipts. A person must review and sign the final form.
        </div>
      </div>
    </div>
  )
}
