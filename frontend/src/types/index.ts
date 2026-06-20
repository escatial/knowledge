export interface Document {
  id: string
  title: string
  content: string
  category: string
  created_at: string
  filename?: string
  file_type?: string
  chunk_count?: number
}

export interface GraphNode {
  id: string
  name: string
  type: string
  description?: string
  category?: string
  val?: number
}

export interface GraphEdge {
  source: string
  target: string
  type: string
  description?: string
}

export interface KnowledgeGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface NodeDetail {
  node: GraphNode
  edges: GraphEdge[]
  related_nodes: GraphNode[]
}

export interface SearchResult {
  graph: KnowledgeGraph
  text: Array<{
    document: Document
    score: number
    type: string
  }>
}

export interface AIAnswer {
  question: string
  answer: string
  sources: SearchResult
}
