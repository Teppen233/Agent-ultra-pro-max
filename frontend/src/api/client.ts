import type {
  BenchmarkSummary,
  EventType,
  PipelineEvent,
  RepositoryBenchmarkStatus,
  ReviewRequest,
  ReviewResponse,
  ReviewResult,
  RunsResponse,
  StartReviewResponse,
} from '@/contracts'

type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

interface EventSourceLike {
  onopen: (() => void) | null
  onmessage: ((event: MessageEvent<string>) => void) | null
  onerror: (() => void) | null
  close(): void
}

interface SubscriptionHandlers {
  onEvent(event: PipelineEvent): void
  onOpen?(): void
  onDisconnect?(): void
  onError?(message: string): void
  onClosed?(terminalType: 'review.completed' | 'review.failed'): void
}

interface SubscriptionOptions {
  replay?: boolean
  speed?: number
  factory?: (url: string) => EventSourceLike
}

interface ReplayOptions {
  speed?: number
  wait?: (milliseconds: number) => Promise<void>
  signal?: AbortSignal
  runToken?: string
  isCurrent?: (token: string) => boolean
}

interface PollOptions {
  fetcher?: Fetcher
  wait?: (milliseconds: number) => Promise<void>
  signal?: AbortSignal
  intervalMs?: number
  onPending?(response: Extract<ReviewResponse, { kind: 'pending' }>): void
}

const eventTypes = new Set<EventType>([
  'review.started', 'review.completed', 'review.failed',
  'stage.started', 'stage.completed', 'stage.failed',
  'agent.started', 'agent.tool', 'agent.candidate', 'agent.completed', 'agent.failed',
  'verifier.started', 'verifier.accepted', 'verifier.rejected', 'verifier.completed',
  'report.generated',
])

const configuredBase = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/$/, '')

const apiUrl = (path: string): string => `${configuredBase}${path}`

const readError = async (response: Response): Promise<string> => {
  try {
    const body = await response.json() as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // 非 JSON 响应统一转为稳定中文提示，不向用户暴露代理或服务器原文。
  }
  return `请求失败（HTTP ${response.status}），请稍后重试。`
}

const requestJson = async <T>(path: string, init?: RequestInit, fetcher: Fetcher = fetch): Promise<T> => {
  const response = await fetcher(apiUrl(path), init)
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<T>
}

const asPipelineEvent = (value: unknown): PipelineEvent => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('事件格式无效。')
  const event = value as Record<string, unknown>
  if (
    typeof event.id !== 'string'
    || typeof event.run_id !== 'string'
    || typeof event.sequence !== 'number'
    || !Number.isInteger(event.sequence)
    || event.sequence < 1
    || typeof event.timestamp !== 'string'
    || typeof event.type !== 'string'
    || !eventTypes.has(event.type as EventType)
    || !event.data
    || typeof event.data !== 'object'
    || Array.isArray(event.data)
  ) {
    throw new Error('事件格式无效。')
  }
  return {
    id: event.id,
    run_id: event.run_id,
    sequence: event.sequence,
    timestamp: event.timestamp,
    type: event.type as EventType,
    data: event.data as Record<string, unknown>,
  }
}

/** 启动真实 PR、本地提交或服务端 Replay 审查。 */
export const startReview = (
  request: ReviewRequest,
  fetcher: Fetcher = fetch,
): Promise<StartReviewResponse> => requestJson('/api/reviews', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(request),
}, fetcher)

const asReviewResponse = (value: unknown): ReviewResponse => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('运行状态格式无效。')
  const payload = value as Record<string, unknown>
  if (typeof payload.run_id !== 'string' || typeof payload.status !== 'string') {
    throw new Error('运行状态格式无效。')
  }
  const terminal = ['completed', 'partial', 'failed'].includes(payload.status)
  const completeResult = (
    typeof payload.repository === 'string'
    && typeof payload.base_sha === 'string'
    && typeof payload.head_sha === 'string'
    && Array.isArray(payload.findings)
    && typeof payload.rejected_count === 'number'
    && Array.isArray(payload.coverage)
    && Array.isArray(payload.warnings)
    && typeof payload.started_at === 'string'
    && typeof payload.completed_at === 'string'
    && typeof payload.elapsed_seconds === 'number'
  )
  if (terminal && completeResult) return { kind: 'result', result: payload as unknown as ReviewResult }
  if (payload.status === 'failed') return { kind: 'failed', run_id: payload.run_id, status: 'failed' }
  if (!terminal) return { kind: 'pending', run_id: payload.run_id, status: payload.status }
  throw new Error('最终审查结果尚未完整生成。')
}

