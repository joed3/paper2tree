import { useCallback, useEffect, useRef, useState } from 'react'
import { getJob, Job } from '../api/jobs'

const STORAGE_KEY = 'p2t_jobs'
const POLL_MS = 2000
const RETAIN_MS = 86_400_000 // 24 h

function load(): Job[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
  } catch {
    return []
  }
}

function persist(jobs: Job[]) {
  const cutoff = Date.now() - RETAIN_MS
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify(
      jobs.filter(
        (j) =>
          j.status === 'queued' ||
          j.status === 'running' ||
          new Date(j.created_at).getTime() > cutoff,
      ),
    ),
  )
}

export function useJobs(onComplete?: (job: Job) => void) {
  const [jobs, setJobs] = useState<Job[]>(load)
  // Keep onComplete stable via ref so polling closure is never stale
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete

  const addJob = useCallback((job: Job) => {
    setJobs((prev) => [job, ...prev.filter((j) => j.job_id !== job.job_id)])
  }, [])

  const removeJob = useCallback((jobId: string) => {
    setJobs((prev) => prev.filter((j) => j.job_id !== jobId))
  }, [])

  // Poll all queued/running jobs
  useEffect(() => {
    const active = jobs.filter((j) => j.status === 'queued' || j.status === 'running')
    if (!active.length) return

    const id = setInterval(async () => {
      const settled = await Promise.allSettled(active.map((j) => getJob(j.job_id)))
      setJobs((prev) => {
        let dirty = false
        const next = prev.map((j) => {
          const ai = active.findIndex((a) => a.job_id === j.job_id)
          if (ai === -1) return j
          const r = settled[ai]
          if (r.status === 'rejected') return j
          const updated = r.value
          if (updated.step !== j.step || updated.status !== j.status) dirty = true
          if (j.status !== 'done' && updated.status === 'done') {
            // Fire outside setState to avoid React batching issues
            setTimeout(() => onCompleteRef.current?.(updated), 0)
          }
          return updated
        })
        return dirty ? next : prev
      })
    }, POLL_MS)

    return () => clearInterval(id)
  }, [jobs])

  useEffect(() => {
    persist(jobs)
  }, [jobs])

  return { jobs, addJob, removeJob }
}
