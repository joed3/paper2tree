import { useCallback, useEffect, useMemo, useState } from 'react'
import { ReactFlowProvider } from 'reactflow'
import { PaperDAG } from './types/dag'
import { DAGViewer, buildFullLayout, FullMapInset } from './components/DAGViewer'
import { FinalReviewPanel } from './components/FinalReviewPanel'
import { NodeCard } from './components/NodeCard'
import { PDFPanel } from './components/PDFPanel'
import { EvalBadge } from './components/EvalBadge'

// pdf_data_url is injected at export time — not part of the dag.json schema
interface ExportPaperDAG extends PaperDAG {
  pdf_data_url?: string
}

declare global {
  interface Window {
    __PAPER_DATA__: ExportPaperDAG | null
  }
}

function ScorePip({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-xs font-mono text-slate-200 font-semibold">{value}</span>
      <span className="text-[10px] text-slate-600 uppercase tracking-wide">{label}</span>
    </div>
  )
}

export default function ExportApp() {
  const [paper, setPaper] = useState<ExportPaperDAG | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [pdfPanelOpen, setPdfPanelOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const data = window.__PAPER_DATA__
    if (!data) {
      setError('No paper data found. This file may not have been exported correctly.')
      return
    }
    document.title = `paper2tree — ${data.paper.title}`
    setPaper(data)
  }, [])

  const handleNodeClick = useCallback((nodeId: string) => {
    const isDeselecting = selectedNodeId === nodeId
    setSelectedNodeId(isDeselecting ? null : nodeId)
    if (!isDeselecting && paper?.pdf_data_url && !pdfPanelOpen) {
      setPdfPanelOpen(true)
    }
  }, [selectedNodeId, paper?.pdf_data_url, pdfPanelOpen])

  const selectedNode = paper?.dag.nodes.find((n) => n.id === selectedNodeId) ?? null
  const pdfUrl = paper?.pdf_data_url ?? null
  const showPDFPanel = pdfPanelOpen && !!selectedNode && !!pdfUrl

  const dagInsetLayout = useMemo(
    () => (paper ? buildFullLayout(paper.dag.nodes, paper.dag.edges) : null),
    [paper],
  )
  const allNodeIds = useMemo(
    () => new Set(paper?.dag.nodes.map((n) => n.id) ?? []),
    [paper],
  )

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-950">
        <p className="text-sm text-red-400 max-w-sm text-center leading-relaxed">{error}</p>
      </div>
    )
  }

  if (!paper) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-950">
        <div className="w-6 h-6 border-2 border-slate-600 border-t-slate-300 rounded-full animate-spin" />
      </div>
    )
  }

  const overallBadgeLevel =
    paper.summary.high_support_nodes / paper.summary.total_nodes >= 0.6
      ? ('high' as const)
      : paper.summary.low_support_nodes / paper.summary.total_nodes >= 0.5
        ? ('low' as const)
        : ('medium' as const)

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-950">
      {/* top bar */}
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
          <EvalBadge support_level={overallBadgeLevel} />
          <ScorePip value={paper.summary.total_nodes} label="claims" />
          <ScorePip value={paper.summary.total_edges} label="edges" />
          <ScorePip value={paper.summary.max_depth} label="depth" />
          <ScorePip
            value={`${paper.summary.high_support_nodes}/${paper.summary.total_nodes}`}
            label="high support"
          />
        </div>
        {/* watermark */}
        <a
          href="https://github.com/anthropics/paper2tree"
          target="_blank"
          rel="noreferrer"
          className="shrink-0 ml-2 text-[10px] font-mono text-slate-600 hover:text-slate-400 transition-colors"
        >
          paper2tree
        </a>
      </div>

      {/* main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* center: PDF (when open) or DAG canvas */}
        <div className="flex-1 flex overflow-hidden relative">
          {/* PDF panel — fills center when open */}
          {showPDFPanel && pdfUrl && (
            <PDFPanel
              pdfUrl={pdfUrl}
              nodes={paper.dag.nodes}
              selectedNodeId={selectedNodeId}
              onNodeSelect={setSelectedNodeId}
              onClose={() => setPdfPanelOpen(false)}
            />
          )}

          {/* Clickable DAG mini-map inset — pinned to top-left while PDF is open */}
          {showPDFPanel && dagInsetLayout && (
            <FullMapInset
              nodes={dagInsetLayout.nodes}
              edges={dagInsetLayout.edges}
              bbox={dagInsetLayout.bbox}
              visibleIds={allNodeIds}
              selectedNodeId={selectedNodeId}
              onClick={() => setPdfPanelOpen(false)}
              label="← DAG"
              className="absolute top-4 left-4 z-30"
            />
          )}

          {/* DAG hidden (not unmounted) while PDF is open to preserve pan/zoom state */}
          <div className={`flex-1 flex flex-col overflow-hidden relative ${showPDFPanel ? 'hidden' : ''}`}>
            <ReactFlowProvider>
              <DAGViewer
                data={paper}
                selectedNodeId={selectedNodeId}
                onNodeClick={handleNodeClick}
              />
            </ReactFlowProvider>

            {/* overall assessment banner */}
            {paper.summary.overall_assessment && (
              <div className="absolute bottom-0 left-0 right-0 px-4 py-2 bg-slate-900/80 backdrop-blur-sm border-t border-slate-700/50 z-10">
                <p className="text-[10px] text-slate-400 leading-relaxed line-clamp-2">
                  <span className="text-slate-600 uppercase tracking-widest mr-2">Assessment</span>
                  {paper.summary.overall_assessment}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* right panel: node card when a node is selected; final review otherwise */}
        {selectedNode ? (
          <NodeCard
            node={selectedNode}
            onClose={() => setSelectedNodeId(null)}
            pdfAvailable={!!pdfUrl}
            pdfPanelOpen={showPDFPanel}
            onTogglePDF={() => setPdfPanelOpen((v) => !v)}
          />
        ) : paper.final_review ? (
          <FinalReviewPanel review={paper.final_review} />
        ) : null}
      </div>
    </div>
  )
}
