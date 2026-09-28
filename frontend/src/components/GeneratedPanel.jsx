import { Empty, Field, Money } from './Primitives.jsx'

/** The generated claim plus the download link for the rendered PDF. */
export default function GeneratedPanel({ claim }) {
  const generated = claim?.generated
  if (!generated) {
    return (
      <div className="card">
        <header>
          <h2>Generated claim</h2>
        </header>
        <Empty>No claim form yet. Run the pipeline to generate one.</Empty>
      </div>
    )
  }

  const items = generated.line_items ?? []

  return (
    <div className="card">
      <header>
        <h2>Generated claim</h2>
        <span className="spacer" style={{ flex: 1 }} />
        <a className="btn primary sm" href={`/api/claim/${claim.claim_id}/pdf`} target="_blank" rel="noreferrer">
          Download PDF
        </a>
      </header>
      <div className="body">
        <div className="notice">
          <b>This is a draft for a human to verify.</b> It was assembled from the information you
          supplied and the documents you uploaded. It has not been checked or approved by any
          insurer, and MediClaim gives no medical or insurance advice.
        </div>

        <dl className="kv">
          <Field label="Claim number" value={generated.claim_number} mono />
          <Field label="Claim type" value={generated.claim_type} />
          <dt>Amount claimed</dt>
          <dd>
            <Money amount={generated.claim_amount} currency={generated.currency} />
          </dd>
          <Field label="Amount in words" value={generated.amount_in_words} />
          <Field label="Service period" value={generated.service_period} />
          <Field label="Place of treatment" value={generated.place_of_treatment} />
          <Field label="Claimed by" value={generated.claimed_by} />
          <Field label="Generated at" value={generated.generated_at} />
        </dl>

        {generated.narrative ? (
          <>
            <p
              className="tiny muted"
              style={{ margin: '14px 0 5px', fontWeight: 700, textTransform: 'uppercase' }}
            >
              Narrative
            </p>
            <p style={{ margin: 0, textAlign: 'justify' }}>{generated.narrative}</p>
          </>
        ) : null}

        {items.length ? (
          <table className="items" style={{ marginTop: 14 }}>
            <thead>
              <tr>
                <th>Description</th>
                <th>Category</th>
                <th className="num">Amount</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, index) => (
                <tr key={`${item.description}-${index}`}>
                  <td>{item.description}</td>
                  <td className="muted">{item.category || '-'}</td>
                  <td className="num">{Number(item.amount).toLocaleString('en-IN')}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={2}>Sub total</td>
                <td className="num">{Number(generated.sub_total).toLocaleString('en-IN')}</td>
              </tr>
              {generated.discount ? (
                <tr>
                  <td colSpan={2}>Discount</td>
                  <td className="num">-{Number(generated.discount).toLocaleString('en-IN')}</td>
                </tr>
              ) : null}
              <tr>
                <td colSpan={2}>Total claimed</td>
                <td className="num">{Number(generated.claim_amount).toLocaleString('en-IN')}</td>
              </tr>
            </tfoot>
          </table>
        ) : null}

        {generated.derivation_notes?.length ? (
          <>
            <p
              className="tiny muted"
              style={{ margin: '14px 0 5px', fontWeight: 700, textTransform: 'uppercase' }}
            >
              How these totals were worked out
            </p>
            <ul className="tiny muted" style={{ margin: 0, paddingLeft: 18 }}>
              {generated.derivation_notes.map((note, index) => (
                <li key={index}>{note}</li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </div>
  )
}
