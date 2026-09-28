import { Money } from './Primitives.jsx'

/**
 * At-a-glance metrics for the open claim. Everything here is read straight off
 * the record, so the numbers always agree with the panels below.
 */
export default function ClaimOverview({ claim }) {
  const data = claim.claim_data ?? {}
  const validation = claim.validation
  const generated = claim.generated
  const review = claim.review
  const documents = claim.documents ?? []
  const lineItems = data.billing?.line_items ?? []
  const required = validation?.missing_required?.length ?? 0
  const optional = validation?.missing_optional?.length ?? 0
  const errors = validation?.inconsistencies?.filter((i) => i.severity === 'error') ?? []
  const warnings = validation?.warnings ?? []

  const total = generated?.claim_amount ?? data.billing?.total_amount ?? 0
  const currency = generated?.currency ?? data.billing?.currency ?? 'INR'
  const aiStages = (claim.stages ?? []).filter((s) => s.status === 'completed').length

  return (
    <div className="card">
      <header>
        <h2>Claim overview</h2>
        <span className="spacer" style={{ flex: 1 }} />
        <span className="tiny muted">
          {documents.length} document{documents.length === 1 ? '' : 's'} &middot; {aiStages} stage
          {aiStages === 1 ? '' : 's'} by AI
        </span>
      </header>
      <div className="body">
        <div className="stats">
          <div className="stat">
            <span className="k">Claimed amount</span>
            <span className="v">
              {total ? <Money amount={total} currency={currency} /> : <span className="muted">&mdash;</span>}
            </span>
          </div>
          <div className="stat">
            <span className="k">Patient</span>
            <span className="v sm">{data.patient?.name || <span className="muted">&mdash;</span>}</span>
          </div>
          <div className="stat">
            <span className="k">Line items</span>
            <span className="v">{lineItems.length}</span>
          </div>
          <div className={`stat ${required ? 'bad' : validation ? 'good' : ''}`}>
            <span className="k">Missing required</span>
            <span className="v">{validation ? required : <span className="muted">&mdash;</span>}</span>
          </div>
          <div className={`stat ${errors.length ? 'bad' : ''}`}>
            <span className="k">Blocking issues</span>
            <span className="v">{validation ? errors.length : <span className="muted">&mdash;</span>}</span>
          </div>
          <div className={`stat ${warnings.length + optional ? 'warn' : ''}`}>
            <span className="k">To review</span>
            <span className="v">{validation ? warnings.length + optional : <span className="muted">&mdash;</span>}</span>
          </div>
          <div className="stat">
            <span className="k">Claim number</span>
            <span className="v sm mono">{generated?.claim_number || <span className="muted">&mdash;</span>}</span>
          </div>
          <div className={`stat ${review?.status === 'READY_FOR_REVIEW' ? 'good' : review ? 'warn' : ''}`}>
            <span className="k">Final review</span>
            <span className="v sm">
              {review ? review.status.replace(/_/g, ' ') : <span className="muted">&mdash;</span>}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
