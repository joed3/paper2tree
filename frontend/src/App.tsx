import { useCallback, useState } from 'react'
import { ReactFlowProvider } from 'reactflow'
import { Job } from './api/jobs'
import { deletePaper } from './api/papers'
import { PaperIndexEntry } from './types/dag'
import { usePaperIndex } from './hooks/usePaperIndex'
import { usePaper } from './hooks/usePaper'
import { useJobs } from './hooks/useJobs'
import { PaperBrowser } from './components/PaperBrowser'
import { DAGViewer } from './components/DAGViewer'
import { NodeCard } from './components/NodeCard'
import { EvalBadge } from './components/EvalBadge'
import { AddPaperDialog } from './components/AddPaperDialog'
import { JobProgressView } from './components/JobProgressView'

function ScorePip({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-xs font-mono text-slate-200 font-semibold">{value}</span>
      <span className="text-[10px] text-slate-600 uppercase tracking-wide">{label}</span>
    </div>
  )
}

export default function App() {
  const { papers, loading: indexLoading, error: indexError, refresh } = usePaperIndex()
  const [selectedEntry, setSelectedEntry] = useState<PaperIndexEntry | null>(null)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [showAddDialog, setShowAddDialog] = useState(false)

  const handleJobComplete = useCallback(
    async (job: Job) => {
      if (!job.paper_id) return
      const updated = await refresh()
      // Auto-switch to the paper if this was the selected job
      setSelectedJobId((cur) => {
        if (cur === job.job_id) {
          const entry = updated.find((p) => p.paper_id === job.paper_id)
          if (entry) {
            setSelectedEntry(entry)
            setSelectedNodeId(null)
          }
          return null
        }
        return cur
      })
    },
    [refresh],
  )

  const { jobs, addJob, removeJob } = useJobs(handleJobComplete)

  const { paper, loading: paperLoading } = usePaper(
    selectedEntry?.result_path ?? null,
  )

  const selectedNode = paper?.dag.nodes.find((n) => n.id === selectedNodeId) ?? null
  const selectedJob = jobs.find((j) => j.job_id === selectedJobId) ?? null

  function handleSelectPaper(entry: PaperIndexEntry) {
    setSelectedEntry(entry)
    setSelectedJobId(null)
    setSelectedNodeId(null)
  }

  function handleSelectJob(jobId: string) {
    setSelectedJobId(jobId)
    setSelectedEntry(null)
    setSelectedNodeId(null)
  }

  function handleNodeClick(nodeId: string) {
    setSelectedNodeId((prev) => (prev === nodeId ? null : nodeId))
  }

  const handleJobSubmitted = useCallback(
    (job: Job) => {
      addJob(job)
      setSelectedJobId(job.job_id)
      setSelectedEntry(null)
      setSelectedNodeId(null)
      setShowAddDialog(false)
    },
    [addJob],
  )

  const handleDismissJob = useCallback(
    (jobId: string) => {
      removeJob(jobId)
      if (selectedJobId === jobId) setSelectedJobId(null)
    },
    [removeJob, selectedJobId],
  )

  const handleDeletePaper = useCallback(
    async (paperId: string) => {
      if (!window.confirm('Delete this paper and all its review artifacts?')) return
      try {
        await deletePaper(paperId)
        if (selectedEntry?.paper_id === paperId) {
          setSelectedEntry(null)
          setSelectedNodeId(null)
        }
        await refresh()
      } catch (e) {
        window.alert(`Delete failed: ${(e as Error).message}`)
      }
    },
    [selectedEntry, refresh],
  )

  const showDAG = !!paper && !paperLoading && !selectedJobId
  const showJobProgress = !!selectedJobId
  const showEmpty = !selectedEntry && !selectedJobId && !paperLoading

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-950">
      {/* top bar — only when a paper is loaded */}
      {paper && !selectedJobId && (
        <div className="flex items-center px-4 py-2 bg-slate-900 border-b border-slate-700 shrink-0 gap-4">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-slate-100 truncate">{paper.paper.title}</p>
            <p className="text-[11px] text-slate-500 truncate">
              {paper.paper.authors.join(', ')}
              {paper.paper.url && !paper.paper.url.startsWith('upload://') && (
                <>
                  {' '}
                  ·{' '}
                  <a
                    href={paper.paper.url}
                    target="_blank"
                    rel="noreferrer"
                    className="hover:text-slate-300 transition-colors underline underline-offset-2"
                  >
                    source
                  </a>
                </>
              )}
            </p>
          </div>
          <div className="flex items-center gap-5 shrink-0">
            <EvalBadge
              support_level={
                paper.summary.high_support_nodes / paper.summary.total_nodes >= 0.6
                  ? 'high'
                  : paper.summary.low_support_nodes / paper.summary.total_nodes >= 0.5
                    ? 'low'
                    : 'medium'
              }
            />
            <ScorePip value={paper.summary.total_nodes} label="claims" />
            <ScorePip value={paper.summary.total_edges} label="edges" />
            <ScorePip value={paper.summary.max_depth} label="depth" />
            <ScorePip
              value={`${paper.summary.high_support_nodes}/${paper.summary.total_nodes}`}
              label="high support"
            />
          </div>
          <a
            href={`/api/papers/${paper.paper.paper_id}/export`}
            download
            className="shrink-0 px-3 py-1.5 rounded text-[11px] font-semibold border border-slate-600 text-slate-400 hover:text-slate-200 hover:border-slate-400 transition-colors"
            title="Download self-contained interactive HTML"
          >
            Export
          </a>
        </div>
      )}

      {/* main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* left: paper browser */}
        <PaperBrowser
          papers={papers}
          jobs={jobs}
          selectedId={selectedEntry?.paper_id ?? null}
          selectedJobId={selectedJobId}
          onSelect={handleSelectPaper}
          onSelectJob={handleSelectJob}
          onDismissJob={handleDismissJob}
          onDeletePaper={handleDeletePaper}
          onAddPaper={() => setShowAddDialog(true)}
          loading={indexLoading}
          error={indexError}
        />

        {/* center: DAG, job progress, or empty state */}
        <div className="flex-1 flex flex-col overflow-hidden relative">
          {paperLoading && !selectedJobId && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-950 z-10">
              <div className="flex flex-col items-center gap-3">
                <div className="w-6 h-6 border-2 border-slate-600 border-t-slate-300 rounded-full animate-spin" />
                <p className="text-xs text-slate-500 font-mono">Loading DAG…</p>
              </div>
            </div>
          )}

          {showEmpty && (
            <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-8">
              <div className="text-5xl opacity-20">⬡</div>
              <p className="text-sm text-slate-500 max-w-xs leading-relaxed">
                Select a paper from the sidebar to view its claim DAG.
              </p>
              {papers.length === 0 && jobs.length === 0 && !indexLoading && (
                <button
                  onClick={() => setShowAddDialog(true)}
                  className="mt-2 px-4 py-2 rounded-lg text-xs font-semibold transition-colors border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500"
                >
                  + Add your first paper
                </button>
              )}
            </div>
          )}

          {showDAG && (
            <ReactFlowProvider>
              <DAGViewer
                data={paper}
                selectedNodeId={selectedNodeId}
                onNodeClick={handleNodeClick}
              />
            </ReactFlowProvider>
          )}

          {showJobProgress && (
            <JobProgressView
              job={selectedJob}
              onDismiss={() => handleDismissJob(selectedJobId)}
            />
          )}

          {/* overall assessment banner */}
          {paper && !selectedJobId && paper.summary.overall_assessment && (
            <div className="absolute bottom-0 left-0 right-0 px-4 py-2 bg-slate-900/80 backdrop-blur-sm border-t border-slate-700/50 z-10">
              <p className="text-[10px] text-slate-400 leading-relaxed line-clamp-2">
                <span className="text-slate-600 uppercase tracking-widest mr-2">Assessment</span>
                {paper.summary.overall_assessment}
              </p>
            </div>
          )}
        </div>

        {/* right: node card slide-in */}
        {selectedNode && !selectedJobId && (
          <NodeCard node={selectedNode} onClose={() => setSelectedNodeId(null)} />
        )}
      </div>

      {/* add paper modal */}
      {showAddDialog && (
        <AddPaperDialog
          onClose={() => setShowAddDialog(false)}
          onSubmitted={handleJobSubmitted}
        />
      )}
    </div>
  )
}
