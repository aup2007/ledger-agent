// Typed wrappers around the FastAPI endpoints. Single source of truth
// for the shape of a run / step so the rest of the app stays unaware of
// fetch() details.

// In dev, VITE_API_BASE is empty and Vite's proxy forwards /documents and
// /runs to localhost:8000. In production (Railway), set
//   VITE_API_BASE=https://<api-service>.up.railway.app
const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')
const u = (path: string) => `${API_BASE}${path}`

export type RunStatus =
  | 'queued' | 'running' | 'needs_review' | 'completed' | 'failed'

export interface Run {
  id: number
  document_id: number
  status: RunStatus
  verdict: 'IGO' | 'NIGO' | null
  record: Record<string, unknown> | null
  human_request: string | null
  started_at: string
  finished_at: string | null
}

export interface Step {
  step_index: number
  node: string
  detail: string
  created_at: string
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  uploadDocument: async (file: File): Promise<{ run_id: number }> => {
    const fd = new FormData()
    fd.append('file', file)
    return jsonOrThrow(await fetch(u('/documents'), { method: 'POST', body: fd }))
  },

  getRun: async (id: number): Promise<Run> =>
    jsonOrThrow(await fetch(u(`/runs/${id}`))),

  getTrace: async (id: number): Promise<Step[]> =>
    jsonOrThrow(await fetch(u(`/runs/${id}/trace`))),

  listRuns: async (status?: RunStatus): Promise<Run[]> => {
    const path = status ? `/runs?status=${status}` : '/runs'
    return jsonOrThrow(await fetch(u(path)))
  },

  documentUrl: (id: number): string => u(`/runs/${id}/document`),

  reviewRun: async (id: number, humanInput: Record<string, unknown>): Promise<Run> =>
    jsonOrThrow(await fetch(u(`/runs/${id}/review`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ human_input: humanInput }),
    })),
}
