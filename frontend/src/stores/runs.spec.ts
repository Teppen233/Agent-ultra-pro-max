import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PipelineEvent } from '@/contracts'
import { createIsolatedReviewStore, useReviewStore } from '@/stores/review'
import { createServerReplaySubscription, useRunsStore } from '@/stores/runs'

interface FakeEventSource {
  onopen: (() => void) | null
  onmessage: ((event: MessageEvent<string>) => void) | null
  onerror: (() => void) | null
  close: ReturnType<typeof vi.fn>
}

const fakeEventSource = (): FakeEventSource => ({
  onopen: null,
  onmessage: null,
  onerror: null,
  close: vi.fn(),
})

const event = (runId: string, repository: string): PipelineEvent => ({
  id: `evt-${runId}`,
  run_id: runId,
  sequence: 1,
  timestamp: '2026-07-30T01:00:00Z',
  type: 'review.started',
  data: { repository },
})

describe('应用级运行订阅', () => {
  let applicationPinia: ReturnType<typeof createPinia>

  beforeEach(() => {
    applicationPinia = createPinia()
    setActivePinia(applicationPinia)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('页面卸载后全局运行订阅仍保持连接', () => {
    const source = fakeEventSource()
    const store = useRunsStore()

    store.startSubscription('run-1', () => source)
    store.leaveReviewPage('run-1')

    expect(source.close).not.toHaveBeenCalled()
  })

  it('重复订阅同一运行时不创建第二个 EventSource', () => {
    const source = fakeEventSource()
    const factory = vi.fn(() => source)
    const store = useRunsStore()

    store.startSubscription('run-1', factory)
    store.startSubscription('run-1', factory)

    expect(factory).toHaveBeenCalledOnce()
    expect(store.activeRunId).toBe('run-1')
  })

  it('收到终态事件后关闭订阅并清除活动运行标识', () => {
    const source = fakeEventSource()
    const store = useRunsStore()

    store.startSubscription('run-1', () => source)
    source.onmessage?.({
      data: JSON.stringify({
        id: 'evt-1', run_id: 'run-1', sequence: 1, timestamp: '2026-07-30T01:00:00Z',
        type: 'review.completed', data: { status: 'completed' },
      }),
    } as MessageEvent<string>)

    expect(source.close).toHaveBeenCalledOnce()
    expect(store.activeRunId).toBeNull()
  })

  it('刷新后从会话存储恢复活动运行订阅', () => {
    const source = fakeEventSource()
    const factory = vi.fn(() => source)
    const values = new Map<string, string>([['reviewcrew.activeRunId', 'run-restore']])
    vi.stubGlobal('window', {
      sessionStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
      },
    })
    const store = useRunsStore()

    store.restoreSubscription(factory)

    expect(factory).toHaveBeenCalledOnce()
    expect(store.activeRunId).toBe('run-restore')
  })

  it('真实运行继续接收 SSE 时不会污染独立的离线 Demo 状态', () => {
    const source = fakeEventSource()
    const liveReview = useReviewStore()
    const demoReview = createIsolatedReviewStore(applicationPinia)
    const store = useRunsStore()

    store.startSubscription('run-live', () => source)
    demoReview.applyEvent(event('run-demo', 'demo/repository'))
    source.onmessage?.({ data: JSON.stringify(event('run-live', 'live/repository')) } as MessageEvent<string>)

    expect(demoReview.runId).toBe('run-demo')
    expect(demoReview.repository).toBe('demo/repository')
    expect(demoReview.events).toHaveLength(1)
    expect(liveReview.runId).toBe('run-live')
    expect(liveReview.repository).toBe('live/repository')
  })

  it('历史回放使用服务端 Replay 端点和两倍速且不替换活动真实订阅', () => {
    const liveSource = fakeEventSource()
    const replaySource = fakeEventSource()
    const replayFactory = vi.fn(() => replaySource)
    const store = useRunsStore()
    store.startSubscription('run-live', () => liveSource)

    const replay = createServerReplaySubscription('run-history', { onEvent: () => undefined }, replayFactory)

    expect(replayFactory).toHaveBeenCalledWith('/api/replays/run-history/events?speed=2')
    expect(store.activeRunId).toBe('run-live')
    expect(liveSource.close).not.toHaveBeenCalled()
    replay.close()
    expect(replaySource.close).toHaveBeenCalledOnce()
  })
})