const asBenchmarkSummary = (value: unknown): BenchmarkSummary => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('评测摘要格式无效。')
  const payload = value as Record<string, unknown>
  const integerFields = [
    'selected_cases', 'completed_cases', 'actually_run_ready_cases', 'caught_cases',
    'false_positive_count', 'verifier_accepted_count', 'verifier_rejected_count',
    'needs_human_review_cases', 'timed_out_cases',
  ]
  const validIntegerFields = integerFields.every((field) =>
    typeof payload[field] === 'number' && Number.isInteger(payload[field]) && (payload[field] as number) >= 0)
  const validRate = (rate: unknown): boolean =>
    rate === null || (typeof rate === 'number' && Number.isFinite(rate) && rate >= 0 && rate <= 1)
  const validNonNegativeInteger = (field: unknown): boolean =>
    typeof field === 'number' && Number.isInteger(field) && field >= 0
  const validElapsed = (field: unknown): boolean =>
    typeof field === 'number' && Number.isFinite(field) && field >= 0
  const repositoryStatuses = new Set<RepositoryBenchmarkStatus>([
    'needs_data', 'pending', 'running', 'completed', 'partial', 'failed',
  ])
  const validCase = (value: unknown): boolean => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false
    const item = value as Record<string, unknown>
    const judge = item.judge
    if (!judge || typeof judge !== 'object' || Array.isArray(judge)) return false
    const decision = judge as Record<string, unknown>
    return typeof item.case_id === 'string'
      && typeof item.project === 'string'
      && typeof item.language === 'string'
      && typeof item.status === 'string'
      && ['completed', 'partial', 'failed'].includes(item.status)
      && validElapsed(item.elapsed_seconds)
      && typeof item.timed_out === 'boolean'
      && (typeof item.run_id === 'string' || item.run_id === null)
      && typeof decision.caught === 'boolean'
      && (typeof decision.matched_finding_id === 'string' || decision.matched_finding_id === null)
      && typeof decision.location_match === 'boolean'
      && typeof decision.semantic_match === 'boolean'
      && (decision.used_line_tolerance === null || (
        typeof decision.used_line_tolerance === 'number' && Number.isInteger(decision.used_line_tolerance)
      ))
      && typeof decision.needs_human_review === 'boolean'
      && typeof decision.reason === 'string'
      && validNonNegativeInteger(decision.false_positive_count)
      && validNonNegativeInteger(decision.verifier_accepted_count)
      && validNonNegativeInteger(decision.verifier_rejected_count)
  }
  const validRepository = (value: unknown): boolean => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false
    const repository = value as Record<string, unknown>
    const countFields = [
      'total_cases', 'verified_cases', 'executed_cases', 'target_caught', 'other_findings', 'rejected_count',
    ]
    return typeof repository.repository === 'string'
      && typeof repository.language === 'string'
      && countFields.every((field) => validNonNegativeInteger(repository[field]))
      && validElapsed(repository.elapsed_seconds)
      && typeof repository.status === 'string'
      && repositoryStatuses.has(repository.status as RepositoryBenchmarkStatus)
      && (typeof repository.latest_run_id === 'string' || repository.latest_run_id === null)
      && validRate(repository.catch_rate)
      && validRate(repository.observed_offline_catch_rate)
      && Array.isArray(repository.cases)
      && repository.cases.every(validCase)
  }
  if (
    typeof payload.mode !== 'string'
    || !['quick', 'case', 'full'].includes(payload.mode)
    || typeof payload.runner !== 'string'
    || !['fake', 'real'].includes(payload.runner)
    || typeof payload.offline !== 'boolean'
    || !validIntegerFields
    || !validRate(payload.real_catch_rate)
    || !validRate(payload.observed_offline_catch_rate)
    || typeof payload.offline_results_excluded_from_real_rate !== 'boolean'
    || typeof payload.elapsed_seconds !== 'number'
    || !Number.isFinite(payload.elapsed_seconds)
    || payload.elapsed_seconds < 0
    || !Array.isArray(payload.repositories)
    || !payload.repositories.every(validRepository)
  ) {
    throw new Error('评测摘要格式无效。')
  }
  return payload as unknown as BenchmarkSummary
}

