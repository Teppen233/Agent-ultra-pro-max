import dagre from '@dagrejs/dagre'

import type { WorkflowEdge, WorkflowKind, WorkflowNode, WorkflowRelation } from '@/types'

export type WorkflowPosition = { x: number; y: number }
export type WorkflowNodeSize = { width: number; height: number }
export type WorkflowNodeDimensions = Map<string, WorkflowNodeSize>

export interface RoutedWorkflowEdge {
  path: string
  sourcePoint: WorkflowPosition
  targetPoint: WorkflowPosition
}

export const WORKFLOW_NODE_SIZES: Record<WorkflowKind, WorkflowNodeSize> = {
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
const PROVISIONAL_RANK_GAP = 96
const PROVISIONAL_NODE_GAP = 64
const EDGE_CHANNEL_GAP = 12
const OUTER_LANE_GAP = 12
const OUTER_LANE_OFFSET = 24

export function getWorkflowNodeSize(
  node: WorkflowNode,
  dimensions?: WorkflowNodeDimensions,
): WorkflowNodeSize {
  const fallback = WORKFLOW_NODE_SIZES[node.kind]
  const measured = dimensions?.get(node.id)
  return {
    width: Math.max(fallback.width, measured?.width ?? 0),
    height: Math.max(fallback.height, measured?.height ?? 0),
  }
}

function fallbackLayout(
  nodes: WorkflowNode[],
  dimensions?: WorkflowNodeDimensions,
): Map<string, WorkflowPosition> {
  const positions = new Map<string, WorkflowPosition>()
  const sorted = [...nodes].sort((left, right) => left.id.localeCompare(right.id))
  const sizes = sorted.map((node) => getWorkflowNodeSize(node, dimensions))
  const cellWidth = Math.max(...sizes.map((size) => size.width))
  const cellHeight = Math.max(...sizes.map((size) => size.height))

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
  dimensions?: WorkflowNodeDimensions,
) {
  const byRank = new Map<number, WorkflowNode[]>()
  for (const node of nodes) {
    const position = positions.get(node.id)
    if (!position) continue
    const size = getWorkflowNodeSize(node, dimensions)
    const rank = Math.round(position.y + size.height / 2)
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
        return (position?.x ?? 0) + getWorkflowNodeSize(node, dimensions).width
      }),
    )
    const requiredWidth = rankNodes.reduce(
      (sum, node) => sum + getWorkflowNodeSize(node, dimensions).width,
      RANK_NODE_GAP * (rankNodes.length - 1),
    )
    let cursor = Math.max(GRAPH_MARGIN, (originalLeft + originalRight - requiredWidth) / 2)

    for (const node of rankNodes) {
      const position = positions.get(node.id)
      if (!position) continue
      positions.set(node.id, { x: cursor, y: position.y })
      cursor += getWorkflowNodeSize(node, dimensions).width + RANK_NODE_GAP
    }
  }
}

export function layoutWorkflowGraph(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  dimensions?: WorkflowNodeDimensions,
): Map<string, WorkflowPosition> {
  if (nodes.length === 0) return new Map()

  const sortedNodes = [...nodes].sort((left, right) => left.id.localeCompare(right.id))
  const nodeIds = new Set(sortedNodes.map((node) => node.id))
  const nodeById = new Map(sortedNodes.map((node) => [node.id, node]))
  const sortedEdges = [...edges]
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .filter((edge) => edge.relation !== 'result' || nodeById.get(edge.target)?.kind === 'report')
    .sort((left, right) => left.id.localeCompare(right.id))

  try {
    const graph = new dagre.graphlib.Graph({ multigraph: true })
    graph.setGraph({
      rankdir: 'TB',
      ranker: 'network-simplex',
      nodesep: RANK_NODE_GAP,
      edgesep: 28,
      ranksep: 108,
      marginx: GRAPH_MARGIN,
      marginy: GRAPH_MARGIN,
    })
    graph.setDefaultEdgeLabel(() => ({}))

    for (const node of sortedNodes) graph.setNode(node.id, getWorkflowNodeSize(node, dimensions))
    for (const edge of sortedEdges) {
      graph.setEdge(edge.source, edge.target, { relation: edge.relation }, edge.id)
    }

    dagre.layout(graph)

    const positions = new Map<string, WorkflowPosition>()
    for (const node of sortedNodes) {
      const result = graph.node(node.id) as { x?: number; y?: number } | undefined
      const size = getWorkflowNodeSize(node, dimensions)
      if (!result || !Number.isFinite(result.x) || !Number.isFinite(result.y)) {
        return fallbackLayout(sortedNodes, dimensions)
      }
      positions.set(node.id, {
        x: (result.x ?? 0) - size.width / 2,
        y: (result.y ?? 0) - size.height / 2,
      })
    }
    spreadRankCollisions(sortedNodes, positions, dimensions)
    return positions
  } catch {
    return fallbackLayout(sortedNodes, dimensions)
  }
}

