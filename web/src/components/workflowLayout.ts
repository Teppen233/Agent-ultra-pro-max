import dagre from '@dagrejs/dagre'

import type { WorkflowEdge, WorkflowKind, WorkflowNode } from '@/types'

export type WorkflowPosition = { x: number; y: number }

export const WORKFLOW_NODE_SIZES: Record<WorkflowKind, { width: number; height: number }> = {
  input: { width: 208, height: 88 },
  coordinator: { width: 208, height: 92 },
  agent_task: { width: 248, height: 112 },
  tool: { width: 184, height: 80 },
  finding: { width: 248, height: 112 },
  verifier: { width: 248, height: 112 },
  report: { width: 208, height: 88 },
}

const GRAPH_MARGIN = 48
const FALLBACK_COLUMNS = 4
const FALLBACK_GAP_X = 72
const FALLBACK_GAP_Y = 96
const RANK_NODE_GAP = 72

function fallbackLayout(nodes: WorkflowNode[]): Map<string, WorkflowPosition> {
  const positions = new Map<string, WorkflowPosition>()
  const sorted = [...nodes].sort((left, right) => left.id.localeCompare(right.id))
  const cellWidth = Math.max(...Object.values(WORKFLOW_NODE_SIZES).map((size) => size.width))
  const cellHeight = Math.max(...Object.values(WORKFLOW_NODE_SIZES).map((size) => size.height))

  sorted.forEach((node, index) => {
    positions.set(node.id, {
      x: GRAPH_MARGIN + (index % FALLBACK_COLUMNS) * (cellWidth + FALLBACK_GAP_X),
      y: GRAPH_MARGIN + Math.floor(index / FALLBACK_COLUMNS) * (cellHeight + FALLBACK_GAP_Y),
    })
  })
  return positions
}

function spreadRankCollisions(
  nodes: WorkflowNode[],
  positions: Map<string, WorkflowPosition>,
) {
  const byRank = new Map<number, WorkflowNode[]>()
  for (const node of nodes) {
    const position = positions.get(node.id)
    if (!position) continue
    const rank = Math.round(position.y + WORKFLOW_NODE_SIZES[node.kind].height / 2)
    const rankNodes = byRank.get(rank) ?? []
    rankNodes.push(node)
    byRank.set(rank, rankNodes)
  }

  for (const rankNodes of byRank.values()) {
    if (rankNodes.length < 2) continue
    rankNodes.sort((left, right) => {
      const leftX = positions.get(left.id)?.x ?? 0
      const rightX = positions.get(right.id)?.x ?? 0
      return leftX - rightX || left.id.localeCompare(right.id)
    })

    const originalLeft = Math.min(...rankNodes.map((node) => positions.get(node.id)?.x ?? 0))
    const originalRight = Math.max(
      ...rankNodes.map((node) => {
        const position = positions.get(node.id)
        return (position?.x ?? 0) + WORKFLOW_NODE_SIZES[node.kind].width
      }),
    )
    const requiredWidth = rankNodes.reduce(
      (sum, node) => sum + WORKFLOW_NODE_SIZES[node.kind].width,
      RANK_NODE_GAP * (rankNodes.length - 1),
    )
    let cursor = Math.max(GRAPH_MARGIN, (originalLeft + originalRight - requiredWidth) / 2)

    for (const node of rankNodes) {
      const position = positions.get(node.id)
      if (!position) continue
      positions.set(node.id, { x: cursor, y: position.y })
      cursor += WORKFLOW_NODE_SIZES[node.kind].width + RANK_NODE_GAP
    }
  }
}

export function layoutWorkflowGraph(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): Map<string, WorkflowPosition> {
  if (nodes.length === 0) return new Map()

  const sortedNodes = [...nodes].sort((left, right) => left.id.localeCompare(right.id))
  const nodeIds = new Set(sortedNodes.map((node) => node.id))
  const sortedEdges = [...edges]
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .sort((left, right) => left.id.localeCompare(right.id))

  try {
    const graph = new dagre.graphlib.Graph({ multigraph: true })
    graph.setGraph({
      rankdir: 'TB',
      ranker: 'network-simplex',
      nodesep: 72,
      edgesep: 28,
      ranksep: 108,
      marginx: GRAPH_MARGIN,
      marginy: GRAPH_MARGIN,
    })
    graph.setDefaultEdgeLabel(() => ({}))

    for (const node of sortedNodes) {
      graph.setNode(node.id, WORKFLOW_NODE_SIZES[node.kind])
    }
    for (const edge of sortedEdges) {
      graph.setEdge(edge.source, edge.target, { relation: edge.relation }, edge.id)
    }

    dagre.layout(graph)

    const positions = new Map<string, WorkflowPosition>()
    for (const node of sortedNodes) {
      const result = graph.node(node.id) as { x?: number; y?: number } | undefined
      const size = WORKFLOW_NODE_SIZES[node.kind]
      if (!result || !Number.isFinite(result.x) || !Number.isFinite(result.y)) {
        return fallbackLayout(sortedNodes)
      }
      positions.set(node.id, {
        x: (result.x ?? 0) - size.width / 2,
        y: (result.y ?? 0) - size.height / 2,
      })
    }
    spreadRankCollisions(sortedNodes, positions)
    return positions
  } catch {
    return fallbackLayout(sortedNodes)
  }
}
