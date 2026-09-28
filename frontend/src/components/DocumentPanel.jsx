import { useRef, useState } from 'react'
import api from '../api.js'
import { Bytes, Empty, ErrorBanner } from './Primitives.jsx'

/** Two-letter badge so a document is recognisable at a glance. */
function kindOf(doc) {
  const name = (doc.filename || '').toLowerCase()
  if (/\.(png|jpe?g|webp|heic)$/.test(name)) return 'IMG'
  if (/bill|invoice/.test(name)) return 'INV'
  if (/discharge|summary/.test(name)) return 'SUM'
  if (/policy/.test(name)) return 'POL'
  if (/card/.test(name)) return 'CRD'
  return 'DOC'
}

/** Upload / remove the supporting documents for a claim. */
export default function DocumentPanel({ claim, onChanged, onError }) {
  const inputRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const documents = claim?.documents ?? []

  async function upload(files) {
    if (!files?.length) return
    setBusy(true)
    setError(null)
    try {
      await api.upload(claim.claim_id, files)
      onChanged()
    } catch (err) {
      setError(err)
      onError?.(err)
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function remove(documentId) {
    setBusy(true)
    setError(null)
    try {
      await api.deleteDocument(claim.claim_id, documentId)
      onChanged()
    } catch (err) {
      setError(err)
      onError?.(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <header>
        <h2>Documents</h2>
        <span className="muted tiny">{documents.length} attached</span>
        <div className="spacer" style={{ flex: 1 }} />
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,.webp,.heic"
          style={{ display: 'none' }}
          onChange={(e) => upload(e.target.files)}
        />
        <button
          className="btn ghost sm"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? <span className="spinner" /> : null} Add files
        </button>
      </header>
      <div className="body">
        <ErrorBanner error={error} onClose={() => setError(null)} />
        {documents.length === 0 ? (
          <Empty>No documents yet. Add the hospital bill, discharge summary and policy schedule.</Empty>
        ) : (
          <ul className="docs">
            {documents.map((doc) => (
              <li key={doc.document_id}>
                <span className="icon">{kindOf(doc)}</span>
                <span className="name">
                  {doc.filename}
                  {doc.detected_type ? (
                    <span className="tiny muted"> &middot; {doc.detected_type}</span>
                  ) : null}
                </span>
                <span className="size">{Bytes(doc.size_bytes)}</span>
                <button
                  className="btn danger sm"
                  disabled={busy}
                  onClick={() => remove(doc.document_id)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <p className="tiny muted" style={{ margin: '10px 0 0' }}>
          PDF, PNG, JPG, WEBP or HEIC. Scanned documents are read by the model directly; no text
          layer is required.
        </p>
      </div>
    </div>
  )
}
