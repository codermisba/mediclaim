// In development the base is empty, so every call is same-origin and Vite's
// proxy forwards it to the backend. In production VITE_API_BASE is set to the
// deployed API origin (Render) and the same code needs no changes.
const API = import.meta.env.VITE_API_BASE || ''

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...options,
  })
  const text = await response.text()
  let body = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }
  if (!response.ok) {
    // The backend wraps failures as { error: { detail, code, hint, kind } }.
    const detail = body?.error?.detail ?? body?.detail ?? body
    const message = typeof detail === 'string' ? detail : detail?.message ?? 'Request failed'
    const error = new Error(message)
    error.status = response.status
    error.hint = body?.error?.hint
    error.code = body?.error?.code
    error.kind = body?.error?.kind
    error.model = body?.error?.model
    throw error
  }
  return body
}

export const api = {
  health: () => request('/api/health'),
  config: () => request('/api/config'),
  listClaims: () => request('/api/claims'),
  // The detail endpoint wraps the record: { claim_id, pipeline_running, claim }.
  getClaim: async (id) => {
    const data = await request(`/api/claim/${id}`)
    return { ...data.claim, pipeline_running: data.pipeline_running }
  },
  sample: () => request('/api/claims/sample'),
  createClaim: (payload) =>
    request('/api/claim/create', { method: 'POST', body: JSON.stringify(payload) }),
  updateClaim: (id, payload) =>
    request(`/api/claim/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteClaim: (id) => request(`/api/claim/${id}`, { method: 'DELETE' }),
  upload: (id, files) => {
    const form = new FormData()
    Array.from(files).forEach((file) => form.append('files', file))
    return request(`/api/claim/upload?claim_id=${encodeURIComponent(id)}`, {
      method: 'POST',
      body: form,
    })
  },
  deleteDocument: (claimId, docId) =>
    request(`/api/claim/upload/${claimId}/${docId}`, { method: 'DELETE' }),
  process: (id) => request('/api/claim/process', { method: 'POST', body: JSON.stringify({ claim_id: id }) }),
  validate: (id) => request('/api/claim/validate', { method: 'POST', body: JSON.stringify({ claim_id: id }) }),
  generate: (id) => request('/api/claim/generate', { method: 'POST', body: JSON.stringify({ claim_id: id }) }),
  review: (id) => request('/api/claim/review', { method: 'POST', body: JSON.stringify({ claim_id: id }) }),
  pdfUrl: (id) => `${API}/api/claim/${id}/pdf`,
}

export default api
