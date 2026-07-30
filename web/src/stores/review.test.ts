import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { demoEvents } from '@/demo'
import { useReviewStore } from '@/stores/review'
import type { PipelineEvent } from '@/types'

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

  it('sends a null repository path when automatic checkout is requested', async () => {
    class FakeEventSource {
      onerror: (() => void) | null = null

      addEventListener() {}

      close() {}
    }

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ run_id: 'run-auto-repo' }), {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('EventSource', FakeEventSource)
    const store = useReviewStore()

    try {
      await store.startReview('https://github.com/owner/repo/pull/42', '   ')

      const request = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined
      expect(JSON.parse(String(request?.body))).toEqual({
        pr_url: 'https://github.com/owner/repo/pull/42',
        repo_path: null,
      })
    } finally {
      store.stopSource()
      vi.unstubAllGlobals()
    }
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

  it('keeps legacy findings distinct when a model reused a placeholder ID', () => {
    const store = useReviewStore()
    const first = structuredClone(
      demoEvents.find((event) => event.type === 'finding') as PipelineEvent,
    )
    const second = structuredClone(first)
    if (first.type !== 'finding' || second.type !== 'finding') throw new Error('fixture mismatch')
    first.finding.id = 'F1'
    second.finding.id = 'F1'
    second.finding.title = 'A separate candidate'
    second.finding.line_start += 20
    store.consume(first)
    store.consume(second)

    store.consume({
      type: 'verdict',
      timestamp: 3,
      verdict: {
        finding_id: 'F1',
        verdict: 'reject',
        reason: 'first verdict',
        confidence_adjusted: 0.1,
      },
    })
    store.consume({
      type: 'verdict',
      timestamp: 4,
      verdict: {
        finding_id: 'F1',
        verdict: 'keep',
        reason: 'second verdict',
        confidence_adjusted: 0.9,
      },
    })

    expect(store.findings).toHaveLength(2)
    expect(new Set(store.findings.map((item) => item.id)).size).toBe(2)
    expect(store.findings.find((item) => item.title === first.finding.title)?.verdict_reason).toBe(
      'first verdict',
    )
    expect(store.findings.find((item) => item.title === second.finding.title)?.verdict_reason).toBe(
      'second verdict',
    )
  })

  it('replaces streamed candidates with the authoritative report findings', () => {
    const store = useReviewStore()
    const findingEvents = demoEvents.filter((event) => event.type === 'finding')
    for (const event of findingEvents) store.consume(structuredClone(event))
    const finalFinding = structuredClone(
      findingEvents[0]?.finding,
    )
    if (!finalFinding) throw new Error('fixture mismatch')
    finalFinding.verdict = 'keep'
    finalFinding.confidence_adjusted = 0.9

    store.consume({
      type: 'report',
      timestamp: 10,
      markdown: '# 审查摘要\n\n- 候选总数：1',
      findings: [finalFinding],
    })

    expect(store.findings).toEqual([finalFinding])
    expect(store.retainedFindings).toHaveLength(1)
    expect(store.rejectedCount).toBe(0)
  })
})
