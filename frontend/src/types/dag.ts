export interface VisualMeta {
  color: string
  size: number
  border_width: number
}

export interface LiteratureCitation {
  title: string
  authors: string[]
  year: number | null
  url: string
  relevance: string
  stance: 'supports' | 'contradicts' | 'extends' | 'neutral'
}

export interface ClaimEvaluation {
  node_id: string
  evidence_strength: 'strong' | 'moderate' | 'weak' | 'absent'
  claim_evidence_calibration: 'overclaimed' | 'calibrated' | 'underclaimed'
  strengths: string[]
  weaknesses: string[]
  alternative_interpretations: string[]
  required_assumptions: string[]
  notes: string
  literature_citations?: LiteratureCitation[]
  novelty_score?: 'high' | 'medium' | 'low' | null
  groundedness_score?: 'high' | 'medium' | 'low' | null
}

export interface DAGNode {
  id: string
  label: string
  claim: string
  type: 'root' | 'primary' | 'supporting' | 'evidence'
  depth: number
  section_source: string
  verbatim_quote: string
  evaluation: ClaimEvaluation | null
  visual: VisualMeta
  page_number?: number | null
  bbox?: [number, number, number, number][] | null
}

export interface DAGEdge {
  id: string
  source: string
  target: string
  relationship: string
  label: string
}

export interface PaperMeta {
  paper_id: string
  title: string
  authors: string[]
  url: string
  abstract: string
  word_count: number
  processed_at: string
  has_local_pdf?: boolean
}

export interface DAGSummary {
  total_nodes: number
  total_edges: number
  max_depth: number
  high_support_nodes: number
  low_support_nodes: number
  overall_assessment: string
}

export interface PaperDAG {
  paper: PaperMeta
  dag: {
    nodes: DAGNode[]
    edges: DAGEdge[]
  }
  summary: DAGSummary
  final_review?: string | null
}

export interface PaperIndexEntry {
  paper_id: string
  title: string
  authors: string[]
  url: string
  abstract_short: string
  processed_at: string
  high_support_count: number
  total_claims: number
  result_path: string
}

export interface PaperIndex {
  version: number
  papers: PaperIndexEntry[]
}