/** 获取一次运行的可辨识状态或完整最终结果。 */
export const fetchReview = async (runId: string, fetcher: Fetcher = fetch): Promise<ReviewResponse> =>
  asReviewResponse(await requestJson<unknown>(`/api/reviews/${encodeURIComponent(runId)}`, undefined, fetcher))

/** 轮询直到完整最终结果可用；运行中响应不会进入 Store 水合。 */
export const pollReviewResult = async (runId: string, options: PollOptions = {}): Promise<ReviewResponse> => {
  const wait = options.wait ?? ((milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds)))
  while (!options.signal?.aborted) {
    const response = await fetchReview(runId, options.fetcher)
    if (options.signal?.aborted) break
    if (response.kind !== 'pending') return response
    options.onPending?.(response)
    await wait(options.intervalMs ?? 1000)
  }
  return { kind: 'pending', run_id: runId, status: 'cancelled' }
}

/** 获取有界历史运行列表。 */
export const fetchRuns = (limit = 50, offset = 0): Promise<RunsResponse> =>
  requestJson(`/api/runs?limit=${limit}&offset=${offset}`)

/** 获取最近一次真实 Benchmark 摘要。 */
export const fetchLatestBenchmark = async (): Promise<BenchmarkSummary> =>
  asBenchmarkSummary(await requestJson<unknown>('/api/benchmarks/latest'))

/** 返回后端 Markdown 报告地址，供查看或下载。 */
export const reportUrl = (runId: string): string =>
  apiUrl(`/api/reviews/${encodeURIComponent(runId)}/report?format=markdown`)

/** 从 JSONL fixture 解析脱敏后的公开事件。 */
export const parseEventLog = (content: string): PipelineEvent[] => content
  .split(/\r?\n/)
  .filter((line) => line.trim().length > 0)
  .map((line) => asPipelineEvent(JSON.parse(line) as unknown))
  .sort((left, right) => left.sequence - right.sequence)

/** 在浏览器本地播放 JSONL；真实 SSE 与离线演示最终都调用同一个 applyEvent。 */
export const replayEventLog = async (
  content: string,
  onEvent: (event: PipelineEvent) => void,
  options: ReplayOptions = {},
): Promise<void> => {
  const speed = options.speed ?? 4
  if (!Number.isFinite(speed) || speed <= 0) throw new Error('回放速度必须大于零。')
  const wait = options.wait ?? ((milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds)))
  const events = parseEventLog(content)
  let previous: PipelineEvent | undefined
  for (const event of events) {
    if (options.signal?.aborted) return
    if (options.runToken && options.isCurrent && !options.isCurrent(options.runToken)) return
    if (previous) {
      const gap = Math.max(0, Date.parse(event.timestamp) - Date.parse(previous.timestamp))
      await wait(Math.min(1800, gap / speed))
    }
    if (options.signal?.aborted) return
    if (options.runToken && options.isCurrent && !options.isCurrent(options.runToken)) return
    onEvent(event)
    previous = event
  }
}

/**
 * 建立实时或服务端 Replay SSE。浏览器错误时保留连接让 EventSource 自动重连；
 * 收到终态后主动关闭，避免终态之后被重复连接污染。
 */
export const createEventSubscription = (
  runId: string,
  handlers: SubscriptionHandlers,
  options: SubscriptionOptions = {},
): { close(): void } => {
  const path = options.replay
    ? `/api/replays/${encodeURIComponent(runId)}/events?speed=${options.speed ?? 1}`
    : `/api/reviews/${encodeURIComponent(runId)}/events`
  const factory = options.factory ?? ((url: string) => new EventSource(url))
  const source = factory(apiUrl(path))
  let closed = false

  const close = (): void => {
    if (closed) return
    closed = true
    source.close()
  }

  source.onopen = () => handlers.onOpen?.()
  source.onerror = () => {
    if (!closed) handlers.onDisconnect?.()
  }
  source.onmessage = (message: MessageEvent<string>) => {
    try {
      const event = asPipelineEvent(JSON.parse(message.data) as unknown)
      handlers.onEvent(event)
      if (event.type === 'review.completed' || event.type === 'review.failed') {
        handlers.onClosed?.(event.type)
        close()
      }
    } catch {
      handlers.onError?.('收到无法识别的审查事件，已跳过。')
    }
  }

  return { close }
}
