export interface VisualMeta {
  color: string
  size: number
  border_width: number
}

export interface ClaimEvaluation {
  node_id: string
  support_level: 'high' | 'medium' | 'low'
  confidence_level: 'high' | 'medium' | 'low'
  is_well_supported: boolean
  strengths: string[]
  weaknesses: string[]
  alternative_interpretations: string[]
  required_assumptions: string[]
  supporting_evidence_quality: 'strong' | 'moderate' | 'weak' | 'absent'
  notes: string
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
