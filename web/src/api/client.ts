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

  es.onopen = () => {
    console.log('[SSE] 连接已建立:', url)
  }

  // 监听默认 message 事件（兼容所有 SSE 事件类型）
  es.onmessage = (e: MessageEvent) => {
    try {
      const data: PipelineEvent = JSON.parse(e.data)
      hasReceivedMessage = true
      console.log('[SSE] 收到事件:', data.type, 'seq:', data.sequence)
      onEvent(data)
    } catch (err) {
      console.error('[SSE] 解析事件失败:', err, 'raw:', e.data?.substring(0, 200))
    }
  }

  es.onerror = (e) => {
    console.log('[SSE] onerror, readyState:', es.readyState, 'hasMsg:', hasReceivedMessage)
    if (es.readyState === EventSource.CLOSED) {
      if (hasReceivedMessage) {
        // 已收到过数据后关闭 → 正常结束
        onComplete?.()
      } else {
        // 重试耗尽仍未收到数据 → 连接彻底失败
        onError?.(e)
      }
    }
    // readyState === CONNECTING → 自动重试中，不报错，等待重连
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
  const esR = new EventSource(url)
  let hasReceivedMessageR = false

  esR.onopen = () => {
    console.log('[SSE Replay] 连接已建立:', url)
  }

  esR.onmessage = (e: MessageEvent) => {
    try {
      const data: PipelineEvent = JSON.parse(e.data)
      hasReceivedMessageR = true
      console.log('[SSE Replay] 收到事件:', data.type, 'seq:', data.sequence)
      onEvent(data)
    } catch (err) {
      console.error('[SSE Replay] 解析失败:', err, 'raw:', e.data?.substring(0, 200))
    }
  }

  esR.onerror = (e) => {
    console.log('[SSE Replay] onerror, readyState:', esR.readyState, 'hasMsg:', hasReceivedMessageR)
    if (esR.readyState === EventSource.CLOSED) {
      if (hasReceivedMessageR) {
        onComplete?.()
      } else {
        onError?.(e)
      }
    }
  }

  return esR
}
