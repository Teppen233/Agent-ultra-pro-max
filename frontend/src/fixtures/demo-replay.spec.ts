import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'

import { replayEventLog } from '@/api/client'
import demoEvents from '@/fixtures/demo-events.jsonl?raw'
import { useReviewStore } from '@/stores/review'

describe('完整离线 Demo Replay', () => {
  it('包含双专家并行、两个候选、一接收一拒绝和最终报告', async () => {
    setActivePinia(createPinia())
    const store = useReviewStore()

    await replayEventLog(demoEvents, store.applyEvent, {
      speed: 100,
      wait: async () => undefined,
    })

    expect(store.status).toBe('completed')
    expect(store.agents.defect.status).toBe('completed')
    expect(store.agents.intent.status).toBe('completed')
    expect(store.agents.verifier.status).toBe('completed')
    expect(store.candidates.map((candidate) => candidate.verdict)).toEqual(['accepted', 'rejected'])
    expect(store.findings).toHaveLength(1)
    expect(store.reportReady).toBe(true)
    expect(demoEvents).not.toContain('prompt')
    expect(demoEvents).not.toContain('reasoning_summary')
  })
})
