import { Empty, Field, Money } from './Primitives.jsx'

/** The merged claim data every agent worked from. */
export default function ClaimDataPanel({ claim }) {
  const data = claim?.claim_data
  if (!data) {
    return (
      <div className="card">
        <header>
          <h2>Claim data</h2>
        </header>
        <Empty>The agents have not produced claim data yet. Run the pipeline first.</Empty>
      </div>
    )
  }

  const sources = claim?.field_sources ?? {}
  const section = (title, obj, rows) => (
    <div className="card" key={title}>
      <header>
        <h2>{title}</h2>
      </header>
      <div className="body">
        <dl className="kv">
          {rows.map(([key, label]) => (
            <Field key={key} label={label} value={obj?.[key]} />
          ))}
        </dl>
      </div>
    </div>
  )

  const flagged = Object.entries(sources).filter(([, source]) => source === 'uncertain')

  return (
    <>
      {flagged.length ? (
        <div className="notice info">
          <b>{flagged.length} field(s) need a human decision.</b>
          These are values that appear in more than one place but do not match. Check them against
          the original documents before submitting.
        </div>
      ) : null}

      {section('Patient', data.patient, [
        ['name', 'Full name'],
        ['date_of_birth', 'Date of birth'],
        ['gender', 'Gender'],
        ['phone', 'Phone'],
        ['email', 'Email'],
        ['patient_id', 'Hospital record / patient ID'],
        ['address', 'Address'],
      ])}

      {section('Insurance', data.insurance, [
        ['provider', 'Provider'],
        ['policy_number', 'Policy number'],
        ['member_id', 'Member ID'],
        ['group_number', 'Group number'],
        ['policy_holder', 'Policy holder'],
        ['policy_start_date', 'Policy start'],
        ['policy_end_date', 'Policy end'],
        ['sum_insured', 'Sum insured'],
      ])}

      {section('Hospital', data.hospital, [
        ['name', 'Hospital name'],
        ['facility_type', 'Facility type'],
        ['address', 'Address'],
        ['phone', 'Phone'],
        ['license_number', 'Registration / licence'],
      ])}

      {section('Treating doctor', data.doctor, [
        ['name', 'Name'],
        ['registration_number', 'Registration number'],
        ['specialization', 'Specialisation'],
        ['designation', 'Designation'],
      ])}

      {section('Treatment', data.treatment, [
        ['diagnosis', 'Diagnosis'],
        ['icd_code', 'ICD code'],
        ['procedure', 'Procedure'],
        ['treatment', 'Treatment'],
        ['admission_date', 'Admission date'],
        ['discharge_date', 'Discharge date'],
        ['clinical_notes', 'Clinical notes'],
      ])}

      <div className="card">
        <header>
          <h2>Billing</h2>
        </header>
        <div className="body">
          <dl className="kv">
            <Field label="Invoice number" value={data.billing?.invoice_number} />
            <Field label="Invoice date" value={data.billing?.invoice_date} />
            <dt>Total amount</dt>
            <dd>
              {data.billing?.total_amount
                ? <Money amount={data.billing.total_amount} currency={data.billing.currency} />
                : 'Not provided'}
            </dd>
            <Field label="Currency" value={data.billing?.currency} />
          </dl>

          {data.billing?.line_items?.length ? (
            <table className="items" style={{ marginTop: 13 }}>
              <thead>
                <tr>
                  <th>Description</th>
                  <th>Category</th>
                  <th className="num">Qty</th>
                  <th className="num">Rate</th>
                  <th className="num">Amount</th>
                </tr>
              </thead>
              <tbody>
                {data.billing.line_items.map((item, index) => (
                  <tr key={`${item.description}-${index}`}>
                    <td>{item.description}</td>
                    <td className="muted">{item.category || '-'}</td>
                    <td className="num">{item.quantity}</td>
                    <td className="num">{Number(item.unit_price).toLocaleString('en-IN')}</td>
                    <td className="num">{Number(item.amount).toLocaleString('en-IN')}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={4}>Total</td>
                  <td className="num">
                    {Number(data.billing.total_amount || 0).toLocaleString('en-IN')}
                  </td>
                </tr>
              </tfoot>
            </table>
          ) : (
            <p className="tiny muted" style={{ marginBottom: 0 }}>
              No itemised breakdown was found in the documents.
            </p>
          )}
        </div>
      </div>
    </>
  )
}
