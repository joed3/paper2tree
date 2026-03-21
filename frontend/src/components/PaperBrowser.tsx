import { useState } from 'react'
import { PaperIndexEntry } from '../types/dag'
import { EvalBadge } from './EvalBadge'

interface PaperBrowserProps {
  papers: PaperIndexEntry[]
  selectedId: string | null
  onSelect: (entry: PaperIndexEntry) => void
  onAddPaper: () => void
  loading: boolean
  error: string | null
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export function PaperBrowser({
  papers,
  selectedId,
  onSelect,
  onAddPaper,
  loading,
  error,
}: PaperBrowserProps) {
  const [query, setQuery] = useState('')

  const filtered = papers.filter((p) => {
    if (!query.trim()) return true
    const q = query.toLowerCase()
    return (
      p.title.toLowerCase().includes(q) ||
      p.authors.some((a) => a.toLowerCase().includes(q))
    )
  })

  return (
    <div className="flex flex-col h-full bg-slate-900 border-r border-slate-700" style={{ width: 300 }}>
      {/* header */}
      <div className="px-4 py-3 border-b border-slate-700 shrink-0">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-slate-200 font-semibold text-sm tracking-wide">paper2tree</span>
          {papers.length > 0 && (
            <span className="text-[10px] text-slate-500 font-mono bg-slate-800 px-1.5 py-0.5 rounded">
              {papers.length}
            </span>
          )}
          <button
            onClick={onAddPaper}
            title="Add paper"
            className="ml-auto w-6 h-6 rounded flex items-center justify-center text-slate-400 hover:text-slate-100 hover:bg-slate-700 transition-colors text-base leading-none"
          >
            +
          </button>
        </div>
        <input
          type="text"
          placeholder="Search papers…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full bg-slate-800 border border-slate-700 rounded text-xs text-slate-200 placeholder-slate-600 px-3 py-1.5 outline-none focus:border-slate-500 transition-colors font-mono"
        />
      </div>

      {/* list */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center h-24 text-xs text-slate-600">
            Loading…
          </div>
        )}

        {error && (
          <div className="px-4 py-3 text-xs text-red-400">
            <p className="font-semibold mb-1">Failed to load papers</p>
            <p className="text-slate-500">{error}</p>
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="px-4 py-3 text-xs text-slate-600 italic">No papers match.</div>
        )}

        {filtered.map((entry) => {
          const isSelected = entry.paper_id === selectedId
          return (
            <button
              key={entry.paper_id}
              onClick={() => onSelect(entry)}
              className="w-full text-left px-4 py-3 border-b border-slate-800 transition-colors hover:bg-slate-800"
              style={{
                backgroundColor: isSelected ? '#1e293b' : undefined,
                borderLeft: isSelected ? '2px solid #22c55e' : '2px solid transparent',
              }}
            >
              <p className="text-xs text-slate-200 leading-snug mb-1 line-clamp-2 font-medium">
                {entry.title}
              </p>
              <p className="text-[10px] text-slate-500 mb-2 truncate">
                {entry.authors.join(', ')}
              </p>
              <div className="flex items-center gap-2 flex-wrap">
                <EvalBadge score={entry.mean_validity_score} size="sm" />
                <span className="text-[10px] text-slate-600 font-mono">
                  {entry.total_claims} claims
                </span>
                <span className="text-[10px] text-slate-700 font-mono ml-auto">
                  {formatDate(entry.processed_at)}
                </span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
