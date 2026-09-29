import { useMemo, useState } from 'react'
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

const GENDERS = ['', 'Female', 'Male', 'Other']
const CURRENCIES = ['INR', 'USD', 'EUR', 'GBP', 'AED']

const RAW_SECTIONS = [
  {
    key: 'patient',
    label: 'Patient',
    hint: 'Who the treatment is for',
    blocks: [
      {
        group: 'patient',
        fields: [
          { key: 'name', label: 'Full name', required: true, placeholder: 'e.g. Aarav Sharma' },
          { key: 'date_of_birth', label: 'Date of birth', required: true, type: 'date' },
          { key: 'gender', label: 'Gender', required: true, type: 'select', options: GENDERS, placeholder: 'Select' },
          { key: 'phone', label: 'Phone', type: 'tel', placeholder: '+91 98765 43210' },
          { key: 'email', label: 'Email', type: 'email', placeholder: 'name@example.com' },
          { key: 'address', label: 'Address', span: 'full', placeholder: 'Street, city, postcode' },
        ],
      },
    ],
  },
  {
    key: 'coverage',
    label: 'Insurance & policy',
    hint: 'Who pays, and under what policy',
    blocks: [
      {
        group: 'insurance',
        fields: [
          { key: 'provider', label: 'Insurance provider', required: true, placeholder: 'e.g. Star Health' },
          { key: 'policy_number', label: 'Policy number', required: true, placeholder: 'e.g. SH-2024-889134' },
          { key: 'policy_holder', label: 'Policy holder', placeholder: 'Defaults to patient name' },
          { key: 'member_id', label: 'Member ID' },
          { key: 'group_number', label: 'Group number' },
        ],
      },
    ],
  },
  {
    key: 'provider',
    label: 'Hospital & doctor',
    hint: 'Where, and by whom, the treatment happened',
    blocks: [
      {
        group: 'hospital',
        label: 'Hospital',
        fields: [
          { key: 'name', label: 'Hospital name', required: true, placeholder: 'e.g. Apollo Hospitals' },
          { key: 'phone', label: 'Hospital phone', type: 'tel' },
          { key: 'address', label: 'Hospital address', span: 'full' },
        ],
      },
      {
        group: 'doctor',
        label: 'Doctor',
        fields: [
          { key: 'name', label: 'Doctor name', required: true, placeholder: 'e.g. Dr. Meera Iyer' },
          { key: 'registration_number', label: 'Registration number', placeholder: 'Medical council no.' },
          { key: 'specialization', label: 'Specialisation', placeholder: 'e.g. General surgery' },
        ],
      },
    ],
  },
  {
    key: 'claim',
    label: 'Treatment & billing',
    hint: 'What was done, and what it cost',
    blocks: [
      {
        group: 'treatment',
        label: 'Treatment',
        fields: [
          { key: 'diagnosis', label: 'Primary diagnosis', required: true, placeholder: 'e.g. Acute appendicitis' },
          { key: 'admission_date', label: 'Admission date', required: true, type: 'date' },
          { key: 'discharge_date', label: 'Discharge date', required: true, type: 'date' },
          {
            key: 'treatment',
            label: 'Treatment provided',
            required: true,
            type: 'textarea',
            span: 'full',
            placeholder: 'e.g. Laparoscopic appendectomy, two nights of inpatient care',
          },
        ],
      },
      {
        group: 'billing',
        label: 'Billing',
        fields: [
          { key: 'total_amount', label: 'Total amount', required: true, type: 'number', step: '0.01', placeholder: 'e.g. 145000' },
          { key: 'currency', label: 'Currency', required: true, type: 'select', options: CURRENCIES },
          { key: 'invoice_number', label: 'Invoice number', placeholder: 'e.g. INV-2024-0042' },
        ],
      },
      {
        label: null,
        fields: [
          {
            key: 'notes',
            label: 'Anything else we should know?',
            type: 'textarea',
            span: 'full',
            placeholder:
              'Optional context for the reviewer — complications, prior claims, correspondence…',
            required: false,
          },
        ],
      },
    ],
  },
]

