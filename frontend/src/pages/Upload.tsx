import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

export function UploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const nav = useNavigate()

  useEffect(() => {
    if (!file) { setPreviewUrl(null); return }
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  async function submit() {
    if (!file) return
    setBusy(true); setErr(null)
    try {
      const { run_id } = await api.uploadDocument(file)
      nav(`/runs/${run_id}`)
    } catch (e) {
      setErr(String(e))
      setBusy(false)
    }
  }

  function pickFile(f: File | null) {
    if (!f) return
    if (f.type && f.type !== 'application/pdf') {
      setErr('Only PDF files are supported.')
      return
    }
    setErr(null); setFile(f)
  }

  return (
    <div className="upload-page">
      {/* Headline strip — always present */}
      <header className="upload-head">
        <div>
          <div className="eyebrow">Subscription &middot; Capital Call</div>
          <h1>Process an <em>alternative</em>‑investment document.</h1>
        </div>
        <p className="lede">
          Drop a subscription agreement or capital‑call notice below. Review
          the source, then dispatch to the agent. Clean documents resolve to
          <em> IGO</em>; ambiguous ones route to a reviewer with the full trace.
        </p>
      </header>

      {/* Empty state: large dropzone */}
      {!file && (
        <div
          className={`dropzone-xl ${dragging ? 'dragging' : ''}`}
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={e => {
            e.preventDefault(); setDragging(false)
            pickFile(e.dataTransfer.files[0] ?? null)
          }}
          onClick={() => inputRef.current?.click()}
        >
          <div className="dz-icon" aria-hidden>
            <svg viewBox="0 0 64 64" width="56" height="56" fill="none">
              <path d="M16 8h22l12 12v36a4 4 0 0 1-4 4H16a4 4 0 0 1-4-4V12a4 4 0 0 1 4-4Z"
                    stroke="currentColor" strokeWidth="1.5" />
              <path d="M38 8v12h12" stroke="currentColor" strokeWidth="1.5" />
              <path d="M32 30v18M24 38l8-8 8 8" stroke="currentColor" strokeWidth="1.5"
                    strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="dz-headline">Drop a PDF anywhere on this page</div>
          <div className="dz-sub">or click to browse</div>
        </div>
      )}

      {/* Loaded state: full-width preview + action bar */}
      {file && previewUrl && (
        <div className="preview">
          <div className="preview-bar">
            <div className="pb-meta">
              <div className="pb-eyebrow">Source · Awaiting Dispatch</div>
              <div className="pb-name mono">{file.name}</div>
            </div>
            <div className="pb-actions">
              <span className="pb-size mono">{(file.size / 1024).toFixed(1)} KB</span>
              <button className="btn secondary" disabled={busy}
                      onClick={() => { setFile(null); if (inputRef.current) inputRef.current.value = '' }}>
                Replace
              </button>
              <button className="btn primary" disabled={busy} onClick={submit}>
                {busy ? 'Dispatching…' : 'Process Document  →'}
              </button>
            </div>
          </div>
          <iframe
            title="upload-preview"
            src={previewUrl + '#toolbar=0&navpanes=0&view=FitH'}
            className="preview-frame"
          />
        </div>
      )}

      <input
        ref={inputRef}
        type="file" accept="application/pdf"
        style={{ display: 'none' }}
        onChange={e => pickFile(e.target.files?.[0] ?? null)}
      />

      {err && <div style={{ color: 'var(--wax)', marginTop: 14 }} className="mono">{err}</div>}
    </div>
  )
}
