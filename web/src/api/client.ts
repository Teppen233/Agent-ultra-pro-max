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
  let hasReceivedMessage = false

  // 监听默认 message 事件（兼容所有 SSE 事件类型）
  es.onmessage = (e: MessageEvent) => {
    try {
      const data: PipelineEvent = JSON.parse(e.data)
      hasReceivedMessage = true
      onEvent(data)
    } catch {
      // 忽略解析错误
    }
  }

  es.onerror = (e) => {
    // SSE 在流正常结束和连接失败时都会触发 onerror
    if (es.readyState === EventSource.CLOSED) {
      if (hasReceivedMessage) {
        // 已收到过数据后关闭 → 正常结束
        onComplete?.()
      } else {
        // 从未成功接收数据 → 连接失败
        onError?.(e)
      }
      return
    }
    // readyState === CONNECTING → 正在重试，先报错
    if (!hasReceivedMessage) {
      onError?.(e)
    }
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
  const url = `${BASE_URL}/replays/${encodeURIComponent(runId)}/events?speed=${speed}`
  const es = new EventSource(url)
  let hasReceivedMessage = false

  es.onmessage = (e: MessageEvent) => {
    try {
      const data: PipelineEvent = JSON.parse(e.data)
      hasReceivedMessage = true
      onEvent(data)
    } catch {
      // 忽略解析错误
    }
  }

  es.onerror = (e) => {
    if (es.readyState === EventSource.CLOSED) {
      if (hasReceivedMessage) {
        onComplete?.()
      } else {
        onError?.(e)
      }
      return
    }
    if (!hasReceivedMessage) {
      onError?.(e)
    }
  }

  return es
}