// Every field is treated as required unless explicitly opted out.
const SECTIONS = RAW_SECTIONS.map((section) => ({
  ...section,
  blocks: section.blocks.map((block) => ({
    ...block,
    fields: block.fields.map((f) => ({ ...f, required: f.required !== false })),
  })),
}))

const FLAT_FIELDS = []
SECTIONS.forEach((section) =>
  section.blocks.forEach((block) =>
    block.fields.forEach((f) =>
      FLAT_FIELDS.push({
        ...f,
        path: block.group ? `${block.group}.${f.key}` : f.key,
        section: section.key,
      }),
    ),
  ),
)
const REQUIRED = FLAT_FIELDS.filter((f) => f.required)
const SECTION_FIELDS = Object.fromEntries(
  SECTIONS.map((s) => [s.key, FLAT_FIELDS.filter((f) => f.section === s.key)]),
)
const SECTION_REQUIRED = Object.fromEntries(
  SECTIONS.map((s) => [s.key, SECTION_FIELDS[s.key].filter((f) => f.required)]),
)

function getIn(obj, path) {
  if (!path.includes('.')) return obj[path]
  const [group, key] = path.split('.')
  return obj[group]?.[key] ?? ''
}

function setIn(obj, path, value) {
  if (!path.includes('.')) return { ...obj, [path]: value }
  const [group, key] = path.split('.')
  return { ...obj, [group]: { ...obj[group], [key]: value } }
}

