import { useCallback, useState } from 'react'
import { ReactFlowProvider } from 'reactflow'
import { PaperIndexEntry } from './types/dag'
import { usePaperIndex } from './hooks/usePaperIndex'
import { usePaper } from './hooks/usePaper'
import { PaperBrowser } from './components/PaperBrowser'
import { DAGViewer } from './components/DAGViewer'
import { NodeCard } from './components/NodeCard'
import { EvalBadge } from './components/EvalBadge'
import { AddPaperDialog } from './components/AddPaperDialog'

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
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [showAddDialog, setShowAddDialog] = useState(false)

  const { paper, loading: paperLoading } = usePaper(selectedEntry?.result_path ?? null)

  const selectedNode = paper?.dag.nodes.find((n) => n.id === selectedNodeId) ?? null

  function handleSelectPaper(entry: PaperIndexEntry) {
    setSelectedEntry(entry)
    setSelectedNodeId(null)
  }

  function handleNodeClick(nodeId: string) {
    setSelectedNodeId((prev) => (prev === nodeId ? null : nodeId))
  }

  // Called when a job finishes: refresh the index then auto-select the new paper
  const handleJobDone = useCallback(
    async (paperId: string) => {
      const updated = await refresh()
      const entry = updated.find((p) => p.paper_id === paperId)
      if (entry) {
        setSelectedEntry(entry)
        setSelectedNodeId(null)
      }
      setShowAddDialog(false)
    },
    [refresh],
  )

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-950">
      {/* top bar — only when a paper is loaded */}
      {paper && (
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
        </div>
      )}

      {/* main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* left: paper browser */}
        <PaperBrowser
          papers={papers}
          selectedId={selectedEntry?.paper_id ?? null}
          onSelect={handleSelectPaper}
          onAddPaper={() => setShowAddDialog(true)}
          loading={indexLoading}
          error={indexError}
        />

        {/* center: DAG or empty state */}
        <div className="flex-1 flex flex-col overflow-hidden relative">
          {paperLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-950 z-10">
              <div className="flex flex-col items-center gap-3">
                <div className="w-6 h-6 border-2 border-slate-600 border-t-slate-300 rounded-full animate-spin" />
                <p className="text-xs text-slate-500 font-mono">Loading DAG…</p>
              </div>
            </div>
          )}

          {!selectedEntry && !paperLoading && (
            <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-8">
              <div className="text-5xl opacity-20">⬡</div>
              <p className="text-sm text-slate-500 max-w-xs leading-relaxed">
                Select a paper from the sidebar to view its claim DAG.
              </p>
              {papers.length === 0 && !indexLoading && (
                <button
                  onClick={() => setShowAddDialog(true)}
                  className="mt-2 px-4 py-2 rounded-lg text-xs font-semibold transition-colors border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500"
                >
                  + Add your first paper
                </button>
              )}
            </div>
          )}

          {paper && !paperLoading && (
            <ReactFlowProvider>
              <DAGViewer
                data={paper}
                selectedNodeId={selectedNodeId}
                onNodeClick={handleNodeClick}
              />
            </ReactFlowProvider>
          )}

          {/* overall assessment banner */}
          {paper && paper.summary.overall_assessment && (
            <div className="absolute bottom-0 left-0 right-0 px-4 py-2 bg-slate-900/80 backdrop-blur-sm border-t border-slate-700/50 z-10">
              <p className="text-[10px] text-slate-400 leading-relaxed line-clamp-2">
                <span className="text-slate-600 uppercase tracking-widest mr-2">Assessment</span>
                {paper.summary.overall_assessment}
              </p>
            </div>
          )}
        </div>

        {/* right: node card slide-in */}
        {selectedNode && (
          <NodeCard node={selectedNode} onClose={() => setSelectedNodeId(null)} />
        )}
      </div>

      {/* add paper modal */}
      {showAddDialog && (
        <AddPaperDialog onClose={() => setShowAddDialog(false)} onDone={handleJobDone} />
      )}
    </div>
  )
}
