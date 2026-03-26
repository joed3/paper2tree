import { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'
import { DAGNode } from '../types/dag'
import { useExpand } from './ExpandContext'

export interface ClaimNodeData extends DAGNode {
  isSelected: boolean
  isExpanded: boolean
  hiddenChildCount: number
}

const TYPE_DIMS: Record<string, { w: number; h: number }> = {
  root: { w: 240, h: 104 },
  primary: { w: 210, h: 92 },
  supporting: { w: 185, h: 84 },
  evidence: { w: 165, h: 78 },
}

export function getNodeDims(type: string) {
  return TYPE_DIMS[type] ?? TYPE_DIMS.supporting
}

function ClaimNodeInner({ data }: NodeProps<ClaimNodeData>) {
  const { id, label, type, visual, evaluation, isSelected, isExpanded, hiddenChildCount } = data
  const supportLevel = evaluation?.support_level
  const dims = getNodeDims(type)
  const { toggle } = useExpand()

  const showToggle = hiddenChildCount > 0 || isExpanded

  return (
    <div
      className="relative flex flex-col rounded-lg transition-shadow duration-150"
      style={{
        width: dims.w,
        height: dims.h,
        border: `${visual.border_width}px solid ${visual.color}`,
        backgroundColor: `${visual.color}12`,
        boxShadow: isSelected
          ? `0 0 0 3px #fff4, 0 0 16px ${visual.color}60`
          : `0 0 8px ${visual.color}20`,
        cursor: 'pointer',
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: '#475569', border: '2px solid #1e293b', width: 8, height: 8 }}
      />

      <div className="flex flex-col h-full p-2.5 gap-1.5 overflow-hidden">
        {/* header row */}
        <div className="flex items-center gap-1.5 shrink-0">
          <span
            className="text-[10px] font-mono font-semibold uppercase tracking-widest px-1.5 py-0.5 rounded"
            style={{ color: visual.color, backgroundColor: `${visual.color}22` }}
          >
            {type}
          </span>
          {supportLevel !== undefined && (
            <span
              className="text-[10px] font-mono font-semibold uppercase tracking-wide"
              style={{ color: visual.color }}
            >
              {supportLevel}
            </span>
          )}
          {showToggle && (
            <button
              className="ml-auto text-[10px] font-mono px-1.5 py-0.5 rounded leading-none transition-colors"
              style={{
                color: visual.color,
                backgroundColor: `${visual.color}20`,
                border: `1px solid ${visual.color}50`,
              }}
              onClick={(e) => {
                e.stopPropagation()
                toggle(id)
              }}
            >
              {isExpanded ? '−' : `+${hiddenChildCount}`}
            </button>
          )}
        </div>

        {/* label */}
        <p className="text-[11px] leading-[1.35] text-slate-200 overflow-hidden line-clamp-3 flex-1">
          {label}
        </p>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        style={{ background: '#475569', border: '2px solid #1e293b', width: 8, height: 8 }}
      />
    </div>
  )
}

export const ClaimNode = memo(ClaimNodeInner)
