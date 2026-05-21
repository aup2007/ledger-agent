import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, type Run, type Step } from '../api'
import { Timeline } from '../components/Timeline'

const POLLING_STATUSES = new Set(['queued', 'running'])

export function RunDetailPage() {
  const { id } = useParams()
  const runId = Number(id)
  const [run, setRun] = useState<Run | null>(null)
  const [steps, setSteps] = useState<Step[]>([])
  const [err, setErr] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [r, t] = await Promise.all([api.getRun(runId), api.getTrace(runId)])
      setRun(r); setSteps(t); setErr(null)
    } catch (e) { setErr(String(e)) }
  }, [runId])

  useEffect(() => {
    refresh()
    const interval = setInterval(() => {
      if (!run || POLLING_STATUSES.has(run.status)) refresh()
    }, 2000)
    return () => clearInterval(interval)
  }, [refresh, run])

  if (err) return <div style={{ color: 'var(--wax)' }}>{err}</div>
  if (!run) return <div style={{ color: 'var(--muted)' }}>Loading run #{runId}…</div>

  const isLive = POLLING_STATUSES.has(run.status)

  return (
    <div>
      <div className="run-head">
        <div>
          <div className="eyebrow">Run · #{run.id}</div>
          <h1>The <em>Ledger</em>.</h1>
        </div>
      </div>

      <VerdictBanner run={run} />

      <div className="run-grid">
        <aside className="run-pdf">
          <DocumentViewer runId={run.id} />
        </aside>

        <section className="run-right">
          <h2>Standardized Record</h2>
          {run.record
            ? <RecordTable record={run.record} />
            : <div className="card" style={{ color: 'var(--muted)' }}>No record yet.</div>}

          {run.status === 'needs_review' && (
            <>
              <h2>Reviewer Input Required</h2>
              <ReviewForm run={run} onResolved={refresh} />
            </>
          )}

          <h2>Reasoning Trace {isLive && <span className="live-dot" />}</h2>
          <Timeline steps={steps} live={isLive} />
        </section>
      </div>
    </div>
  )
}

function DocumentViewer({ runId }: { runId: number }) {
  const url = api.documentUrl(runId)
  return (
    <div className="pdf-card">
      <div className="pdf-head">
        <span>PDF · Source</span>
        <a href={url} target="_blank" rel="noreferrer">open in tab ↗</a>
      </div>
      <iframe
        title={`document-${runId}`}
        src={url + '#toolbar=0&navpanes=0&view=FitH'}
        className="pdf-frame"
      />
    </div>
  )
}

function VerdictBanner({ run }: { run: Run }) {
  let cls = run.status, dc = '·', title = '', meta = ''
  if (run.status === 'completed' && run.verdict === 'IGO') {
    cls = 'IGO'; dc = 'I'
    title = 'In Good Order'
    meta = 'All deterministic checks passed.'
  } else if (run.status === 'completed' && run.verdict === 'NIGO') {
    cls = 'NIGO'; dc = 'N'
    title = 'Not In Good Order'
    meta = 'Validation failed; see trace.'
  } else if (run.status === 'needs_review') {
    cls = 'needs_review'; dc = 'R'
    title = 'Needs Human Review'
    meta = run.human_request ?? 'Reviewer input required.'
  } else if (run.status === 'failed') {
    cls = 'failed'; dc = 'F'
    title = 'Failed'
    meta = run.human_request ?? 'Unknown error.'
  } else if (run.status === 'queued') {
    cls = 'queued'; dc = 'Q'
    title = 'Queued'
    meta = 'Awaiting worker.'
  } else if (run.status === 'running') {
    cls = 'running'; dc = '⟶'
    title = 'Processing'
    meta = 'Agent is running the graph.'
  }
  return (
    <div className={`banner ${cls}`}>
      <div className="dc">{dc}</div>
      <div className="b-body">
        <div className="b-title">{title}</div>
        <div className="b-meta">{meta}</div>
      </div>
    </div>
  )
}

function RecordTable({ record }: { record: Record<string, unknown> }) {
  const keys = useMemo(() => Object.keys(record), [record])
  return (
    <div className="card record">
      {keys.map(k => {
        const v = record[k]
        const isNull = v === null || v === undefined
        return (
          <div key={k} className="row">
            <div className="k">{k}</div>
            <div className={`v ${isNull ? 'null' : ''}`}>
              {isNull ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ReviewForm({ run, onResolved }: { run: Run; onResolved: () => void }) {
  const fields = useMemo(() => deriveFields(run.human_request ?? ''), [run.human_request])
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries(fields.map(f => [f, '']))
  )
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit() {
    setBusy(true); setErr(null)
    try {
      const payload: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(values)) {
        if (v === '') continue
        payload[k] = parseScalar(v)
      }
      if ('call_amount' in payload && !('amount_ambiguous' in payload)) {
        payload['amount_ambiguous'] = false
      }
      await api.reviewRun(run.id, payload)
      onResolved()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <div className="review-form">
        {fields.map(f => (
          <FieldInput key={f} name={f}
            value={values[f]}
            onChange={v => setValues(s => ({ ...s, [f]: v }))} />
        ))}
      </div>
      <div style={{ marginTop: 18, display: 'flex', gap: 12 }}>
        <button className="btn primary" disabled={busy} onClick={submit}>
          {busy ? 'Submitting…' : 'Submit Review'}
        </button>
      </div>
      {err && <div style={{ color: 'var(--wax)', marginTop: 12 }} className="mono">{err}</div>}
    </div>
  )
}

function FieldInput({ name, value, onChange }: {
  name: string; value: string; onChange: (v: string) => void
}) {
  const boolish = /present|ambiguous|signature|tax_id|wire/i.test(name)
  return (
    <>
      <label>{name}</label>
      {boolish
        ? <select value={value} onChange={e => onChange(e.target.value)}>
            <option value="">— pick —</option>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        : <input type="text" value={value}
                 placeholder='e.g. 50000 or "Aqua Alpha"'
                 onChange={e => onChange(e.target.value)} />}
    </>
  )
}

function deriveFields(human_request: string): string[] {
  const out = new Set<string>()
  for (const seg of human_request.split(';')) {
    const m = seg.trim().match(/^([a-z0-9_]+):/i)
    if (m) out.add(m[1])
  }
  return [...out]
}

function parseScalar(v: string): unknown {
  if (v === 'true') return true
  if (v === 'false') return false
  if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v)
  return v
}
