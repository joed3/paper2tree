import { Job } from '../api/jobs'

const STEP_LABELS = ['Fetch', 'Extract text', 'Extract claims', 'Build DAG', 'Evaluate claims', 'Generate review', 'Write output']
const STEP_PREFIXES = ['[1/7]', '[2/7]', '[3/7]', '[4/7]', '[5/7]', '[6/7]', '[7/7]']

function currentStepIndex(step: string): number {
  const i = STEP_PREFIXES.findIndex((p) => step.startsWith(p))
  return i
}

function ProgressSteps({ step, status }: { step: string; status: Job['status'] }) {
  const current = currentStepIndex(step)
  return (
    <div className="flex items-center gap-0">
      {STEP_LABELS.map((label, i) => {
        const done = status === 'done' || current > i
        const active = current === i && status === 'running'
        const failed = status === 'error' && current === i
        return (
          <div key={i} className="flex items-center flex-1 min-w-0">
            <div className="flex flex-col items-center">
              <div
                className="w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-mono font-bold shrink-0 transition-colors"
                style={{
                  backgroundColor: failed ? '#ef4444' : done ? '#22c55e' : active ? '#3b82f6' : '#1e293b',
                  border: `1px solid ${failed ? '#ef444480' : done ? '#22c55e80' : active ? '#3b82f680' : '#334155'}`,
                  color: done || active || failed ? '#fff' : '#475569',
                }}
              >
                {done ? '✓' : failed ? '✕' : i + 1}
              </div>
              <span
                className="text-[9px] font-mono mt-1 text-center leading-tight"
                style={{
                  color: done ? '#22c55e' : active ? '#93c5fd' : failed ? '#ef4444' : '#475569',
                  maxWidth: 52,
                  wordBreak: 'break-word',
                }}
              >
                {label}
              </span>
            </div>
            {i < STEP_LABELS.length - 1 && (
              <div
                className="flex-1 h-px mx-1 mb-5 transition-colors"
                style={{ backgroundColor: i < current || status === 'done' ? '#22c55e40' : '#1e293b' }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

interface JobProgressViewProps {
  job: Job | null
  onDismiss: () => void
}

export function JobProgressView({ job, onDismiss }: JobProgressViewProps) {
  if (!job) return null

  const isRunning = job.status === 'queued' || job.status === 'running'
  const isFailed = job.status === 'error'

  return (
    <div className="flex flex-col items-center justify-center h-full bg-slate-950 px-8">
      <div className="w-full max-w-xl">
        {/* source */}
        <div className="mb-8 text-center">
          <p className="text-[10px] uppercase tracking-widest text-slate-600 font-mono mb-1.5">
            {isRunning ? 'Processing' : isFailed ? 'Failed' : 'Complete'}
          </p>
          <p className="text-sm text-slate-300 font-mono break-all leading-relaxed">{job.source}</p>
        </div>

        {/* step progress */}
        <ProgressSteps step={job.step} status={job.status} />

        {/* current step text */}
        <p
          className="text-xs font-mono mt-6 text-center"
          style={{ color: isFailed ? '#f87171' : isRunning ? '#93c5fd' : '#4ade80' }}
        >
          {job.step}
        </p>

        {/* error detail */}
        {isFailed && job.error && (
          <div className="mt-4 bg-red-950/40 border border-red-900/60 rounded-lg px-4 py-3">
            <p className="text-xs text-red-400 font-mono break-words leading-relaxed">{job.error}</p>
          </div>
        )}

        {/* dismiss */}
        {isFailed && (
          <button
            onClick={onDismiss}
            className="mt-5 w-full py-2 rounded-lg text-xs font-semibold text-slate-400 hover:text-slate-200 transition-colors border border-slate-700"
          >
            Dismiss
          </button>
        )}

        {/* running spinner */}
        {isRunning && (
          <div className="flex justify-center mt-6">
            <div className="w-5 h-5 border-2 border-slate-700 border-t-blue-400 rounded-full animate-spin" />
          </div>
        )}
      </div>
    </div>
  )
}
