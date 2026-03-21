import { useCallback, useEffect, useRef, useState } from 'react'
import { getJob, Job, submitFile, submitUrl } from '../api/jobs'

interface AddPaperDialogProps {
  onClose: () => void
  onDone: (paperId: string) => void
}

type Tab = 'url' | 'upload'

const POLL_INTERVAL = 2000

const STEP_ORDER = [
  '[1/6]',
  '[2/6]',
  '[3/6]',
  '[4/6]',
  '[5/6]',
  '[6/6]',
  '✓',
]

function stepIndex(step: string): number {
  for (let i = 0; i < STEP_ORDER.length; i++) {
    if (step.startsWith(STEP_ORDER[i])) return i
  }
  return -1
}

function ProgressSteps({ step, status }: { step: string; status: Job['status'] }) {
  const labels = [
    'Fetch',
    'Extract text',
    'Extract claims',
    'Build DAG',
    'Evaluate claims',
    'Write output',
  ]
  const current = stepIndex(step)

  return (
    <div className="flex items-center gap-0 mt-3 mb-1">
      {labels.map((label, i) => {
        const done = status === 'done' || (current > i)
        const active = current === i && status === 'running'
        const failed = status === 'error' && current === i
        return (
          <div key={i} className="flex items-center flex-1 min-w-0">
            <div className="flex flex-col items-center">
              <div
                className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-mono font-bold shrink-0 transition-colors"
                style={{
                  backgroundColor: failed
                    ? '#ef4444'
                    : done
                      ? '#22c55e'
                      : active
                        ? '#3b82f6'
                        : '#1e293b',
                  border: `1px solid ${failed ? '#ef4444' : done ? '#22c55e' : active ? '#3b82f6' : '#334155'}`,
                  color: done || active || failed ? '#fff' : '#475569',
                }}
              >
                {done ? '✓' : failed ? '✕' : i + 1}
              </div>
              <span
                className="text-[9px] font-mono mt-0.5 text-center leading-tight"
                style={{
                  color: done ? '#22c55e' : active ? '#93c5fd' : failed ? '#ef4444' : '#475569',
                  maxWidth: 48,
                  wordBreak: 'break-word',
                }}
              >
                {label}
              </span>
            </div>
            {i < labels.length - 1 && (
              <div
                className="flex-1 h-px mx-1 mb-4 transition-colors"
                style={{ backgroundColor: i < current || status === 'done' ? '#22c55e' : '#1e293b' }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

export function AddPaperDialog({ onClose, onDone }: AddPaperDialogProps) {
  const [tab, setTab] = useState<Tab>('url')
  const [url, setUrl] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Keyboard close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // Polling
  useEffect(() => {
    if (!job || job.status === 'done' || job.status === 'error') {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }
    pollRef.current = setInterval(async () => {
      try {
        const updated = await getJob(job.job_id)
        setJob(updated)
        if (updated.status === 'done' && updated.paper_id) {
          onDone(updated.paper_id)
        }
      } catch {
        // ignore transient errors
      }
    }, POLL_INTERVAL)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [job, onDone])

  const handleSubmit = useCallback(async () => {
    setSubmitError(null)
    setSubmitting(true)
    try {
      let jobId: string
      if (tab === 'url') {
        if (!url.trim()) { setSubmitError('Please enter a URL.'); return }
        jobId = await submitUrl(url.trim())
      } else {
        if (!file) { setSubmitError('Please select a file.'); return }
        jobId = await submitFile(file)
      }
      // Seed local job state immediately; polling will fill in the rest
      setJob({
        job_id: jobId,
        status: 'queued',
        source: tab === 'url' ? url : (file?.name ?? ''),
        step: 'Queued…',
        paper_id: null,
        error: null,
        created_at: new Date().toISOString(),
      })
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }, [tab, url, file])

  const isInProgress = job && (job.status === 'queued' || job.status === 'running')
  const isDone = job?.status === 'done'
  const isFailed = job?.status === 'error'

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
          {/* Tab switcher — only show before a job starts */}
          {!job && (
            <>
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
                      <span className="text-xs text-slate-600">
                        Click to select a PDF or HTML file
                      </span>
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

              {submitError && (
                <p className="text-xs text-red-400 mb-3 font-mono">{submitError}</p>
              )}

              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="w-full py-2.5 rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
                style={{ backgroundColor: '#1d4ed8', color: '#fff' }}
              >
                {submitting ? 'Submitting…' : 'Start review'}
              </button>
            </>
          )}

          {/* Job progress */}
          {job && (
            <div>
              <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">
                {tab === 'url' ? 'Processing URL' : 'Processing file'}
              </p>
              <p className="text-xs text-slate-300 font-mono truncate mb-3">{job.source}</p>

              <ProgressSteps step={job.step} status={job.status} />

              {/* step log line */}
              <p
                className="text-[10px] font-mono mt-3 leading-relaxed"
                style={{
                  color: isFailed ? '#f87171' : isDone ? '#4ade80' : '#93c5fd',
                }}
              >
                {job.step}
              </p>

              {isFailed && (
                <div className="mt-3 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
                  <p className="text-xs text-red-400 font-mono break-words">{job.error}</p>
                </div>
              )}

              {isDone && (
                <div className="mt-4 flex gap-2">
                  <button
                    onClick={onClose}
                    className="flex-1 py-2 rounded-lg text-xs font-semibold transition-colors"
                    style={{ backgroundColor: '#22c55e', color: '#fff' }}
                  >
                    View paper
                  </button>
                  <button
                    onClick={() => { setJob(null); setUrl(''); setFile(null) }}
                    className="py-2 px-3 rounded-lg text-xs font-semibold text-slate-400 hover:text-slate-200 transition-colors border border-slate-700"
                  >
                    Add another
                  </button>
                </div>
              )}

              {isFailed && (
                <button
                  onClick={() => { setJob(null); setSubmitError(null) }}
                  className="mt-3 w-full py-2 rounded-lg text-xs font-semibold text-slate-400 hover:text-slate-200 transition-colors border border-slate-700"
                >
                  Try again
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
