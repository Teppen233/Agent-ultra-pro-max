import { describe, expect, it, vi } from 'vitest'

import type { PipelineEvent } from '@/contracts'
import {
  createEventSubscription,
  fetchReview,
  parseEventLog,
  pollReviewResult,
  replayEventLog,
  startReview,
} from '@/api/client'

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
    const closed: string[] = []
    const subscription = createEventSubscription(
      'run-123',
      { onEvent: (event) => received.push(event.type), onClosed: (type) => closed.push(type) },
      { factory },
    )

    source.onmessage?.({ data: JSON.stringify({ ...publicEvent, type: 'review.completed' }) } as MessageEvent<string>)

    expect(received).toEqual(['review.completed'])
    expect(closed).toEqual(['review.completed'])
    expect(source.close).toHaveBeenCalledOnce()
    subscription.close()
  })

  it('区分运行中状态与完整最终结果', async () => {
    const runningFetcher = vi.fn(async () => new Response(
      JSON.stringify({ run_id: 'run-123', status: 'running' }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ))
    const response = await fetchReview('run-123', runningFetcher)

    expect(response).toEqual({ kind: 'pending', run_id: 'run-123', status: 'running' })
  })

  it('轮询运行中状态，只有完整终态才返回 ReviewResult', async () => {
    const payloads = [
      { run_id: 'run-123', status: 'running' },
      {
        run_id: 'run-123', status: 'completed', repository: 'acme/repo', base_sha: 'a', head_sha: 'b',
        findings: [], rejected_count: 0, coverage: [], warnings: [],
        started_at: '2026-07-30T01:00:00Z', completed_at: '2026-07-30T01:00:03Z', elapsed_seconds: 3,
      },
    ]
    const fetcher = vi.fn(async () => new Response(
      JSON.stringify(payloads.shift()),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ))
    const pending: string[] = []

    const result = await pollReviewResult('run-123', {
      fetcher,
      wait: async () => undefined,
      onPending: (status) => pending.push(status.status),
    })

    expect(pending).toEqual(['running'])
    expect(result.kind).toBe('result')
    if (result.kind === 'result') expect(result.result.repository).toBe('acme/repo')
  })

  it('请求返回前取消轮询时不会交付过期最终结果', async () => {
    const controller = new AbortController()
    let releaseResponse: (() => void) | undefined
    const fetcher = vi.fn(async () => {
      await new Promise<void>((resolve) => { releaseResponse = resolve })
      return new Response(JSON.stringify({
        run_id: 'run-123', status: 'completed', repository: 'acme/repo', base_sha: 'a', head_sha: 'b',
        findings: [], rejected_count: 0, coverage: [], warnings: [],
        started_at: '2026-07-30T01:00:00Z', completed_at: '2026-07-30T01:00:03Z', elapsed_seconds: 3,
      }), { status: 200, headers: { 'content-type': 'application/json' } })
    })

    const polling = pollReviewResult('run-123', { fetcher, signal: controller.signal })
    controller.abort()
    releaseResponse?.()

    await expect(polling).resolves.toEqual({ kind: 'pending', run_id: 'run-123', status: 'cancelled' })
  })

  it('AbortSignal 或失效运行令牌会停止离线 Replay 写入', async () => {
    const controller = new AbortController()
    let currentToken = 'token-1'
    const received: number[] = []
    const log = [
      publicEvent,
      { ...publicEvent, id: 'evt-2', sequence: 2, timestamp: '2026-07-30T01:00:02Z' },
    ].map((item) => JSON.stringify(item)).join('\n')

    await replayEventLog(log, (item) => {
      received.push(item.sequence)
      currentToken = 'token-2'
      controller.abort()
    }, {
      speed: 2,
      signal: controller.signal,
      runToken: 'token-1',
      isCurrent: (token) => token === currentToken,
      wait: async () => undefined,
    })

    expect(received).toEqual([1])
  })
})
