import { useEffect, useState } from 'react'
import { fetchPaper } from '../api/papers'
import { PaperDAG } from '../types/dag'

const cache = new Map<string, PaperDAG>()

export function usePaper(resultPath: string | null) {
  const [paper, setPaper] = useState<PaperDAG | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!resultPath) {
      setPaper(null)
      return
    }

    if (cache.has(resultPath)) {
      setPaper(cache.get(resultPath)!)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)

    fetchPaper(resultPath)
      .then((data) => {
        if (!cancelled) {
          cache.set(resultPath, data)
          setPaper(data)
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [resultPath])

  return { paper, loading, error }
}
