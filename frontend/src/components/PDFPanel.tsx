import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Document, Page } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'
import type { DAGNode } from '../types/dag'

type CustomTextRenderer = (props: {
  str: string
  pageIndex: number
  pageNumber: number
  itemIndex: number
}) => string

const PAGE_WIDTH = 560

interface PDFPanelProps {
  pdfUrl: string
  nodes: DAGNode[]
  selectedNodeId: string | null
  onNodeSelect: (nodeId: string) => void
  onClose: () => void
}

function buildHighlightTerms(quote: string | null): Set<string> {
  if (!quote) return new Set()
  return new Set(
    quote
      .split(/\s+/)
      .map((w) => w.toLowerCase().replace(/[^a-z0-9]/g, ''))
      .filter((w) => w.length >= 6),
  )
}

export function PDFPanel({ pdfUrl, nodes, selectedNodeId, onNodeSelect, onClose }: PDFPanelProps) {
  const [numPages, setNumPages] = useState(0)
  const [originalWidth, setOriginalWidth] = useState(0)
  const pageRefs = useRef<(HTMLDivElement | null)[]>([])

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null
  const selectedPage = selectedNode?.page_number ?? null  // 0-indexed

  // Group nodes by page index for efficient per-page highlight rendering
  const nodesByPage = useMemo(() => {
    const map = new Map<number, DAGNode[]>()
    for (const node of nodes) {
      if (node.page_number != null && node.bbox && node.bbox.length > 0) {
        const arr = map.get(node.page_number) ?? []
        arr.push(node)
        map.set(node.page_number, arr)
      }
    }
    return map
  }, [nodes])

  // Text-search fallback: only for the selected node when it has no bbox coords
  const selectedHasNoCoords = !selectedNode?.bbox || selectedNode.bbox.length === 0
  const highlightTerms = useMemo(
    () => buildHighlightTerms(selectedHasNoCoords ? (selectedNode?.verbatim_quote ?? null) : null),
    [selectedNode, selectedHasNoCoords],
  )
  const hasTextHighlight = selectedHasNoCoords && highlightTerms.size > 0
  const quoteLower = selectedNode?.verbatim_quote?.toLowerCase() ?? ''

  const customTextRenderer: CustomTextRenderer = useCallback(
    ({ str }: { str: string }) => {
      const strLower = str.toLowerCase().replace(/[^a-z0-9]/g, '')
      const isMatch =
        strLower.length >= 6 &&
        (highlightTerms.has(strLower) ||
          (quoteLower.length > 0 && quoteLower.includes(str.toLowerCase())))
      return isMatch
        ? `<mark style="background:rgba(250,204,21,0.45);border-radius:2px;padding:0">${str}</mark>`
        : str
    },
    [highlightTerms, quoteLower],
  )

  const scale = originalWidth > 0 ? PAGE_WIDTH / originalWidth : 1

  const handleLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages)
  }, [])

  // Reset scale when a different PDF is loaded
  useEffect(() => {
    setOriginalWidth(0)
    setNumPages(0)
  }, [pdfUrl])

  const handleFirstPageLoadSuccess = useCallback((page: { originalWidth: number }) => {
    setOriginalWidth(page.originalWidth)
  }, [])

  // Scroll to the selected node's page whenever selection or document changes
  useEffect(() => {
    if (numPages === 0 || selectedPage === null) return
    const ref = pageRefs.current[selectedPage]
    ref?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [numPages, selectedPage, pdfUrl])

  return (
    <div className="flex flex-col h-full flex-1 bg-slate-900 overflow-hidden">
      {/* header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-700 shrink-0 gap-3">
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-200 transition-colors text-[11px] font-mono shrink-0 flex items-center gap-1"
          aria-label="Back to DAG"
        >
          ← DAG
        </button>
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500 shrink-0">
            PDF source
          </span>
          {selectedPage !== null && (
            <span className="text-[10px] font-mono text-slate-600">p.{selectedPage + 1}</span>
          )}
          {hasTextHighlight && (
            <span className="text-[10px] font-mono text-yellow-700 shrink-0">text search</span>
          )}
        </div>
        <div className="w-16" />
      </div>

      {/* scrollable continuous PDF */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden bg-slate-950 py-4">
        <Document
          file={pdfUrl}
          onLoadSuccess={handleLoadSuccess}
          loading={
            <div className="flex items-center justify-center h-48 text-slate-500 text-xs font-mono">
              Loading PDF…
            </div>
          }
          error={
            <div className="flex items-center justify-center h-48 text-slate-500 text-xs font-mono">
              Failed to load PDF.
            </div>
          }
        >
          {Array.from({ length: numPages }, (_, i) => {
            const pageNum = i + 1       // react-pdf 1-indexed
            const pageIndex = i         // our 0-indexed
            const isSelectedPage = pageIndex === selectedPage
            const pageNodes = nodesByPage.get(pageIndex) ?? []
            const showTextHighlight = isSelectedPage && hasTextHighlight

            return (
              <div
                key={pageNum}
                ref={(el) => { pageRefs.current[pageIndex] = el }}
                className="flex justify-center mb-4"
              >
                <div className="relative">
                  <Page
                    pageNumber={pageNum}
                    width={PAGE_WIDTH}
                    renderTextLayer={showTextHighlight}
                    renderAnnotationLayer={false}
                    customTextRenderer={showTextHighlight ? customTextRenderer : undefined}
                    onLoadSuccess={pageNum === 1 ? handleFirstPageLoadSuccess : undefined}
                    loading={
                      <div
                        style={{ width: PAGE_WIDTH, height: PAGE_WIDTH * 1.41 }}
                        className="flex items-center justify-center text-slate-700 text-xs font-mono"
                      >
                        {pageNum}
                      </div>
                    }
                  />

                  {/* Coordinate highlights — one div per rect per node on this page */}
                  {originalWidth > 0 &&
                    pageNodes.map((node) => {
                      const isSelected = node.id === selectedNodeId
                      return node.bbox!.map(([x0, y0, x1, y1], rectIdx) => (
                        <div
                          key={`${node.id}-${rectIdx}`}
                          className="absolute pointer-events-auto rounded-sm"
                          style={{
                            left: x0 * scale,
                            top: y0 * scale,
                            width: Math.max((x1 - x0) * scale, 4),
                            height: Math.max((y1 - y0) * scale, 4),
                            backgroundColor: isSelected
                              ? 'rgba(250, 204, 21, 0.35)'
                              : 'rgba(250, 204, 21, 0.12)',
                            border: `1.5px solid ${isSelected ? 'rgba(250,204,21,0.85)' : 'rgba(250,204,21,0.35)'}`,
                            boxShadow: isSelected ? '0 0 0 2px rgba(250,204,21,0.12)' : 'none',
                            cursor: isSelected ? 'default' : 'pointer',
                          }}
                          onClick={isSelected ? undefined : () => onNodeSelect(node.id)}
                          title={isSelected ? undefined : node.label}
                        />
                      ))
                    })}
                </div>
              </div>
            )
          })}
        </Document>
      </div>
    </div>
  )
}
