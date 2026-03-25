import { DAGNode } from '../types/dag'
import { EvalBadge } from './EvalBadge'

interface NodeCardProps {
  node: DAGNode | null
  onClose: () => void
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <h4 className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mb-1.5">
        {title}
      </h4>
      {children}
    </div>
  )
}

function BulletList({ items, color }: { items: string[]; color?: string }) {
  if (!items.length)
    return <p className="text-xs text-slate-600 italic">None noted.</p>
  return (
    <ul className="space-y-1">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2 text-xs text-slate-300 leading-relaxed">
          <span style={{ color: color ?? '#94a3b8' }} className="shrink-0 mt-0.5">
            ›
          </span>
          {item}
        </li>
      ))}
    </ul>
  )
}

const QUALITY_COLOR: Record<string, string> = {
  strong: '#22c55e',
  moderate: '#eab308',
  weak: '#f97316',
  absent: '#ef4444',
}

export function NodeCard({ node, onClose }: NodeCardProps) {
  if (!node) return null
  const ev = node.evaluation

  return (
    <div
      className="flex flex-col h-full bg-slate-900 border-l border-slate-700 overflow-hidden"
      style={{ width: 360 }}
    >
      {/* header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b shrink-0"
        style={{ borderColor: `${node.visual.color}40` }}
      >
        <div className="flex items-center gap-2">
          <span
            className="text-[10px] font-mono font-semibold uppercase tracking-widest px-2 py-0.5 rounded"
            style={{
              color: node.visual.color,
              backgroundColor: `${node.visual.color}20`,
              border: `1px solid ${node.visual.color}40`,
            }}
          >
            {node.type}
          </span>
          <span className="text-xs text-slate-500 font-mono">{node.id}</span>
        </div>
        <button
          onClick={onClose}
          className="text-slate-500 hover:text-slate-300 transition-colors text-lg leading-none px-1"
          aria-label="Close"
        >
          ×
        </button>
      </div>

      {/* scrollable body */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {/* claim text */}
        <Section title="Claim">
          <p className="text-sm text-slate-200 leading-relaxed">{node.claim}</p>
        </Section>

        {/* verbatim quote */}
        <Section title="Verbatim quote">
          <blockquote className="border-l-2 border-slate-600 pl-3 text-xs text-slate-400 italic leading-relaxed">
            "{node.verbatim_quote}"
          </blockquote>
        </Section>

        <div className="flex gap-4 mb-4">
          <div>
            <p className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mb-1">
              Source
            </p>
            <span className="text-xs text-slate-300 font-mono bg-slate-800 px-2 py-0.5 rounded">
              {node.section_source}
            </span>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mb-1">
              Depth
            </p>
            <span className="text-xs text-slate-300 font-mono bg-slate-800 px-2 py-0.5 rounded">
              {node.depth}
            </span>
          </div>
        </div>

        {ev ? (
          <>
            <div className="border-t border-slate-700 mb-4" />

            {/* scores */}
            <Section title="Support">
              <div className="flex items-center gap-3 flex-wrap">
                <EvalBadge support_level={ev.support_level} />
                <span className="text-xs text-slate-400">
                  confidence:{' '}
                  <span
                    className="font-semibold"
                    style={{
                      color:
                        ev.confidence_level === 'high'
                          ? '#22c55e'
                          : ev.confidence_level === 'medium'
                            ? '#eab308'
                            : '#ef4444',
                    }}
                  >
                    {ev.confidence_level}
                  </span>
                </span>
                <span className="text-xs text-slate-400">
                  evidence:{' '}
                  <span
                    className="font-semibold"
                    style={{ color: QUALITY_COLOR[ev.supporting_evidence_quality] }}
                  >
                    {ev.supporting_evidence_quality}
                  </span>
                </span>
              </div>
              {ev.is_well_supported && (
                <p className="text-xs text-slate-500 mt-2">✓ Well supported by the paper</p>
              )}
            </Section>

            <Section title="Strengths">
              <BulletList items={ev.strengths} color="#22c55e" />
            </Section>

            <Section title="Weaknesses">
              <BulletList items={ev.weaknesses} color="#ef4444" />
            </Section>

            {ev.alternative_interpretations.length > 0 && (
              <Section title="Alternative interpretations">
                <BulletList items={ev.alternative_interpretations} color="#a78bfa" />
              </Section>
            )}

            {ev.required_assumptions.length > 0 && (
              <Section title="Required assumptions">
                <BulletList items={ev.required_assumptions} color="#eab308" />
              </Section>
            )}

            {ev.notes && (
              <Section title="Evaluator notes">
                <p className="text-xs text-slate-400 leading-relaxed">{ev.notes}</p>
              </Section>
            )}
          </>
        ) : (
          <p className="text-xs text-slate-600 italic">No evaluation available for this node.</p>
        )}
      </div>
    </div>
  )
}
