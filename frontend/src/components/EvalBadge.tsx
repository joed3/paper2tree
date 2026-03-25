interface EvalBadgeProps {
  support_level: 'high' | 'medium' | 'low'
  size?: 'sm' | 'md'
}

const LEVEL_COLOR: Record<string, string> = {
  high: '#22c55e',
  medium: '#eab308',
  low: '#ef4444',
}

export function EvalBadge({ support_level, size = 'md' }: EvalBadgeProps) {
  const color = LEVEL_COLOR[support_level]

  const textClass = size === 'sm' ? 'text-xs' : 'text-sm'
  const padClass = size === 'sm' ? 'px-1.5 py-0.5' : 'px-2 py-1'

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono rounded ${textClass} ${padClass} font-medium`}
      style={{ color, backgroundColor: `${color}20`, border: `1px solid ${color}40` }}
    >
      <span
        className="inline-block w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: color }}
      />
      {support_level}
    </span>
  )
}
