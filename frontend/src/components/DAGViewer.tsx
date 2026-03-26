import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  Edge,
  MarkerType,
  Node,
  NodeTypes,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from 'reactflow'
import 'reactflow/dist/style.css'
import dagre from 'dagre'
import { DAGEdge, DAGNode, PaperDAG } from '../types/dag'
import { ClaimNode, ClaimNodeData, getNodeDims } from './ClaimNode'
import { ExpandContext } from './ExpandContext'

const nodeTypes: NodeTypes = { claim: ClaimNode }

// ─── helpers ──────────────────────────────────────────────────────────────────

function buildChildrenMap(edges: DAGEdge[]): Map<string, string[]> {
  const m = new Map<string, string[]>()
  for (const e of edges) {
    if (!m.has(e.source)) m.set(e.source, [])
    m.get(e.source)!.push(e.target)
  }
  return m
}

function computeVisibleIds(
  nodes: DAGNode[],
  childrenMap: Map<string, string[]>,
  expandedIds: Set<string>,
): Set<string> {
  // Root and primary nodes always visible
  const visible = new Set(nodes.filter((n) => n.depth <= 1).map((n) => n.id))

  // BFS: add descendants of each expanded node that is itself visible
  const queue = [...expandedIds].filter((id) => visible.has(id))
  while (queue.length) {
    const id = queue.shift()!
    for (const child of childrenMap.get(id) ?? []) {
      if (!visible.has(child)) {
        visible.add(child)
        if (expandedIds.has(child)) queue.push(child)
      }
    }
  }
  return visible
}

const DAGRE_OPTS = { rankdir: 'LR', ranksep: 80, nodesep: 32, marginx: 60, marginy: 60 } as const

function buildLayout(
  rawNodes: DAGNode[],
  rawEdges: DAGEdge[],
  selectedId: string | null,
  visibleIds: Set<string>,
  childrenMap: Map<string, string[]>,
  expandedIds: Set<string>,
): { nodes: Node<ClaimNodeData>[]; edges: Edge[] } {
  const visNodes = rawNodes.filter((n) => visibleIds.has(n.id))
  const visEdges = rawEdges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))

  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph(DAGRE_OPTS)
  visNodes.forEach((n) => {
    const { w, h } = getNodeDims(n.type)
    g.setNode(n.id, { width: w, height: h })
  })
  visEdges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)

  const nodes: Node<ClaimNodeData>[] = visNodes.map((n) => {
    const { x, y, width, height } = g.node(n.id)
    const children = childrenMap.get(n.id) ?? []
    const hiddenChildCount = children.filter((c) => !visibleIds.has(c)).length
    return {
      id: n.id,
      type: 'claim',
      position: { x: x - width / 2, y: y - height / 2 },
      data: { ...n, isSelected: n.id === selectedId, isExpanded: expandedIds.has(n.id), hiddenChildCount },
      draggable: true,
    }
  })

  const edges: Edge[] = visEdges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.relationship,
    animated: e.relationship === 'contradicts',
    style: {
      stroke:
        e.relationship === 'contradicts' ? '#ef4444' : e.relationship === 'qualifies' ? '#eab308' : '#475569',
      strokeDasharray:
        e.relationship === 'contradicts' ? '6 3' : e.relationship === 'qualifies' ? '4 2' : undefined,
    },
    labelStyle: { fill: '#94a3b8', fontSize: 9, fontFamily: 'JetBrains Mono, monospace' },
    labelBgStyle: { fill: '#1e293b', fillOpacity: 0.85 },
    labelBgPadding: [3, 5] as [number, number],
    labelBgBorderRadius: 3,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color:
        e.relationship === 'contradicts' ? '#ef4444' : e.relationship === 'qualifies' ? '#eab308' : '#475569',
    },
  }))

  return { nodes, edges }
}

// ─── full-graph inset ─────────────────────────────────────────────────────────

interface InsetNode { id: string; x: number; y: number; w: number; h: number; color: string }
interface InsetEdge { x1: number; y1: number; x2: number; y2: number }

function buildFullLayout(
  rawNodes: DAGNode[],
  rawEdges: DAGEdge[],
): { nodes: InsetNode[]; edges: InsetEdge[]; bbox: { x: number; y: number; w: number; h: number } } {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ ...DAGRE_OPTS, marginx: 20, marginy: 20 })
  rawNodes.forEach((n) => {
    const { w, h } = getNodeDims(n.type)
    g.setNode(n.id, { width: w, height: h })
  })
  rawEdges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)

  const nodes: InsetNode[] = rawNodes.map((n) => {
    const { x, y, width, height } = g.node(n.id)
    return { id: n.id, x: x - width / 2, y: y - height / 2, w: width, h: height, color: n.visual.color }
  })
  const edges: InsetEdge[] = rawEdges.map((e) => {
    const s = g.node(e.source)
    const t = g.node(e.target)
    return { x1: s.x, y1: s.y, x2: t.x, y2: t.y }
  })

  const xs = nodes.flatMap((n) => [n.x, n.x + n.w])
  const ys = nodes.flatMap((n) => [n.y, n.y + n.h])
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  return { nodes, edges, bbox: { x: minX, y: minY, w: Math.max(...xs) - minX, h: Math.max(...ys) - minY } }
}

