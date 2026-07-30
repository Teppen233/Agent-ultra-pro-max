import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PipelineEvent } from '@/contracts'
import {
  createEventSubscription,
  fetchLatestBenchmark,
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
  afterEach(() => vi.unstubAllGlobals())

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

  it('解析计划、工具与 Mailbox 新事件契约', () => {
    const types = ['plan.published', 'tool.started', 'tool.completed', 'tool.failed', 'mailbox.message']
    const log = types.map((type, index) => JSON.stringify({
      ...publicEvent,
      id: `evt-contract-${index + 1}`,
      sequence: index + 1,
      type,
      data: {},
    })).join('\n')

    expect(parseEventLog(log).map((item) => item.type)).toEqual(types)
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

  it('离线回放与服务端一致，只接受固定的五档倍速', async () => {
    await expect(replayEventLog(JSON.stringify(publicEvent), () => undefined, { speed: 3 }))
      .rejects.toThrow('回放速度仅支持')
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

  it('将仅含状态的失败响应建模为失败，而不是不完整结果错误', async () => {
    const failedFetcher = vi.fn(async () => new Response(
      JSON.stringify({ run_id: 'run-123', status: 'failed' }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ))

    await expect(fetchReview('run-123', failedFetcher)).resolves.toEqual({
      kind: 'failed', run_id: 'run-123', status: 'failed',
    })
  })

  it('拒绝字段缺失或类型错误的 Benchmark 摘要', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      mode: 'quick', runner: 'real', offline: false, selected_cases: 5,
      completed_cases: 5, caught_cases: 3, real_catch_rate: 0.6,
    }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetcher)

    await expect(fetchLatestBenchmark()).rejects.toThrow('评测摘要格式无效。')
  })

  it('拒绝用数组伪装的 Benchmark 枚举字段', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      mode: ['quick'], runner: ['real'], offline: false, selected_cases: 5, completed_cases: 5,
      actually_run_ready_cases: 5, caught_cases: 3, real_catch_rate: 0.6,
      observed_offline_catch_rate: null, offline_results_excluded_from_real_rate: false,
      false_positive_count: 0, verifier_accepted_count: 3, verifier_rejected_count: 0,
      needs_human_review_cases: 0, timed_out_cases: 0, elapsed_seconds: 12,
    }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetcher)

    await expect(fetchLatestBenchmark()).rejects.toThrow('评测摘要格式无效。')
  })

  it('拒绝缺少逐仓状态与统计字段的 Benchmark 摘要', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      mode: 'quick', runner: 'real', offline: false, selected_cases: 1, completed_cases: 1,
      actually_run_ready_cases: 1, caught_cases: 0, real_catch_rate: 0,
      observed_offline_catch_rate: null, offline_results_excluded_from_real_rate: false,
      false_positive_count: 0, verifier_accepted_count: 0, verifier_rejected_count: 0,
      needs_human_review_cases: 0, timed_out_cases: 0, elapsed_seconds: 10,
      repositories: [{ repository: 'sentry', language: 'Python' }],
    }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetcher)

    await expect(fetchLatestBenchmark()).rejects.toThrow('评测摘要格式无效。')
  })

  it('拒绝缺少 Judge 完整判定字段的逐案例 Benchmark 摘要', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      mode: 'case', runner: 'real', offline: false, selected_cases: 1, completed_cases: 1,
      actually_run_ready_cases: 1, caught_cases: 1, real_catch_rate: 1,
      observed_offline_catch_rate: null, offline_results_excluded_from_real_rate: false,
      false_positive_count: 0, verifier_accepted_count: 1, verifier_rejected_count: 0,
      needs_human_review_cases: 0, timed_out_cases: 0, elapsed_seconds: 10,
      repositories: [{
        repository: 'sentry', language: 'Python', total_cases: 1, verified_cases: 1, executed_cases: 1,
        target_caught: 1, other_findings: 0, rejected_count: 0, elapsed_seconds: 10,
        status: 'completed', latest_run_id: 'run-20260730-012450-d90a1b5b', catch_rate: 1,
        observed_offline_catch_rate: null,
        cases: [{
          case_id: 'sentry-01', project: 'sentry', language: 'Python', status: 'completed',
          elapsed_seconds: 10, timed_out: false, run_id: 'run-20260730-012450-d90a1b5b',
          judge: {
            caught: true, matched_finding_id: 'finding-1', location_match: true,
            used_line_tolerance: 0, needs_human_review: false, reason: '命中',
            false_positive_count: 0, verifier_accepted_count: 1, verifier_rejected_count: 0,
          },
        }],
      }],
    }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetcher)

    await expect(fetchLatestBenchmark()).rejects.toThrow('评测摘要格式无效。')
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
