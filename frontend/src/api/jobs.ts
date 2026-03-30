export type JobStatus = 'queued' | 'running' | 'done' | 'error'

export interface Job {
  job_id: string
  status: JobStatus
  source: string
  step: string
  paper_id: string | null
  error: string | null
  created_at: string
}

export async function submitUrl(url: string, force = false, liveSearch = false): Promise<string> {
  const res = await fetch('/api/process', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, force, live_search: liveSearch }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail ?? `HTTP ${res.status}`)
  }
  return (await res.json()).job_id
}

export async function submitFile(file: File, force = false, liveSearch = false): Promise<string> {
  const form = new FormData()
  form.append('file', file)
  if (force) form.append('force', 'true')
  if (liveSearch) form.append('live_search', 'true')
  const res = await fetch('/api/upload', { method: 'POST', body: form })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail ?? `HTTP ${res.status}`)
  }
  return (await res.json()).job_id
}

export async function getJob(jobId: string): Promise<Job> {
  const res = await fetch(`/api/jobs/${jobId}`)
  if (!res.ok) throw new Error(`Job not found: ${jobId}`)
  return res.json()
}
