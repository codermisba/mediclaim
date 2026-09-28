import { useState } from 'react'
import api from '../api.js'
import { ErrorBanner } from './Primitives.jsx'

const BLANK = {
  patient: { name: '', date_of_birth: '', gender: '', phone: '', email: '', address: '' },
  insurance: { provider: '', policy_number: '', member_id: '', group_number: '', policy_holder: '' },
  hospital: { name: '', address: '', phone: '' },
  doctor: { name: '', registration_number: '', specialization: '' },
  treatment: { diagnosis: '', admission_date: '', discharge_date: '', treatment: '' },
  billing: { total_amount: '', currency: 'INR', invoice_number: '' },
  notes: '',
}

function setIn(obj, group, key, value) {
  return { ...obj, [group]: { ...obj[group], [key]: value } }
}

/** Create-claim form: a sample-data shortcut plus optional typed details. */
export default function NewClaimForm({ onCreated, onError }) {
  const [mode, setMode] = useState('sample')
  const [title, setTitle] = useState('')
  const [form, setForm] = useState(BLANK)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const field = (group, key, label, extra = {}) => (
    <div className="field" key={`${group}.${key}`}>
      <label>{label}</label>
      <input
        value={form[group][key]}
        onChange={(e) => setForm((f) => setIn(f, group, key, e.target.value))}
        {...extra}
      />
    </div>
  )

  const group = (heading, children) => (
    <div>
      <p className="tiny muted" style={{ margin: '0 0 7px', fontWeight: 700, letterSpacing: '0.5px' }}>
        {heading}
      </p>
      <div className="form-grid">{children}</div>
    </div>
  )

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created = await api.createClaim({
        title: mode === 'sample' ? '' : title,
        use_sample_data: mode === 'sample',
        input_data: mode === 'sample' ? {} : form,
      })
      setTitle('')
      setForm(BLANK)
      onCreated(created.claim_id)
    } catch (err) {
      setError(err)
      onError?.(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <header>
        <h2>New claim</h2>
      </header>
      <div className="body">
        <ErrorBanner error={error} onClose={() => setError(null)} />

        <div className="segmented" style={{ marginBottom: 13 }}>
          <button
            type="button"
            className={mode === 'sample' ? 'active' : ''}
            onClick={() => setMode('sample')}
          >
            Use sample data
          </button>
          <button
            type="button"
            className={mode === 'manual' ? 'active' : ''}
            onClick={() => setMode('manual')}
          >
            Enter my own
          </button>
        </div>

        {mode === 'sample' ? (
          <p className="tiny muted" style={{ margin: 0 }}>
            Creates a pre-filled claim with four generated documents (hospital bill, discharge
            summary, policy schedule and an insurance card photo) so you can watch every agent run.
          </p>
        ) : (
          <>
            <div className="field" style={{ marginBottom: 11 }}>
              <label>Claim title</label>
              <input
                value={title}
                placeholder="e.g. Aarav Sharma - appendectomy"
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <div className="stack">
              {group(
                'PATIENT',
                <>
                  {field('patient', 'name', 'Full name')}
                  {field('patient', 'date_of_birth', 'Date of birth', { type: 'date' })}
                  <div className="field">
                    <label>Gender</label>
                    <select
                      value={form.patient.gender}
                      onChange={(e) => setForm((f) => setIn(f, 'patient', 'gender', e.target.value))}
                    >
                      <option value="">Not stated</option>
                      <option>Female</option>
                      <option>Male</option>
                      <option>Other</option>
                    </select>
                  </div>
                  {field('patient', 'phone', 'Phone')}
                  {field('patient', 'email', 'Email', { type: 'email' })}
                  <div className="full">{field('patient', 'address', 'Address')}</div>
                </>,
              )}
              {group(
                'INSURANCE',
                <>
                  {field('insurance', 'provider', 'Provider')}
                  {field('insurance', 'policy_number', 'Policy number')}
                  {field('insurance', 'member_id', 'Member ID')}
                  {field('insurance', 'group_number', 'Group number')}
                </>,
              )}
              {group(
                'HOSPITAL &amp; DOCTOR',
                <>
                  {field('hospital', 'name', 'Hospital name')}
                  {field('hospital', 'phone', 'Hospital phone')}
                  {field('doctor', 'name', 'Doctor name')}
                  {field('doctor', 'registration_number', 'Registration number')}
                  {field('doctor', 'specialization', 'Specialisation')}
                </>,
              )}
              {group(
                'TREATMENT &amp; BILLING',
                <>
                  {field('treatment', 'diagnosis', 'Diagnosis')}
                  {field('treatment', 'admission_date', 'Admission date', { type: 'date' })}
                  {field('treatment', 'discharge_date', 'Discharge date', { type: 'date' })}
                  {field('billing', 'total_amount', 'Total amount', { type: 'number', step: '0.01' })}
                  {field('billing', 'currency', 'Currency')}
                  {field('billing', 'invoice_number', 'Invoice number')}
                  <div className="full">
                    <div className="field">
                      <label>Treatment notes</label>
                      <textarea
                        value={form.treatment.treatment}
                        onChange={(e) =>
                          setForm((f) => setIn(f, 'treatment', 'treatment', e.target.value))
                        }
                      />
                    </div>
                  </div>
                  <div className="full">
                    <div className="field">
                      <label>Anything else we should know?</label>
                      <textarea
                        value={form.notes}
                        onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                      />
                    </div>
                  </div>
                </>,
              )}
            </div>
          </>
        )}

        <div className="row end" style={{ marginTop: 14 }}>
          <button className="btn primary" disabled={busy} type="submit">
            {busy ? <span className="spinner" /> : null} Create claim
          </button>
        </div>
      </div>
    </form>
  )
}