function rectanglesOverlap(
  leftPosition: WorkflowPosition,
  leftSize: WorkflowNodeSize,
  rightPosition: WorkflowPosition,
  rightSize: WorkflowNodeSize,
) {
  const padding = 24
  return (
    leftPosition.x < rightPosition.x + rightSize.width + padding &&
    leftPosition.x + leftSize.width + padding > rightPosition.x &&
    leftPosition.y < rightPosition.y + rightSize.height + padding &&
    leftPosition.y + leftSize.height + padding > rightPosition.y
  )
}

export function placeProvisionalNodes(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  stablePositions: Map<string, WorkflowPosition>,
  dimensions?: WorkflowNodeDimensions,
): Map<string, WorkflowPosition> {
  const positions = new Map(stablePositions)
  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  const newNodes = nodes
    .filter((node) => !positions.has(node.id))
    .sort((left, right) => left.id.localeCompare(right.id))
  const groupedByParent = new Map<string, WorkflowNode[]>()
  const unparented: WorkflowNode[] = []

  for (const node of newNodes) {
    const parentEdge = edges
      .filter((edge) => edge.target === node.id && edge.relation !== 'result')
      .sort((left, right) => left.id.localeCompare(right.id))
      .find((edge) => positions.has(edge.source))
    if (!parentEdge) {
      unparented.push(node)
      continue
    }
    const siblings = groupedByParent.get(parentEdge.source) ?? []
    siblings.push(node)
    groupedByParent.set(parentEdge.source, siblings)
  }

  const placeWithoutCollision = (node: WorkflowNode, initial: WorkflowPosition) => {
    const size = getWorkflowNodeSize(node, dimensions)
    const candidate = { ...initial }
    let attempts = 0
    while (
      attempts < 100 &&
      [...positions].some(([id, position]) => {
        const other = nodeById.get(id)
        return other
          ? rectanglesOverlap(candidate, size, position, getWorkflowNodeSize(other, dimensions))
          : false
      })
    ) {
      candidate.x += size.width + PROVISIONAL_NODE_GAP
      attempts += 1
    }
    positions.set(node.id, candidate)
  }

  for (const [parentId, children] of [...groupedByParent].sort(([left], [right]) => left.localeCompare(right))) {
    const parent = nodeById.get(parentId)
    const parentPosition = positions.get(parentId)
    if (!parent || !parentPosition) continue
    const parentSize = getWorkflowNodeSize(parent, dimensions)
    const totalWidth = children.reduce(
      (sum, child) => sum + getWorkflowNodeSize(child, dimensions).width,
      PROVISIONAL_NODE_GAP * Math.max(0, children.length - 1),
    )
    let cursor = parentPosition.x + parentSize.width / 2 - totalWidth / 2
    for (const child of children) {
      placeWithoutCollision(child, {
        x: cursor,
        y: parentPosition.y + parentSize.height + PROVISIONAL_RANK_GAP,
      })
      cursor += getWorkflowNodeSize(child, dimensions).width + PROVISIONAL_NODE_GAP
    }
  }

  const rightEdge = Math.max(
    GRAPH_MARGIN,
    ...[...positions].map(([id, position]) => {
      const node = nodeById.get(id)
      return position.x + (node ? getWorkflowNodeSize(node, dimensions).width : 0)
    }),
  )
  unparented.forEach((node, index) => {
    placeWithoutCollision(node, {
      x: rightEdge + PROVISIONAL_NODE_GAP,
      y: GRAPH_MARGIN + index * (getWorkflowNodeSize(node, dimensions).height + PROVISIONAL_RANK_GAP),
    })
  })
  return positions
}

const primaryRelations = new Set<WorkflowRelation>(['dispatch', 'depends_on', 'candidate', 'challenge'])

function slotOffset(index: number, count: number, extent: number) {
  const safeExtent = Math.max(0, extent - 40)
  return 20 + ((index + 1) / (count + 1)) * safeExtent
}

