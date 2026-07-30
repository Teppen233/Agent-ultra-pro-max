import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { demoEvents } from '@/demo'
import { useReviewStore } from '@/stores/review'

describe('review workflow reducer', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('starts empty and updates workflow nodes by stable ID', () => {
    const store = useReviewStore()
    expect(store.workflowNodes).toHaveLength(0)

    const coordinatorEvents = demoEvents.filter(
      (event) => event.type === 'workflow_node' && event.workflow_node.id === 'coordinator',
    )
    for (const event of coordinatorEvents) store.consume(structuredClone(event))

    expect(store.workflowNodes).toHaveLength(1)
    expect(store.workflowNodes[0]?.status).toBe('completed')
    expect(store.dispatchLog.length).toBeGreaterThan(1)
  })

  it('derives task counts, concurrency, edges, and verifier decisions', () => {
    const store = useReviewStore()
    for (const event of demoEvents) store.consume(structuredClone(event))

    expect(store.workflowNodes.length).toBeGreaterThan(10)
    expect(store.workflowEdges.some((edge) => edge.relation === 'handoff')).toBe(true)
    expect(store.workflowEdges.some((edge) => edge.relation === 'challenge')).toBe(true)
    expect(store.concurrencyPeak).toBeGreaterThanOrEqual(2)
    expect(store.taskCounts.completed).toBeGreaterThanOrEqual(4)
    expect(store.findings).toHaveLength(2)
    expect(store.retainedFindings).toHaveLength(1)
    expect(store.rejectedCount).toBe(1)
  })

  it('loads the complete demo fixture for refreshable deep links', () => {
    const store = useReviewStore()
    store.loadDemo()

    expect(store.runId).toBe('demo-refresh-token')
    expect(store.diff).toContain('refresh_session')
    expect(store.report).toContain('审查摘要')
    expect(store.workflowNodes.at(-1)?.kind).toBe('report')
  })

  it('rebuilds deterministic state when stepping and seeking', () => {
    const store = useReviewStore()
    store.setReplaySource(demoEvents, true)

    expect(store.replayIndex).toBe(demoEvents.length)
    expect(store.workflowNodes.at(-1)?.kind).toBe('report')

    store.stepReplay(-1)
    expect(store.replayIndex).toBe(demoEvents.length - 1)
    expect(store.report).toBeNull()

    store.stepReplay(1)
    expect(store.replayIndex).toBe(demoEvents.length)
    expect(store.report).toContain('审查摘要')

    store.seekReplay(0)
    expect(store.replayIndex).toBe(0)
    expect(store.workflowNodes).toHaveLength(0)
  })

  it('changes speed and restarts playback from the end', async () => {
    vi.useFakeTimers()
    const store = useReviewStore()
    store.setReplaySource(demoEvents.slice(0, 3), true)
    store.setReplaySpeed(4)
    store.playReplay()

    expect(store.replaySpeed).toBe(4)
    expect(store.replayIndex).toBe(0)
    expect(store.replaying).toBe(true)

    await vi.runAllTimersAsync()
    expect(store.replayIndex).toBe(3)
    expect(store.replaying).toBe(false)
    vi.useRealTimers()
  })
})
