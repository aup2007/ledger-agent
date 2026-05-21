// Reasoning-trace timeline. Each row is colored by node category; the
// last row pulses to indicate "agent is still running" and dotted rail
// echoes ledger paper. Staggered animation-delay creates a deliberate
// reveal on page load and on each newly-arrived step.

import type { Step } from '../api'

const NODE_CLASS: Record<string, string> = {
  ingest: 'tl-ingest',
  classify: 'tl-classify',
  extract: 'tl-extract',
  normalize: 'tl-normalize',
  validate: 'tl-validate',
  verdict: 'tl-verdict',
  remediate: 'tl-remediate',
  auto_fix: 'tl-auto_fix',
  request_human: 'tl-request_human',
  finalize: 'tl-finalize',
}

function classFor(node: string): string {
  return NODE_CLASS[node] ?? 'tl-default'
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString(undefined, { hour12: false })
  } catch { return iso }
}

export function Timeline({ steps, live }: { steps: Step[]; live: boolean }) {
  if (steps.length === 0) {
    return <div className="card" style={{ color: 'var(--muted)' }}>
      No steps yet — waiting for the agent to start…
    </div>
  }
  return (
    <div className="timeline">
      {steps.map((s, i) => {
        const isLast = live && i === steps.length - 1
        return (
          <div
            key={s.step_index}
            className={`tl-row ${classFor(s.node)} ${isLast ? 'is-last' : ''}`}
            style={{ animationDelay: `${Math.min(i, 12) * 60}ms` }}
          >
            <span className="tl-dot" />
            <div className="tl-card">
              <div className="tl-head">
                <span className="tl-node">{s.node}</span>
                <span className="tl-time">{formatTime(s.created_at)}</span>
              </div>
              <div className="tl-detail">{s.detail}</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
