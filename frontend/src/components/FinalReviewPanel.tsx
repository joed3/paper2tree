import type { ReactNode } from 'react'

interface Props {
  review: string
}

function renderReview(text: string): ReactNode[] {
  const elements: ReactNode[] = []
  let key = 0

  for (const line of text.split('\n')) {
    const trimmed = line.trim()

    // **Section Header**
    if (trimmed.startsWith('**') && trimmed.endsWith('**') && trimmed.length > 4) {
      const heading = trimmed.slice(2, -2)
      elements.push(
        <h3
          key={key++}
          className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mt-5 mb-1.5 first:mt-0"
        >
          {heading}
        </h3>,
      )
      continue
    }

    // - Bullet item
    if (trimmed.startsWith('- ')) {
      elements.push(
        <div key={key++} className="flex gap-2 text-xs text-slate-300 leading-relaxed mb-1">
          <span className="text-slate-600 shrink-0 mt-0.5">·</span>
          <span>{trimmed.slice(2)}</span>
        </div>,
      )
      continue
    }

    // Empty line
    if (trimmed === '') {
      elements.push(<div key={key++} className="h-1" />)
      continue
    }

    // Regular paragraph
    elements.push(
      <p key={key++} className="text-xs text-slate-300 leading-relaxed mb-1">
        {trimmed}
      </p>,
    )
  }

  return elements
}

export function FinalReviewPanel({ review }: Props) {
  return (
    <div
      className="flex flex-col h-full bg-slate-900 border-l border-slate-700 overflow-hidden shrink-0"
      style={{ width: 360 }}
    >
      {/* header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-700 shrink-0">
        <span className="text-xs font-semibold text-slate-200">AI Review</span>
        <span className="text-[10px] text-slate-500 border border-slate-700 rounded px-1.5 py-0.5 font-mono">
          paper2tree
        </span>
      </div>

      {/* scrollable body */}
      <div className="flex-1 overflow-y-auto px-4 py-3">{renderReview(review)}</div>
    </div>
  )
}
