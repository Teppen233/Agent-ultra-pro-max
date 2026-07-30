import { defineStore } from 'pinia'

import { demoDiff, demoEvents } from '@/demo'
import type {
  DispatchEntry,
  Finding,
  PipelineEvent,
  RunDetail,
  RunSummary,
  WorkflowEdge,
  WorkflowNode,
  WorkflowStatus,
} from '@/types'

interface ReviewState {
  runId: string | null
  events: PipelineEvent[]
  findings: Finding[]
  workflowNodes: WorkflowNode[]
  workflowEdges: WorkflowEdge[]
  dispatchLog: DispatchEntry[]
  selectedNodeId: string | null
  report: string | null
  diff: string | null
  runs: RunSummary[]
  loading: boolean
  replaying: boolean
  live: boolean
  error: string | null
  source: EventSource | null
  concurrencyPeak: number
  replayEvents: PipelineEvent[]
  replayIndex: number
  replaySpeed: ReplaySpeed
  replayTimer: number | null
}

export type ReplaySpeed = 0.5 | 1 | 2 | 4

const statusTone = (status: WorkflowStatus): DispatchEntry['tone'] => {
  if (status === 'running') return 'active'
  if (status === 'completed') return 'success'
  if (status === 'failed' || status === 'cancelled') return 'danger'
  return 'neutral'
}

function asPipelineEvent(value: unknown): PipelineEvent | null {
  if (typeof value !== 'object' || value === null || !('type' in value)) return null
  const type = Reflect.get(value, 'type')
  const timestamp = Reflect.get(value, 'timestamp')
  if (typeof type !== 'string' || typeof timestamp !== 'number') return null
  return value as PipelineEvent
}

function cloneEvent(event: PipelineEvent): PipelineEvent {
  return JSON.parse(JSON.stringify(event)) as PipelineEvent
}

async function responseError(response: Response, fallback: string) {
  const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null
  if (typeof payload?.detail === 'string') return payload.detail
  return `${fallback}（HTTP ${response.status}）`
}

