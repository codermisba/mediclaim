export function Pill({ status }) {
  return <span className={`pill ${status || 'draft'}`}>{String(status || 'draft').replace(/_/g, ' ')}</span>
}

const MARK = {
  completed: '✓',
  failed: '!',
  warning: '!',
  processing: '',
  pending: '',
  skipped: '–',
}

export function StageIcon({ status }) {
  return <span className={`dot ${status || 'pending'}`}>{MARK[status] ?? ''}</span>
}

export function Field({ label, value, mono }) {
  const empty = value === null || value === undefined || value === ''
  return (
    <>
      <dt>{label}</dt>
      <dd className={empty ? 'none' : mono ? 'mono' : undefined}>
        {empty ? 'Not provided' : String(value)}
      </dd>
    </>
  )
}

export function Money({ amount, currency }) {
  const value = Number(amount || 0)
  const formatted = value.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return (
    <>
      {currency || 'INR'} {formatted}
    </>
  )
}

export function Bytes({ value }) {
  const n = Number(value || 0)
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function ErrorBanner({ error, onClose }) {
  if (!error) return null
  return (
    <div className="notice error">
      <b>{error.message}</b>
      {error.hint ? <div style={{ marginTop: 3 }}>{error.hint}</div> : null}
      {onClose ? (
        <button className="btn ghost sm" style={{ marginTop: 7 }} onClick={onClose}>
          Dismiss
        </button>
      ) : null}
    </div>
  )
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>
}

export function NoticeBanner({ tone = 'warning', title, children, onClose }) {
  return (
    <div className={`notice ${tone}`}>
      {title ? <b>{title}</b> : null}
      {children ? <div style={{ marginTop: title ? 3 : 0 }}>{children}</div> : null}
      {onClose ? (
        <button className="btn ghost sm" style={{ marginTop: 7 }} onClick={onClose}>
          Dismiss
        </button>
      ) : null}
    </div>
  )
}