/** Create-claim form: sample shortcut plus validated-by-advice manual details. */
export default function NewClaimForm({ onCreated, onError }) {
  const [mode, setMode] = useState('sample')
  const [title, setTitle] = useState('')
  const [form, setForm] = useState(BLANK)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [touched, setTouched] = useState({})
  const [revealed, setRevealed] = useState(false)
  const [open, setOpen] = useState(() => Object.fromEntries(SECTIONS.map((s) => [s.key, true])))

  const filled = (path) => String(getIn(form, path) ?? '').trim().length > 0
  const titleDone = title.trim().length > 0
  const missing = useMemo(() => REQUIRED.filter((f) => !filled(f.path)), [form, title])
  const doneCount = REQUIRED.length - missing.length + (titleDone ? 1 : 0)
  const requiredTotal = REQUIRED.length + 1
  const gapCount = missing.length + (titleDone ? 0 : 1)

  const sectionProgress = (key) => {
    const req = SECTION_REQUIRED[key]
    const hit = req.filter((f) => filled(f.path)).length
    return { hit, total: req.length, complete: hit === req.length }
  }

  const showMissing = (path) =>
    mode === 'manual' && !filled(path) && (revealed || Boolean(touched[path]))
  const showTitleMissing =
    mode === 'manual' && !titleDone && (revealed || Boolean(touched.title))

  function field(block, def) {
    const path = block.group ? `${block.group}.${def.key}` : def.key
    const warn = showMissing(path) && def.required
    const control = (() => {
      const common = {
        value: getIn(form, path),
        onChange: (e) => setForm((f) => setIn(f, path, e.target.value)),
        onBlur: () => setTouched((t) => ({ ...t, [path]: true })),
        placeholder: def.placeholder,
        'aria-required': def.required ? 'true' : undefined,
        className: warn ? 'missing' : undefined,
      }
      if (def.type === 'select') {
        return (
          <select {...common}>
            <option value="">{def.placeholder ?? 'Select'}</option>
            {def.options.filter(Boolean).map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        )
      }
      if (def.type === 'textarea') return <textarea {...common} rows={3} />
      return <input {...common} type={def.type ?? 'text'} step={def.step} />
    })()

    return (
      <div className={`field${def.span === 'full' ? ' full' : ''}${warn ? ' warn' : ''}`} key={path}>
        <label>
          {def.label}
          {def.required ? (
            <span className="req" title="Required field">
              *
            </span>
          ) : null}
        </label>
        {control}
        {warn ? <span className="hint">Required — still empty</span> : null}
      </div>
    )
  }

  function toggle(key) {
    setOpen((o) => ({ ...o, [key]: !o[key] }))
  }

  function allOpen() {
    const every = SECTIONS.every((s) => open[s.key])
    setOpen(Object.fromEntries(SECTIONS.map((s) => [s.key, !every])))
  }

  async function submit(event) {
    event.preventDefault()
    setRevealed(true)
    setBusy(true)
    setError(null)
    try {
      const created = await api.createClaim({
        title: mode === 'sample' ? '' : title,
        use_sample_data: mode === 'sample',
        input_data: mode === 'sample' ? {} : form,
      })
      const gap = mode === 'sample' ? 0 : missing.length + (titleDone ? 0 : 1)
      setTitle('')
      setForm(BLANK)
      setTouched({})
      setRevealed(false)
      onCreated(created.claim_id, gap)
    } catch (err) {
      setError(err)
      onError?.(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card form-card" onSubmit={submit} noValidate>
      <header>
        <h2>New claim</h2>
        <span className="spacer" style={{ flex: 1 }} />
        {mode === 'manual' ? (
          <button type="button" className="linkish" onClick={allOpen}>
            {SECTIONS.every((s) => open[s.key]) ? 'Collapse all' : 'Expand all'}
          </button>
        ) : null}
      </header>

      <div className="form-body">
        <ErrorBanner error={error} onClose={() => setError(null)} />

        <div className="segmented">
          <button type="button" className={mode === 'sample' ? 'active' : ''} onClick={() => setMode('sample')}>
            Use sample data
          </button>
          <button type="button" className={mode === 'manual' ? 'active' : ''} onClick={() => setMode('manual')}>
            Enter my own
          </button>
        </div>

        {mode === 'sample' ? (
          <p className="hint copy">
            Creates a pre-filled claim with four generated documents — hospital bill, discharge
            summary, policy schedule and an insurance card photo — so you can watch every agent run.
          </p>
        ) : (
          <div className="manual">
            <div className="field warn-anchor">
              <label>
                Claim title
                <span className="req" title="Required field">
                  *
                </span>
              </label>
              <input
                value={title}
                placeholder="e.g. Aarav Sharma — appendectomy"
                onChange={(e) => setTitle(e.target.value)}
                onBlur={() => setTouched((t) => ({ ...t, title: true }))}
                aria-required="true"
                className={showTitleMissing ? 'missing' : undefined}
              />
              {showTitleMissing ? (
                <span className="hint">Required — give this claim a short, searchable name</span>
              ) : null}
            </div>

            <div className="sections">
              {SECTIONS.map((section) => {
                const { hit, total, complete } = sectionProgress(section.key)
                const isOpen = open[section.key]
                return (
                  <section className={`sec${isOpen ? ' open' : ''}`} key={section.key}>
                    <button
                      type="button"
                      className="sec-head"
                      aria-expanded={isOpen}
                      onClick={() => toggle(section.key)}
                    >
                      <span className="chev" aria-hidden="true">
                        ▸
                      </span>
                      <span className="sec-text">
                        <span className="sec-title">{section.label}</span>
                        <span className="sec-hint">{section.hint}</span>
                      </span>
                      <span className={`sec-badge${complete ? ' ok' : ''}`}>
                        {complete ? '✓' : `${hit}/${total}`}
                      </span>
                    </button>
                    {isOpen ? (
                      <div className="sec-body">
                        {section.blocks.map((block, i) => (
                          <div className="block" key={block.group ?? block.key ?? `block-${i}`}>
                            {block.label ? <p className="block-label">{block.label}</p> : null}
                            <div className="form-grid">
                              {block.fields.map((def) => field(block, def))}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </section>
                )
              })}
            </div>
          </div>
        )}
      </div>

      <div className="form-actions">
        <div className="counter">
          {mode === 'sample' ? (
            <span className="muted">Everything is pre-filled</span>
          ) : (
            <>
              <b>
                {doneCount} / {requiredTotal}
              </b>{' '}
              required fields
              {gapCount > 0 ? (
                <span className="gap">
                  {' '}
                  · {gapCount} still empty
                </span>
              ) : (
                <span className="gap ok"> · all filled</span>
              )}
            </>
          )}
        </div>
        <button className="btn primary" disabled={busy} type="submit">
          {busy ? <span className="spinner" /> : null} Create claim
        </button>
      </div>
    </form>
  )
}