const INSET_W = 156
const INSET_H = 220

function FullMapInset({
  nodes,
  edges,
  bbox,
  visibleIds,
}: {
  nodes: InsetNode[]
  edges: InsetEdge[]
  bbox: { x: number; y: number; w: number; h: number }
  visibleIds: Set<string>
}) {
  const pad = 10
  const scale = Math.min((INSET_W - pad * 2) / bbox.w, (INSET_H - pad * 2) / bbox.h)
  const ox = pad - bbox.x * scale
  const oy = pad - bbox.y * scale

  return (
    <div
      className="absolute top-4 left-4 z-10 rounded-lg overflow-hidden"
      style={{
        width: INSET_W,
        height: INSET_H,
        background: 'rgba(15,23,42,0.90)',
        border: '1px solid rgba(71,85,105,0.5)',
        backdropFilter: 'blur(4px)',
      }}
    >
      <svg width={INSET_W} height={INSET_H}>
        {edges.map((e, i) => (
          <line
            key={i}
            x1={e.x1 * scale + ox}
            y1={e.y1 * scale + oy}
            x2={e.x2 * scale + ox}
            y2={e.y2 * scale + oy}
            stroke="#334155"
            strokeWidth={0.75}
          />
        ))}
        {nodes.map((n) => {
          const visible = visibleIds.has(n.id)
          return (
            <rect
              key={n.id}
              x={n.x * scale + ox}
              y={n.y * scale + oy}
              width={Math.max(n.w * scale, 2)}
              height={Math.max(n.h * scale, 2)}
              rx={1.5}
              fill={n.color}
              fillOpacity={visible ? 0.55 : 0.1}
              stroke={n.color}
              strokeWidth={0.75}
              strokeOpacity={visible ? 0.85 : 0.25}
            />
          )
        })}
      </svg>
      <span className="absolute bottom-1.5 left-2 text-[9px] text-slate-600 font-mono uppercase tracking-widest pointer-events-none">
        all claims
      </span>
    </div>
  )
}

// ─── fit helper ───────────────────────────────────────────────────────────────

function FitOnLoad({ trigger }: { trigger: number }) {
  const { fitView } = useReactFlow()
  useEffect(() => {
    if (trigger > 0) setTimeout(() => fitView({ padding: 0.12, duration: 400 }), 50)
  }, [trigger, fitView])
  return null
}

// ─── main component ───────────────────────────────────────────────────────────

interface DAGViewerProps {
  data: PaperDAG
  selectedNodeId: string | null
  onNodeClick: (nodeId: string) => void
}

export function DAGViewer({ data, selectedNodeId, onNodeClick }: DAGViewerProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [fitTrigger, setFitTrigger] = useState(0)

  const toggle = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // Reset expansion and re-fit when a different paper is loaded
  useEffect(() => {
    setExpandedIds(new Set())
    setFitTrigger((t) => t + 1)
  }, [data])

  const childrenMap = useMemo(() => buildChildrenMap(data.dag.edges), [data])

  const fullLayout = useMemo(() => buildFullLayout(data.dag.nodes, data.dag.edges), [data])

  const visibleIds = useMemo(
    () => computeVisibleIds(data.dag.nodes, childrenMap, expandedIds),
    [data.dag.nodes, childrenMap, expandedIds],
  )

  const { nodes: layoutNodes, edges: layoutEdges } = useMemo(
    () => buildLayout(data.dag.nodes, data.dag.edges, selectedNodeId, visibleIds, childrenMap, expandedIds),
    // Rebuild layout when paper or visible set changes; selectedNodeId handled separately below
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, visibleIds],
  )

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutEdges)

  // Sync nodes and edges when layout changes (expansion toggles) — no re-fit
  useEffect(() => {
    setNodes(layoutNodes)
    setEdges(layoutEdges)
  }, [layoutNodes, layoutEdges, setNodes, setEdges])

  // Update selection highlight without re-laying out
  useEffect(() => {
    setNodes((nds) =>
      nds.map((n) => ({ ...n, data: { ...n.data, isSelected: n.id === selectedNodeId } })),
    )
  }, [selectedNodeId, setNodes])

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => onNodeClick(node.id),
    [onNodeClick],
  )

  const expandCtx = useMemo(() => ({ expandedIds, toggle }), [expandedIds, toggle])

  return (
    <ExpandContext.Provider value={expandCtx}>
      <div className="flex-1 h-full relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={handleNodeClick}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          minZoom={0.1}
          maxZoom={2}
          panOnScroll
          panOnDrag={false}
          zoomOnScroll={false}
          attributionPosition="bottom-right"
        >
          <Background variant={BackgroundVariant.Dots} color="#1e3a5f" gap={24} size={1} />
          <Controls showInteractive={false} />
          <FitOnLoad trigger={fitTrigger} />
        </ReactFlow>
        <FullMapInset
          nodes={fullLayout.nodes}
          edges={fullLayout.edges}
          bbox={fullLayout.bbox}
          visibleIds={visibleIds}
        />
      </div>
    </ExpandContext.Provider>
  )
}
