import { describe, expect, it, vi } from 'vitest'

import type { PipelineEvent } from '@/contracts'
import { createEventSubscription, parseEventLog, replayEventLog, startReview } from '@/api/client'

const publicEvent: PipelineEvent = {
  id: 'evt-1',
  run_id: 'run-demo',
  sequence: 1,
  timestamp: '2026-07-30T01:00:00Z',
  type: 'review.started',
  data: { mode: 'github' },
}

describe('API Client', () => {
  it('按公开契约提交审查请求并解析运行标识', async () => {
    const fetcher = vi.fn(async () => new Response(
      JSON.stringify({ run_id: 'run-123', status: 'running' }),
      { status: 202, headers: { 'content-type': 'application/json' } },
    ))

    const result = await startReview({ pr_url: 'https://github.com/acme/repo/pull/7' }, fetcher)

    expect(result).toEqual({ run_id: 'run-123', status: 'running' })
    expect(fetcher).toHaveBeenCalledWith('/api/reviews', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pr_url: 'https://github.com/acme/repo/pull/7' }),
    })
  })

  it('将 HTTP 中文 detail 转换为用户可恢复错误', async () => {
    const fetcher = vi.fn(async () => new Response(
      JSON.stringify({ detail: '审查请求参数无效，请检查后重试。' }),
      { status: 422, headers: { 'content-type': 'application/json' } },
    ))

    await expect(startReview({ pr_url: 'invalid' }, fetcher)).rejects.toThrow(
      '审查请求参数无效，请检查后重试。',
    )
  })

  it('只解析六字段公开事件并忽略空行', () => {
    const log = `\n${JSON.stringify(publicEvent)}\n${JSON.stringify({ ...publicEvent, sequence: 2, id: 'evt-2' })}\n`

    expect(parseEventLog(log).map((event) => event.sequence)).toEqual([1, 2])
  })

  it('离线回放按顺序发送事件且可调整速度', async () => {
    const received: number[] = []
    const wait = vi.fn(async () => undefined)
    const log = [
      publicEvent,
      { ...publicEvent, id: 'evt-2', sequence: 2, timestamp: '2026-07-30T01:00:02Z' },
    ].map((event) => JSON.stringify(event)).join('\n')

    await replayEventLog(log, (event) => received.push(event.sequence), { speed: 2, wait })

    expect(received).toEqual([1, 2])
    expect(wait).toHaveBeenCalledWith(1000)
  })

  it('收到终态后主动关闭 EventSource，避免断线重连污染终态', () => {
    const source = {
      onopen: null as (() => void) | null,
      onmessage: null as ((event: MessageEvent<string>) => void) | null,
      onerror: null as (() => void) | null,
      close: vi.fn(),
    }
    const received: string[] = []
    const factory = vi.fn(() => source)
    const subscription = createEventSubscription(
      'run-123',
      { onEvent: (event) => received.push(event.type) },
      { factory },
    )

    source.onmessage?.({ data: JSON.stringify({ ...publicEvent, type: 'review.completed' }) } as MessageEvent<string>)

    expect(received).toEqual(['review.completed'])
    expect(source.close).toHaveBeenCalledOnce()
    subscription.close()
  })
})