export const useReviewStore = defineStore('review', {
  state: (): ReviewState => ({
    runId: null,
    events: [],
    findings: [],
    workflowNodes: [],
    workflowEdges: [],
    dispatchLog: [],
    selectedNodeId: null,
    report: null,
    diff: null,
    runs: [],
    loading: false,
    replaying: false,
    live: false,
    error: null,
    source: null,
    concurrencyPeak: 0,
    replayEvents: [],
    replayIndex: 0,
    replaySpeed: 1,
    replayTimer: null,
  }),
  getters: {
    retainedFindings: (state) => state.findings.filter((item) => item.verdict !== 'reject'),
    rejectedCount: (state) => state.findings.filter((item) => item.verdict === 'reject').length,
    elapsedSeconds: (state) => {
      const first = state.events[0]?.timestamp
      const last = state.events.at(-1)?.timestamp
      return first === undefined || last === undefined ? 0 : Math.max(0, last - first)
    },
    activeAgentCount: (state) =>
      state.workflowNodes.filter(
        (node) =>
          node.status === 'running' &&
          (node.kind === 'agent_task' || node.kind === 'verifier' || node.kind === 'coordinator'),
      ).length,
    taskCounts: (state): Record<WorkflowStatus, number> => {
      const counts: Record<WorkflowStatus, number> = {
        queued: 0,
        running: 0,
        waiting: 0,
        completed: 0,
        failed: 0,
        cancelled: 0,
      }
      for (const node of state.workflowNodes) {
        if (node.kind === 'agent_task' || node.kind === 'verifier') counts[node.status] += 1
      }
      return counts
    },
    selectedWorkflowNode: (state) =>
      state.workflowNodes.find((node) => node.id === state.selectedNodeId) ?? null,
    layoutWorkflowNodes: (state): WorkflowNode[] => {
      const nodes = new Map<string, WorkflowNode>()
      for (const event of state.replayEvents) {
        if (event.type === 'workflow_node') nodes.set(event.workflow_node.id, event.workflow_node)
      }
      return [...nodes.values()]
    },
    layoutWorkflowEdges: (state): WorkflowEdge[] => {
      const edges = new Map<string, WorkflowEdge>()
      for (const event of state.replayEvents) {
        if (event.type === 'workflow_edge') edges.set(event.workflow_edge.id, event.workflow_edge)
      }
      return [...edges.values()]
    },
  },
  actions: {
    clearVisualState() {
      this.events = []
      this.findings = []
      this.workflowNodes = []
      this.workflowEdges = []
      this.dispatchLog = []
      this.selectedNodeId = null
      this.report = null
      this.diff = null
      this.error = null
      this.concurrencyPeak = 0
    },
    pauseReplay() {
      if (this.replayTimer !== null) window.clearTimeout(this.replayTimer)
      this.replayTimer = null
      this.replaying = false
    },
    stopSource() {
      this.source?.close()
      this.source = null
      this.live = false
    },
    reset() {
      this.pauseReplay()
      this.stopSource()
      this.clearVisualState()
      this.replayEvents = []
      this.replayIndex = 0
    },
    consume(event: PipelineEvent) {
      this.events.push(event)
      if (event.type === 'workflow_node') {
        const node = event.workflow_node
        const existing = this.workflowNodes.findIndex((item) => item.id === node.id)
        if (existing >= 0) this.workflowNodes.splice(existing, 1, node)
        else this.workflowNodes.push(node)
        if (node.kind === 'agent_task' || node.kind === 'verifier' || node.kind === 'coordinator') {
          this.dispatchLog.unshift({
            id: `${event.timestamp}-${node.id}-${node.status}`,
            timestamp: event.timestamp,
            title: node.label,
            detail: node.detail ?? this.statusLabel(node.status),
            tone: statusTone(node.status),
          })
          this.dispatchLog = this.dispatchLog.slice(0, 24)
        }
        this.concurrencyPeak = Math.max(this.concurrencyPeak, this.activeAgentCount)
      } else if (event.type === 'workflow_edge') {
        const edge = event.workflow_edge
        const existing = this.workflowEdges.findIndex((item) => item.id === edge.id)
        if (existing >= 0) this.workflowEdges.splice(existing, 1, edge)
        else this.workflowEdges.push(edge)
        if (edge.relation === 'handoff') {
          this.dispatchLog.unshift({
            id: `${event.timestamp}-${edge.id}`,
            timestamp: event.timestamp,
            title: '触发跨 Agent 交叉验证',
            detail: `${edge.source} 将高风险结论移交给 ${edge.target}`,
            tone: 'active',
          })
        }
      } else if (event.type === 'snapshot') {
        this.dispatchLog.unshift({
          id: `${event.timestamp}-${event.task_id ?? 'checkpoint'}`,
          timestamp: event.timestamp,
          title: '阶段性结果已保存',
          detail: event.text ?? `累计 ${event.snapshot_findings?.length ?? 0} 条候选 Finding`,
          tone: 'success',
        })
        this.dispatchLog = this.dispatchLog.slice(0, 24)
      } else if (event.type === 'finding') {
        const existing = this.findings.findIndex((item) => item.id === event.finding.id)
        if (existing >= 0) this.findings.splice(existing, 1, event.finding)
        else this.findings.unshift(event.finding)
      } else if (event.type === 'verdict') {
        const finding = this.findings.find((item) => item.id === event.verdict.finding_id)
        if (finding) {
          finding.verdict = event.verdict.verdict
          finding.verdict_reason = event.verdict.reason
          finding.confidence_adjusted = event.verdict.confidence_adjusted
        }
      } else if (event.type === 'report') {
        this.report = event.markdown
      } else if (event.type === 'stage' && event.status === 'error') {
        this.error = event.text || '审查任务执行失败'
      }
    },
    statusLabel(status: WorkflowStatus) {
      const labels: Record<WorkflowStatus, string> = {
        queued: '等待调度',
        running: '正在执行',
        waiting: '等待验证',
        completed: '执行完成',
        failed: '执行失败',
        cancelled: '已取消',
      }
      return labels[status]
    },
    selectNode(nodeId: string | null) {
      this.selectedNodeId = nodeId
    },
    rebuildReplay(index: number) {
      const target = Math.min(this.replayEvents.length, Math.max(0, Math.floor(index)))
      this.pauseReplay()
      this.clearVisualState()
      for (let eventIndex = 0; eventIndex < target; eventIndex += 1) {
        const event = this.replayEvents[eventIndex]
        if (event) this.consume(cloneEvent(event))
      }
      this.replayIndex = target
    },
    setReplaySource(events: PipelineEvent[], atEnd = true) {
      this.pauseReplay()
      this.stopSource()
      this.replayEvents = events.map(cloneEvent)
      this.replayIndex = 0
      this.clearVisualState()
      if (atEnd) this.rebuildReplay(this.replayEvents.length)
    },
    seekReplay(index: number) {
      this.rebuildReplay(index)
    },
    stepReplay(delta: -1 | 1) {
      this.rebuildReplay(this.replayIndex + delta)
    },
    setReplaySpeed(speed: ReplaySpeed) {
      if (this.replaySpeed === speed) return
      const wasPlaying = this.replaying
      this.pauseReplay()
      this.replaySpeed = speed
      if (wasPlaying) this.playReplay()
    },
    replayDelay() {
      const next = this.replayEvents[this.replayIndex]
      const current = this.replayEvents[this.replayIndex - 1]
      const rawDelay = next && current ? Math.max(0, next.timestamp - current.timestamp) * 1000 : 220
      return Math.min(900, Math.max(220, rawDelay)) / this.replaySpeed
    },
    scheduleReplay() {
      if (!this.replaying) return
      if (this.replayIndex >= this.replayEvents.length) {
        this.pauseReplay()
        return
      }
      this.replayTimer = window.setTimeout(() => {
        this.replayTimer = null
        const event = this.replayEvents[this.replayIndex]
        if (event) {
          this.consume(cloneEvent(event))
          this.replayIndex += 1
        }
        this.scheduleReplay()
      }, this.replayDelay())
    },
    playReplay() {
      if (this.live || this.replaying || this.replayEvents.length === 0) return
      if (this.replayIndex >= this.replayEvents.length) this.rebuildReplay(0)
      this.replaying = true
      this.scheduleReplay()
    },
    restartReplay() {
      if (this.live || this.replayEvents.length === 0) return
      this.rebuildReplay(0)
      this.playReplay()
    },
    async startReview(prUrl: string, repoPath: string) {
      this.reset()
      this.loading = true
      try {
        const response = await fetch('/api/review', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pr_url: prUrl, repo_path: repoPath }),
        })
        if (!response.ok) throw new Error(await responseError(response, '审查任务启动失败'))
        const payload = (await response.json()) as { run_id: string }
        this.runId = payload.run_id
        this.connectLive(payload.run_id)
        return payload.run_id
      } catch (error: unknown) {
        this.error = error instanceof Error ? error.message : '审查任务启动失败'
        throw error
      } finally {
        this.loading = false
      }
    },
    connectLive(runId: string) {
      this.pauseReplay()
      this.stopSource()
      this.clearVisualState()
      this.replayEvents = []
      this.replayIndex = 0
      this.runId = runId
      this.live = true
      const source = new EventSource(`/api/stream/${encodeURIComponent(runId)}`)
      this.source = source
      const eventTypes: PipelineEvent['type'][] = [
        'run',
        'stage',
        'workflow_node',
        'workflow_edge',
        'agent',
        'thought',
        'tool',
        'snapshot',
        'finding',
        'verdict',
        'report',
      ]
      for (const eventType of eventTypes) {
        source.addEventListener(eventType, (message) => {
          if (!(message instanceof MessageEvent) || typeof message.data !== 'string') return
          const parsed = asPipelineEvent(JSON.parse(message.data) as unknown)
          if (!parsed) return
          this.replayEvents.push(cloneEvent(parsed))
          this.consume(parsed)
          this.replayIndex = this.replayEvents.length
          if (
            parsed.type === 'report' ||
            (parsed.type === 'stage' && parsed.status === 'error')
          ) {
            source.close()
            if (this.source === source) this.source = null
            this.live = false
          }
        })
      }
      source.onerror = () => {
        source.close()
        if (this.source === source) this.source = null
        this.live = false
        if (!this.report) this.error = '事件流连接已中断'
      }
    },
    async loadRun(runId: string) {
      this.reset()
      this.loading = true
      try {
        const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`)
        if (!response.ok) throw new Error('运行记录不存在')
        const detail = (await response.json()) as RunDetail
        this.runId = runId
        this.diff = detail.diff
        const completed = detail.events.some((event) => event.type === 'report')
        if (completed) {
          this.setReplaySource(detail.events, true)
          this.runId = runId
          this.diff = detail.diff
          this.report = detail.report
        } else {
          this.connectLive(runId)
          this.diff = detail.diff
        }
      } catch (error: unknown) {
        this.error = error instanceof Error ? error.message : '运行记录加载失败'
        throw error
      } finally {
        this.loading = false
      }
    },
    async loadRuns() {
      const response = await fetch('/api/runs')
      if (response.ok) this.runs = (await response.json()) as RunSummary[]
    },
    loadDemo() {
      this.setReplaySource(demoEvents, true)
      this.runId = 'demo-refresh-token'
      this.diff = demoDiff
    },
    playDemo() {
      this.setReplaySource(demoEvents, false)
      this.runId = 'demo-refresh-token'
      this.diff = demoDiff
      this.playReplay()
    },
    stopReplay() {
      this.pauseReplay()
    },
  },
})
