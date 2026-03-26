import { useCallback, useEffect, useRef, useState } from 'react'
import { Job, submitFile, submitUrl } from '../api/jobs'

interface AddPaperDialogProps {
  onClose: () => void
  onSubmitted: (job: Job) => void
}

type Tab = 'url' | 'upload'

export function AddPaperDialog({ onClose, onSubmitted }: AddPaperDialogProps) {
  const [tab, setTab] = useState<Tab>('url')
  const [url, setUrl] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const handleSubmit = useCallback(async () => {
    setError(null)
    setSubmitting(true)
    try {
      let jobId: string
      if (tab === 'url') {
        if (!url.trim()) { setError('Please enter a URL.'); return }
        jobId = await submitUrl(url.trim())
      } else {
        if (!file) { setError('Please select a file.'); return }
        jobId = await submitFile(file)
      }
      const job: Job = {
        job_id: jobId,
        status: 'queued',
        source: tab === 'url' ? url.trim() : (file?.name ?? ''),
        step: 'Queued…',
        paper_id: null,
        error: null,
        created_at: new Date().toISOString(),
      }
      onSubmitted(job)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }, [tab, url, file, onSubmitted])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        {/* header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700">
          <h2 className="text-sm font-semibold text-slate-100">Add paper for review</h2>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300 transition-colors text-xl leading-none"
          >
            ×
          </button>
        </div>

        <div className="px-5 py-4">
          {/* tabs */}
          <div className="flex gap-1 bg-slate-800 rounded-lg p-1 mb-4">
            {(['url', 'upload'] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className="flex-1 py-1.5 rounded-md text-xs font-mono font-medium transition-colors"
                style={{
                  backgroundColor: tab === t ? '#1e3a5f' : 'transparent',
                  color: tab === t ? '#93c5fd' : '#64748b',
                }}
              >
                {t === 'url' ? '🔗  Link' : '📄  Upload'}
              </button>
            ))}
          </div>

          {tab === 'url' && (
            <div className="mb-4">
              <label className="block text-[10px] uppercase tracking-widest text-slate-500 mb-1.5">
                Paper URL
              </label>
              <input
                autoFocus
                type="url"
                placeholder="https://arxiv.org/abs/…"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit() }}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-200 placeholder-slate-600 px-3 py-2.5 outline-none focus:border-blue-600 transition-colors font-mono"
              />
              <p className="text-[10px] text-slate-600 mt-1.5">
                Accepts arXiv pages, direct PDF links, DOI URLs, and open-access HTML papers.
              </p>
            </div>
          )}

          {tab === 'upload' && (
            <div className="mb-4">
              <label className="block text-[10px] uppercase tracking-widest text-slate-500 mb-1.5">
                Paper file
              </label>
              <button
                onClick={() => fileInputRef.current?.click()}
                className="w-full bg-slate-800 border border-dashed border-slate-600 rounded-lg px-3 py-6 text-center hover:border-slate-500 transition-colors"
              >
                {file ? (
                  <span className="text-xs text-slate-300 font-mono">{file.name}</span>
                ) : (
                  <span className="text-xs text-slate-600">Click to select a PDF or HTML file</span>
                )}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.html,.htm"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
          )}

          {error && <p className="text-xs text-red-400 mb-3 font-mono">{error}</p>}

          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="w-full py-2.5 rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
            style={{ backgroundColor: '#1d4ed8', color: '#fff' }}
          >
            {submitting ? 'Submitting…' : 'Start review'}
          </button>
        </div>
      </div>
    </div>
  )
}
