/**
 * Landing page shown when no claim is open.
 *
 * It exists to answer the three questions a first-time visitor has: what is
 * this, how does it work, and can I trust the output. Everything it claims is
 * true of the code - no invented capabilities.
 */

const FEATURES = [
  {
    icon: '01',
    title: 'Reads your documents',
    text: 'Upload a hospital bill, discharge summary, policy schedule or insurance card. The document agent classifies each one and reads it multimodally.',
  },
  {
    icon: '02',
    title: 'Every field has provenance',
    text: 'Each extracted value records where it came from - typed by you, read from a file, or derived - plus the filename and snippet it was found in.',
  },
  {
    icon: '03',
    title: 'Never invents a value',
    text: 'A missing required field stops the run as needs_input instead of guessing. Blank stays blank and is reported as missing.',
  },
  {
    icon: '04',
    title: 'Rules plus model checks',
    text: 'Dates, totals, IDs and chronology are checked by deterministic rules; the model only adds semantic clashes a rule cannot see.',
  },
  {
    icon: '05',
    title: 'Deterministic PDF',
    text: 'ReportLab renders the claim form from structured fields - the model never controls layout, so the same claim always produces the same document.',
  },
  {
    icon: '06',
    title: 'Survives a model outage',
    text: 'If the provider is rate limited or overloaded mid-run, the stage falls back to the rule engine and says so. Completed work is never thrown away.',
  },
]

const STEPS = [
  ['Input', 'Collect typed details and the files you uploaded. Nothing is sent anywhere yet.'],
  ['Document analysis', 'Classify and read each attachment - invoice, summary, policy, card.'],
  ['Extraction', 'Merge typed values with what was read, resolving conflicts per field.'],
  ['Validation', 'Required fields, dates, totals, identifiers, chronology, semantic clashes.'],
  ['Generation', 'Build the claim narrative, itemised charges and identifiers.'],
  ['Review', 'Compare the draft against the source and list what a human must confirm.'],
]

const AGENTS = [
  ['Input agent', 'Normalises what you supplied'],
  ['Document agent', 'Multimodal document reading'],
  ['Extraction agent', 'Field merge + conflict resolution'],
  ['Validation agent', 'Rules + semantic consistency'],
  ['Generation agent', 'Narrative, charges, identifiers'],
  ['Review agent', 'Final human-review checklist'],
]

export default function Landing({ onStart }) {
  return (
    <div className="landing">
      <section className="hero card">
        <span className="eyebrow">Multi-agent claims drafting</span>
        <h2>Turn a folder of medical documents into a reviewable insurance claim draft.</h2>
        <p className="lede">
          MediClaim reads the bills, summaries and policy pages you already have, extracts the
          fields a claim form asks for, checks them for contradictions, and writes a draft claim
          with a PDF you can hand to an authorised reviewer.
        </p>
        <div className="cta">
          <button className="btn primary" onClick={onStart}>
            Create a claim
          </button>
          <a className="btn ghost" href="#how">
            See how it works
          </a>
        </div>
        <ul className="hero-points">
          <li>Draft output only - no medical or coverage advice</li>
          <li>Never approves, rejects or adjudicates a claim</li>
          <li>Works without a model token in deterministic mode</li>
        </ul>
      </section>

      <section className="card" id="about">
        <header>
          <h2>What this website is</h2>
        </header>
        <div className="body about-body">
          <p>
            <b>MediClaim &middot; ClaimGen AI</b> is a full-stack demonstration of an AI agent
            pipeline applied to insurance claim intake. It is not an insurer, a broker or a
            medical service. It does one job: convert documents you already hold into a
            structured draft that a human can verify in minutes instead of re-typing every field.
          </p>
          <p>
            The interesting part is the architecture rather than the output. Six agents
            communicate only through typed Pydantic records, each stage computes a deterministic
            answer before it ever calls a language model, and any stage that cannot reach the
            model keeps its rule-based result and marks itself{' '}
            <code>warning</code> rather than failing the run. That is why the app still works
            end to end with no token at all.
          </p>
        </div>
      </section>

      <section className="card">
        <header>
          <h2>What it does</h2>
          <span className="spacer" style={{ flex: 1 }} />
          <span className="muted tiny">{FEATURES.length} capabilities</span>
        </header>
        <div className="body">
          <div className="feature-grid">
            {FEATURES.map((feature) => (
              <article className="feature" key={feature.title}>
                <span className="ficon">{feature.icon}</span>
                <h3>{feature.title}</h3>
                <p>{feature.text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="card" id="how">
        <header>
          <h2>How it works</h2>
          <span className="spacer" style={{ flex: 1 }} />
          <span className="muted tiny">6 stages, run in order</span>
        </header>
        <div className="body">
          <ol className="how">
            {STEPS.map(([title, text], index) => (
              <li key={title}>
                <span className="num">{index + 1}</span>
                <div>
                  <b>{title}</b>
                  <p>{text}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="card">
        <header>
          <h2>The six agents</h2>
          <span className="spacer" style={{ flex: 1 }} />
          <span className="muted tiny">structured records only</span>
        </header>
        <div className="body">
          <div className="agent-grid">
            {AGENTS.map(([name, text]) => (
              <div className="agent" key={name}>
                <b>{name}</b>
                <span>{text}</span>
              </div>
            ))}
          </div>
          <div className="notice">
            Agents never talk to each other and never share chain-of-thought - they pass a single
            typed record down the pipeline, so every stage can be inspected and re-run on its own.
          </div>
        </div>
      </section>

      <section className="card">
        <header>
          <h2>Built with</h2>
        </header>
        <div className="body">
          <div className="tech-row">
            {[
              'FastAPI',
              'Pydantic v2',
              'React 18',
              'Vite 5',
              'Hugging Face Inference Providers',
              'Google Gemini (optional)',
              'ReportLab',
              'pypdf',
              'Render + Vercel',
            ].map((item) => (
              <span className="tech" key={item}>
                {item}
              </span>
            ))}
          </div>
          <div className="notice">
            <b>Safety note.</b> This produces a <b>draft</b>. It performs no medical assessment,
            approves no claim, and must not be treated as a source of truth. Every generated field
            requires verification by an authorised human against the original records before it is
            submitted to an insurer.
          </div>
        </div>
      </section>
    </div>
  )
}
