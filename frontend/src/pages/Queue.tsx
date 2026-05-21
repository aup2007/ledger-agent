import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Run } from '../api'

export function QueuePage() {
  const [rows, setRows] = useState<Run[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const tick = () => api.listRuns('needs_review')
      .then(r => { if (!cancelled) setRows(r) })
      .catch(e => { if (!cancelled) setErr(String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    tick()
    const t = setInterval(tick, 4000)
    return () => { cancelled = true; clearInterval(t) }
  }, [])

  return (
    <div>
      <div className="eyebrow">Pending · Reviewer Queue</div>
      <h1>Awaiting <em>review</em>.</h1>

      {err && <div style={{ color: 'var(--wax)' }}>{err}</div>}
      {loading
        ? <div style={{ color: 'var(--muted)', marginTop: 24 }}>Loading…</div>
        : rows.length === 0
          ? <div className="card" style={{ color: 'var(--muted)', marginTop: 18 }}>
              Inbox zero. Nothing waiting.
            </div>
          : <table style={{ marginTop: 18 }}>
              <thead>
                <tr><th>Run</th><th>Reason</th><th>Opened</th><th></th></tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.id}>
                    <td className="mono">#{r.id}</td>
                    <td style={{ color: 'var(--ink-2)' }}>{r.human_request ?? '—'}</td>
                    <td className="mono" style={{ color: 'var(--muted)' }}>
                      {new Date(r.started_at).toLocaleString()}
                    </td>
                    <td><Link to={`/runs/${r.id}`}>open →</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>}
    </div>
  )
}
