import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  Edge,
  MarkerType,
  MiniMap,
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

const nodeTypes: NodeTypes = { claim: ClaimNode }

function buildLayout(
  rawNodes: DAGNode[],
  rawEdges: DAGEdge[],
  selectedId: string | null,
): { nodes: Node<ClaimNodeData>[]; edges: Edge[] } {
  // dagre graph
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'TB', ranksep: 80, nodesep: 40, marginx: 60, marginy: 60 })

  rawNodes.forEach((n) => {
    const { w, h } = getNodeDims(n.type)
    g.setNode(n.id, { width: w, height: h })
  })
  rawEdges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)

  const nodes: Node<ClaimNodeData>[] = rawNodes.map((n) => {
    const { x, y, width, height } = g.node(n.id)
    return {
      id: n.id,
      type: 'claim',
      position: { x: x - width / 2, y: y - height / 2 },
      data: { ...n, isSelected: n.id === selectedId },
      draggable: true,
    }
  })

  const edges: Edge[] = rawEdges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.relationship,
    className: e.relationship,
    animated: e.relationship === 'contradicts',
    style: {
      stroke:
        e.relationship === 'contradicts'
          ? '#ef4444'
          : e.relationship === 'qualifies'
            ? '#eab308'
            : '#475569',
      strokeDasharray:
        e.relationship === 'contradicts'
          ? '6 3'
          : e.relationship === 'qualifies'
            ? '4 2'
            : undefined,
    },
    labelStyle: { fill: '#94a3b8', fontSize: 9, fontFamily: 'JetBrains Mono, monospace' },
    labelBgStyle: { fill: '#1e293b', fillOpacity: 0.85 },
    labelBgPadding: [3, 5] as [number, number],
    labelBgBorderRadius: 3,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color:
        e.relationship === 'contradicts'
          ? '#ef4444'
          : e.relationship === 'qualifies'
            ? '#eab308'
            : '#475569',
    },
  }))

  return { nodes, edges }
}

interface FitViewInner {
  run: () => void
}

function FitOnLoad({ trigger }: { trigger: number }) {
  const { fitView } = useReactFlow()
  useEffect(() => {
    if (trigger > 0) {
      setTimeout(() => fitView({ padding: 0.1, duration: 400 }), 50)
    }
  }, [trigger, fitView])
  return null
}

interface DAGViewerProps {
  data: PaperDAG
  selectedNodeId: string | null
  onNodeClick: (nodeId: string) => void
}

export function DAGViewer({ data, selectedNodeId, onNodeClick }: DAGViewerProps) {
  const [fitTrigger, setFitTrigger] = useState(0)

  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => buildLayout(data.dag.nodes, data.dag.edges, selectedNodeId),
    // Rebuild layout only when paper changes (not on every node selection)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data],
  )

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, , onEdgesChange] = useEdgesState(initialEdges)

  // Reset nodes when paper changes
  useEffect(() => {
    setNodes(initialNodes)
    setFitTrigger((t) => t + 1)
  }, [initialNodes, setNodes])

  // Update selection highlight without re-laying out
  useEffect(() => {
    setNodes((nds) =>
      nds.map((n) => ({
        ...n,
        data: { ...n.data, isSelected: n.id === selectedNodeId },
      })),
    )
  }, [selectedNodeId, setNodes])

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeClick(node.id)
    },
    [onNodeClick],
  )

  return (
    <div className="flex-1 h-full relative">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        minZoom={0.1}
        maxZoom={2}
        attributionPosition="bottom-right"
      >
        <Background variant={BackgroundVariant.Dots} color="#1e3a5f" gap={24} size={1} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => (n.data as ClaimNodeData).visual?.color ?? '#475569'}
          maskColor="rgba(15,23,42,0.7)"
          zoomable
          pannable
        />
        <FitOnLoad trigger={fitTrigger} />
      </ReactFlow>
    </div>
  )
}
