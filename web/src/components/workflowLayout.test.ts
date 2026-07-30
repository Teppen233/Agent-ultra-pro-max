import { describe, expect, it } from 'vitest'

import type { WorkflowEdge, WorkflowNode } from '@/types'

import { layoutWorkflowGraph, WORKFLOW_NODE_SIZES } from './workflowLayout'

const workflowNode = (id: string, kind: WorkflowNode['kind'] = 'agent_task'): WorkflowNode => ({
  id,
  kind,
  label: id,
  status: 'queued',
})

const workflowEdge = (source: string, target: string): WorkflowEdge => ({
  id: `${source}-${target}`,
  source,
  target,
  relation: 'dispatch',
})

function hasOverlap(nodes: WorkflowNode[], positions: ReturnType<typeof layoutWorkflowGraph>) {
  return nodes.some((node, index) => {
    const position = positions.get(node.id)
    if (!position) return true
    const size = WORKFLOW_NODE_SIZES[node.kind]
    return nodes.slice(index + 1).some((other) => {
      const otherPosition = positions.get(other.id)
      if (!otherPosition) return true
      const otherSize = WORKFLOW_NODE_SIZES[other.kind]
      return (
        position.x < otherPosition.x + otherSize.width &&
        position.x + size.width > otherPosition.x &&
        position.y < otherPosition.y + otherSize.height &&
        position.y + size.height > otherPosition.y
      )
    })
  })
}

describe('layoutWorkflowGraph', () => {
  it('returns an empty map for an empty graph', () => {
    expect(layoutWorkflowGraph([], []).size).toBe(0)
  })

  it('lays out a chain from top to bottom', () => {
    const nodes = [workflowNode('input', 'input'), workflowNode('coordinator', 'coordinator'), workflowNode('task')]
    const positions = layoutWorkflowGraph(nodes, [workflowEdge('input', 'coordinator'), workflowEdge('coordinator', 'task')])

    expect(positions.get('input')?.y).toBeLessThan(positions.get('coordinator')?.y ?? 0)
    expect(positions.get('coordinator')?.y).toBeLessThan(positions.get('task')?.y ?? 0)
    expect(hasOverlap(nodes, positions)).toBe(false)
  })

  it('separates parallel branches and multi-parent nodes', () => {
    const nodes = [
      workflowNode('coordinator', 'coordinator'),
      workflowNode('task-a'),
      workflowNode('task-b'),
      workflowNode('task-c'),
      workflowNode('verifier', 'verifier'),
    ]
    const edges = [
      workflowEdge('coordinator', 'task-a'),
      workflowEdge('coordinator', 'task-b'),
      workflowEdge('coordinator', 'task-c'),
      workflowEdge('task-a', 'verifier'),
      workflowEdge('task-b', 'verifier'),
    ]
    const positions = layoutWorkflowGraph(nodes, edges)

    expect(new Set(['task-a', 'task-b', 'task-c'].map((id) => positions.get(id)?.x)).size).toBe(3)
    expect(positions.get('verifier')?.y).toBeGreaterThan(positions.get('task-a')?.y ?? Infinity)
    expect(hasOverlap(nodes, positions)).toBe(false)
  })

  it('places isolated nodes without overlap', () => {
    const nodes = [workflowNode('input', 'input'), workflowNode('orphan'), workflowNode('report', 'report')]
    const positions = layoutWorkflowGraph(nodes, [])

    expect(positions.size).toBe(3)
    expect(hasOverlap(nodes, positions)).toBe(false)
  })

  it('is deterministic when input order changes', () => {
    const nodes = [workflowNode('root', 'coordinator'), workflowNode('a'), workflowNode('b')]
    const edges = [workflowEdge('root', 'a'), workflowEdge('root', 'b')]
    const forward = [...layoutWorkflowGraph(nodes, edges)]
    const reversed = [...layoutWorkflowGraph([...nodes].reverse(), [...edges].reverse())]

    expect(reversed).toEqual(forward)
  })
})
