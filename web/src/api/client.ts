import type { ReviewRequest, PipelineEvent, Finding } from '../contracts'

const BASE_URL = '/api'

export interface ReviewCreated {
  run_id: string
  status: string
}

export interface ReviewStatus {
  run_id: string
  status: string
  events: PipelineEvent[]
  findings: Finding[]
  report_url?: string
}

/** 启动审查 */
export async function startReview(request: ReviewRequest): Promise<ReviewCreated> {
  const res = await fetch(`${BASE_URL}/reviews`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!res.ok) {
    throw new Error(`启动审查失败: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

/** 获取审查状态 */
export async function getStatus(runId: string): Promise<ReviewStatus> {
  const res = await fetch(`${BASE_URL}/reviews/${encodeURIComponent(runId)}`)
  if (!res.ok) {
    throw new Error(`获取状态失败: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

/** 连接 SSE 实时事件流 */
export function connectSSE(
  runId: string,
  onEvent: (event: PipelineEvent) => void,
  onError?: (err: Event) => void,
  onComplete?: () => void
): EventSource {
  const url = `${BASE_URL}/reviews/${encodeURIComponent(runId)}/events`
  const es = new EventSource(url)

  es.addEventListener('event', (e: MessageEvent) => {
    try {
      const data: PipelineEvent = JSON.parse(e.data)
      onEvent(data)
    } catch {
      // 忽略解析错误
    }
  })

  es.addEventListener('done', () => {
    es.close()
    onComplete?.()
  })

  es.onerror = (e) => {
    onError?.(e)
  }

  return es
}

/** 获取 Markdown 报告 */
export async function getReport(runId: string): Promise<string> {
  const res = await fetch(`${BASE_URL}/reviews/${encodeURIComponent(runId)}/report`, {
    headers: { Accept: 'text/markdown' },
  })
  if (!res.ok) {
    throw new Error(`获取报告失败: ${res.status} ${res.statusText}`)
  }
  return res.text()
}

/** 重放历史事件流（Replay） */
export function replayEvents(
  runId: string,
  speed: number,
  onEvent: (event: PipelineEvent) => void,
  onError?: (err: Event) => void,
  onComplete?: () => void
): EventSource {
  const url = `${BASE_URL}/reviews/${encodeURIComponent(runId)}/replay?speed=${speed}`
  const es = new EventSource(url)

  es.addEventListener('event', (e: MessageEvent) => {
    try {
      const data: PipelineEvent = JSON.parse(e.data)
      onEvent(data)
    } catch {
      // 忽略解析错误
    }
  })

  es.addEventListener('done', () => {
    es.close()
    onComplete?.()
  })

  es.onerror = (e) => {
    onError?.(e)
  }

  return es
}
