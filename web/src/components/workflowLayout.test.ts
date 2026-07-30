import { describe, expect, it } from 'vitest'

import type { WorkflowEdge, WorkflowNode } from '@/types'

import {
  layoutWorkflowGraph,
  placeProvisionalNodes,
  routeWorkflowEdges,
  WORKFLOW_NODE_SIZES,
  type WorkflowNodeDimensions,
} from './workflowLayout'

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

  it('uses measured node heights when separating ranks', () => {
    const nodes = [workflowNode('root', 'coordinator'), workflowNode('task')]
    const dimensions: WorkflowNodeDimensions = new Map([
      ['root', { width: 208, height: 220 }],
      ['task', { width: 248, height: 180 }],
    ])
    const positions = layoutWorkflowGraph(nodes, [workflowEdge('root', 'task')], dimensions)

    expect(positions.get('task')?.y).toBeGreaterThan(
      (positions.get('root')?.y ?? 0) + 220,
    )
  })

  it('keeps existing nodes fixed while placing new siblings provisionally', () => {
    const nodes = [
      workflowNode('root', 'coordinator'),
      workflowNode('task-a'),
      workflowNode('task-b'),
      workflowNode('task-c'),
      workflowNode('task-d'),
    ]
    const edges = nodes.slice(1).map((node) => workflowEdge('root', node.id))
    const stable = new Map([['root', { x: 400, y: 60 }]])
    const positions = placeProvisionalNodes(nodes, edges, stable)

    expect(positions.get('root')).toEqual({ x: 400, y: 60 })
    expect(new Set(nodes.slice(1).map((node) => positions.get(node.id)?.x)).size).toBe(4)
    expect(hasOverlap(nodes, positions)).toBe(false)
  })

  it('assigns separate endpoints and channels to primary sibling edges', () => {
    const nodes = [workflowNode('root', 'coordinator'), workflowNode('a'), workflowNode('b')]
    const edges = [workflowEdge('root', 'a'), workflowEdge('root', 'b')]
    const positions = new Map([
      ['root', { x: 300, y: 40 }],
      ['a', { x: 100, y: 260 }],
      ['b', { x: 500, y: 260 }],
    ])
    const routes = routeWorkflowEdges(nodes, edges, positions)

    expect(routes.get('root-a')?.sourcePoint.x).not.toBe(routes.get('root-b')?.sourcePoint.x)
    expect(routes.get('root-a')?.path).not.toBe(routes.get('root-b')?.path)
  })

  it('routes handoff above a rank and result outside graph bounds', () => {
    const source = workflowNode('source')
    const target = workflowNode('target')
    const nodes = [source, target]
    const positions = new Map([
      ['source', { x: 500, y: 260 }],
      ['target', { x: 100, y: 260 }],
    ])
    const handoff: WorkflowEdge = {
      id: 'handoff', source: 'source', target: 'target', relation: 'handoff',
    }
    const result: WorkflowEdge = {
      id: 'result', source: 'source', target: 'target', relation: 'result',
    }
    const routes = routeWorkflowEdges(nodes, [handoff, result], positions)

    expect(routes.get('handoff')?.path).toContain('L 76 ')
    expect(routes.get('result')?.path).toContain('L 64 ')
    expect(routes.get('handoff')?.path).not.toContain('L -')
    expect(routes.get('result')?.path).not.toContain('L -')
  })

  it('keeps feedback lanes close to each side regardless of global edge order', () => {
    const nodes = [
      workflowNode('left-source'),
      workflowNode('left-target'),
      workflowNode('right-source'),
      workflowNode('right-target'),
    ]
    const positions = new Map([
      ['left-source', { x: 100, y: 300 }],
      ['left-target', { x: 100, y: 100 }],
      ['right-source', { x: 600, y: 300 }],
      ['right-target', { x: 600, y: 100 }],
    ])
    const edges: WorkflowEdge[] = [
      { id: 'a-left', source: 'left-source', target: 'left-target', relation: 'result' },
      { id: 'b-right', source: 'right-source', target: 'right-target', relation: 'result' },
      { id: 'c-left', source: 'left-source', target: 'left-target', relation: 'result' },
      { id: 'd-right', source: 'right-source', target: 'right-target', relation: 'result' },
    ]
    const routes = routeWorkflowEdges(nodes, edges, positions)

    expect(routes.get('a-left')?.path).toContain('L 76 ')
    expect(routes.get('c-left')?.path).toContain('L 64 ')
    expect(routes.get('b-right')?.path).toContain('L 872 ')
    expect(routes.get('d-right')?.path).toContain('L 884 ')
  })

  it('routes downward handoff and report results through the tree', () => {
    const nodes = [workflowNode('source'), workflowNode('target', 'report')]
    const positions = new Map([
      ['source', { x: 100, y: 100 }],
      ['target', { x: 120, y: 360 }],
    ])
    const edges: WorkflowEdge[] = [
      { id: 'handoff', source: 'source', target: 'target', relation: 'handoff' },
      { id: 'result', source: 'source', target: 'target', relation: 'result' },
    ]
    const routes = routeWorkflowEdges(nodes, edges, positions)

    expect(routes.get('handoff')?.sourcePoint.y).toBe(212)
    expect(routes.get('handoff')?.targetPoint.y).toBe(360)
    expect(routes.get('result')?.sourcePoint.y).toBe(212)
    expect(routes.get('result')?.targetPoint.y).toBe(360)
  })
})
