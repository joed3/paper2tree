import { PaperDAG, PaperIndex } from '../types/dag'

const BASE = '/outputs'

export async function fetchIndex(): Promise<PaperIndex> {
  const res = await fetch(`${BASE}/index.json`)
  if (!res.ok) throw new Error(`Failed to fetch index: ${res.status}`)
  return res.json()
}

export async function fetchPaper(resultPath: string): Promise<PaperDAG> {
  const res = await fetch(`${BASE}/${resultPath}`)
  if (!res.ok) throw new Error(`Failed to fetch paper: ${res.status}`)
  return res.json()
}