export function routeWorkflowEdges(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  positions: Map<string, WorkflowPosition>,
  dimensions?: WorkflowNodeDimensions,
): Map<string, RoutedWorkflowEdge> {
  const routes = new Map<string, RoutedWorkflowEdge>()
  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  const validEdges = edges
    .filter((edge) => positions.has(edge.source) && positions.has(edge.target))
    .sort((left, right) => left.id.localeCompare(right.id))
  const outgoing = new Map<string, WorkflowEdge[]>()
  const incoming = new Map<string, WorkflowEdge[]>()
  for (const edge of validEdges) {
    outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge])
    incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge])
  }

  const bounds = nodes.reduce(
    (value, node) => {
      const position = positions.get(node.id)
      if (!position) return value
      const size = getWorkflowNodeSize(node, dimensions)
      return {
        minX: Math.min(value.minX, position.x),
        maxX: Math.max(value.maxX, position.x + size.width),
      }
    },
    { minX: Infinity, maxX: -Infinity },
  )
  let leftOuterLaneIndex = 0
  let rightOuterLaneIndex = 0

  validEdges.forEach((edge) => {
    const source = nodeById.get(edge.source)
    const target = nodeById.get(edge.target)
    const sourcePosition = positions.get(edge.source)
    const targetPosition = positions.get(edge.target)
    if (!source || !target || !sourcePosition || !targetPosition) return
    const sourceSize = getWorkflowNodeSize(source, dimensions)
    const targetSize = getWorkflowNodeSize(target, dimensions)
    const sourceEdges = outgoing.get(edge.source) ?? []
    const targetEdges = incoming.get(edge.target) ?? []
    const sourceIndex = sourceEdges.findIndex((item) => item.id === edge.id)
    const targetIndex = targetEdges.findIndex((item) => item.id === edge.id)

    const hasDownwardClearance = targetPosition.y >= sourcePosition.y + sourceSize.height + 24
    const usesDownwardChannel =
      primaryRelations.has(edge.relation) ||
      edge.relation === 'evidence' ||
      edge.relation === 'tool_call' ||
      ((edge.relation === 'handoff' || edge.relation === 'result') && hasDownwardClearance)

    if (usesDownwardChannel) {
      const sourcePoint = {
        x: sourcePosition.x + slotOffset(sourceIndex, sourceEdges.length, sourceSize.width),
        y: sourcePosition.y + sourceSize.height,
      }
      const targetPoint = {
        x: targetPosition.x + slotOffset(targetIndex, targetEdges.length, targetSize.width),
        y: targetPosition.y,
      }
      const available = Math.max(32, targetPoint.y - sourcePoint.y)
      const channelY = sourcePoint.y + Math.min(available / 2, 36 + sourceIndex * EDGE_CHANNEL_GAP)
      routes.set(edge.id, {
        sourcePoint,
        targetPoint,
        path: `M ${sourcePoint.x} ${sourcePoint.y} L ${sourcePoint.x} ${channelY} L ${targetPoint.x} ${channelY} L ${targetPoint.x} ${targetPoint.y}`,
      })
      return
    }

    const sourceCenter = sourcePosition.x + sourceSize.width / 2
    const targetCenter = targetPosition.x + targetSize.width / 2
    const graphCenter = (bounds.minX + bounds.maxX) / 2
    const useLeft = (sourceCenter + targetCenter) / 2 <= graphCenter
    const laneIndex = useLeft ? leftOuterLaneIndex++ : rightOuterLaneIndex++
    const laneX = useLeft
      ? Math.max(8, bounds.minX - OUTER_LANE_OFFSET - laneIndex * OUTER_LANE_GAP)
      : bounds.maxX + OUTER_LANE_OFFSET + laneIndex * OUTER_LANE_GAP
    const sourcePoint = {
      x: sourcePosition.x + (useLeft ? 0 : sourceSize.width),
      y: sourcePosition.y + sourceSize.height / 2,
    }
    const targetPoint = {
      x: targetPosition.x + (useLeft ? 0 : targetSize.width),
      y: targetPosition.y + targetSize.height / 2,
    }
    routes.set(edge.id, {
      sourcePoint,
      targetPoint,
      path: `M ${sourcePoint.x} ${sourcePoint.y} L ${laneX} ${sourcePoint.y} L ${laneX} ${targetPoint.y} L ${targetPoint.x} ${targetPoint.y}`,
    })
  })

  return routes
}
