import { useCallback, useEffect, useState } from 'react'
import { fetchIndex } from '../api/papers'
import { PaperIndexEntry } from '../types/dag'

export function usePaperIndex() {
  const [papers, setPapers] = useState<PaperIndexEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (): Promise<PaperIndexEntry[]> => {
    setError(null)
    try {
      const idx = await fetchIndex()
      const sorted = [...idx.papers].sort(
        (a, b) => new Date(b.processed_at).getTime() - new Date(a.processed_at).getTime(),
      )
      setPapers(sorted)
      return sorted
    } catch (e) {
      setError((e as Error).message)
      return []
    }
  }, [])

  // Initial load
  useEffect(() => {
    setLoading(true)
    load().finally(() => setLoading(false))
  }, [load])

  // refresh() — call after a new paper is processed; returns the updated list
  const refresh = useCallback(() => load(), [load])

  return { papers, loading, error, refresh }
}
