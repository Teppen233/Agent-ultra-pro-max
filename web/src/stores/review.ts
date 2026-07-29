import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PipelineEvent, Finding, ReviewStatus } from '../contracts'

/** 阶段信息 */
export interface StageInfo {
  key: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  startTime?: string
  endTime?: string
}

/** Agent 状态 */
export type AgentStatus = 'idle' | 'running' | 'completed' | 'failed'

/** 工具调用记录 */
export interface ToolCallEntry {
  tool: string
  timestamp: string
  durationMs?: number
}

/** Agent 信息 */
export interface AgentInfo {
  name: string
  key: string
  status: AgentStatus
  tools: ToolCallEntry[]
  candidatesCount: number
  startTime?: string
  endTime?: string
}

/** 候选 Finding 条目 */
export interface CandidateEntry {
  finding: Finding
  verifierStatus: 'pending' | 'accepted' | 'rejected'
  verifierReason?: string
}

/** 预设的 6 个阶段 */
const STAGE_KEYS = ['init', 'analysis', 'defect', 'intent', 'verify', 'report'] as const

const STAGE_NAMES: Record<string, string> = {
  init: '初始化',
  analysis: '并行分析',
  defect: '缺陷检测',
  intent: '意图分析',
  verify: '结果验证',
  report: '报告生成',
}

export const useReviewStore = defineStore('review', () => {
  // ---- 基础状态 ----
  const runId = ref('')
  const status = ref<ReviewStatus>('idle')
  const error = ref<string | null>(null)
  const reviewTitle = ref('')

  // ---- 阶段 ----
  const stages = ref<StageInfo[]>(
    STAGE_KEYS.map((key) => ({
      key,
      name: STAGE_NAMES[key],
      status: 'pending',
    }))
  )

  // ---- Agent ----
  const agents = ref<AgentInfo[]>([
    { name: '缺陷检测 Agent', key: 'defect', status: 'idle', tools: [], candidatesCount: 0 },
    { name: '意图分析 Agent', key: 'intent', status: 'idle', tools: [], candidatesCount: 0 },
    { name: '验证 Agent', key: 'verifier', status: 'idle', tools: [], candidatesCount: 0 },
  ])

  // ---- 候选与最终结果 ----
  const candidates = ref<CandidateEntry[]>([])
  const reportUrl = ref('')

  // ---- 计时 ----
  const startTime = ref<string>('')
  const endTime = ref<string>('')

  // ---- 计算属性 ----
  const stageProgress = computed(() => {
    const total = stages.value.length
    const completed = stages.value.filter(
      (s) => s.status === 'completed' || s.status === 'failed'
    ).length
    const running = stages.value.findIndex((s) => s.status === 'running')
    return { completed, total, percent: Math.round((completed / total) * 100), runningIndex: running }
  })

  const totalDurationMs = computed(() => {
    if (!startTime.value) return 0
    const end = endTime.value ? new Date(endTime.value).getTime() : Date.now()
    return end - new Date(startTime.value).getTime()
  })

  const acceptedFindings = computed(() =>
    candidates.value.filter((c) => c.verifierStatus === 'accepted').map((c) => c.finding)
  )

  const rejectedFindings = computed(() =>
    candidates.value.filter((c) => c.verifierStatus === 'rejected').map((c) => c.finding)
  )

  const pendingFindings = computed(() =>
    candidates.value.filter((c) => c.verifierStatus === 'pending').map((c) => c.finding)
  )

  // ---- 辅助方法 ----
  function getStageIndex(key: string): number {
    return stages.value.findIndex((s) => s.key === key)
  }

  function getAgentIndex(key: string): number {
    return agents.value.findIndex((a) => a.key === key)
  }

  // ---- 核心：applyEvent 归约 ----
  function applyEvent(event: PipelineEvent): void {
    const { type, data, timestamp } = event

    switch (type) {
      case 'review.started': {
        runId.value = event.run_id
        status.value = 'reviewing'
        startTime.value = timestamp
        error.value = null
        reviewTitle.value = (data.pr_title as string) || (data.repo as string) || ''
        // 初始化阶段
        updateStage('init', 'completed', timestamp)
        updateStage('analysis', 'running', timestamp)
        break
      }

      case 'review.completed': {
        status.value = 'completed'
        endTime.value = timestamp
        // 确保所有阶段完成
        stages.value.forEach((s) => {
          if (s.status === 'running') {
            s.status = 'completed'
            s.endTime = timestamp
          }
        })
        agents.value.forEach((a) => {
          if (a.status === 'running') {
            a.status = 'completed'
            a.endTime = timestamp
          }
        })
        break
      }

      case 'review.failed': {
        status.value = 'failed'
        endTime.value = timestamp
        error.value = (data.reason as string) || '审查失败'
        break
      }

      case 'stage.started': {
        const stageKey = data.stage as string
        const idx = getStageIndex(stageKey)
        if (idx !== -1) {
          stages.value[idx].status = 'running'
          stages.value[idx].startTime = timestamp
        }
        break
      }

      case 'stage.completed': {
        const stageKey = data.stage as string
        updateStage(stageKey, 'completed', timestamp)
        // 自动推进到下一阶段
        const idx = getStageIndex(stageKey)
        if (idx !== -1 && idx + 1 < stages.value.length) {
          const next = stages.value[idx + 1]
          if (next.status === 'pending') {
            next.status = 'running'
            next.startTime = timestamp
          }
        }
        break
      }

      case 'stage.failed': {
        const stageKey = data.stage as string
        updateStage(stageKey, 'failed', timestamp)
        status.value = 'failed'
        error.value = (data.reason as string) || `阶段 "${STAGE_NAMES[stageKey] || stageKey}" 失败`
        break
      }

      case 'agent.started': {
        const agentKey = data.agent as string
        const idx = getAgentIndex(agentKey)
        if (idx !== -1) {
          agents.value[idx].status = 'running'
          agents.value[idx].startTime = timestamp
        }
        break
      }

      case 'agent.tool': {
        const agentKey = data.agent as string
        const idx = getAgentIndex(agentKey)
        if (idx !== -1) {
          agents.value[idx].tools.push({
            tool: (data.tool as string) || 'unknown',
            timestamp,
            durationMs: data.duration_ms as number | undefined,
          })
        }
        break
      }

      case 'agent.candidate': {
        const agentKey = data.agent as string
        const finding = data.finding as Finding
        if (finding) {
          candidates.value.push({
            finding,
            verifierStatus: 'pending',
          })
          const idx = getAgentIndex(agentKey)
          if (idx !== -1) {
            agents.value[idx].candidatesCount++
          }
        }
        break
      }

      case 'agent.completed': {
        const agentKey = data.agent as string
        const idx = getAgentIndex(agentKey)
        if (idx !== -1) {
          agents.value[idx].status = 'completed'
          agents.value[idx].endTime = timestamp
        }
        // 如果两个检测 Agent 都完成了，推进到验证阶段
        checkAndAdvanceToVerify(timestamp)
        break
      }

      case 'agent.failed': {
        const agentKey = data.agent as string
        const idx = getAgentIndex(agentKey)
        if (idx !== -1) {
          agents.value[idx].status = 'failed'
          agents.value[idx].endTime = timestamp
        }
        break
      }

      case 'verifier.started': {
        const idx = getAgentIndex('verifier')
        if (idx !== -1) {
          agents.value[idx].status = 'running'
          agents.value[idx].startTime = timestamp
        }
        status.value = 'verifying'
        updateStage('analysis', 'completed', timestamp)
        updateStage('verify', 'running', timestamp)
        break
      }

      case 'verifier.accepted': {
        const findingId = data.finding_id as string
        const entry = candidates.value.find((c) => c.finding.id === findingId)
        if (entry) {
          entry.verifierStatus = 'accepted'
          entry.verifierReason = data.reason as string | undefined
          // 支持后端直接返回完整 finding
          if (data.finding) {
            entry.finding = data.finding as Finding
          }
        }
        break
      }

      case 'verifier.rejected': {
        const findingId = data.finding_id as string
        const entry = candidates.value.find((c) => c.finding.id === findingId)
        if (entry) {
          entry.verifierStatus = 'rejected'
          entry.verifierReason = data.reason as string | undefined
        }
        break
      }

      case 'verifier.completed': {
        const idx = getAgentIndex('verifier')
        if (idx !== -1) {
          agents.value[idx].status = 'completed'
          agents.value[idx].endTime = timestamp
        }
        updateStage('verify', 'completed', timestamp)
        updateStage('report', 'running', timestamp)
        break
      }

      case 'report.generated': {
        reportUrl.value = (data.url as string) || ''
        updateStage('report', 'completed', timestamp)
        break
      }
    }
  }

  /** 批量应用事件（Replay / 历史加载） */
  function applyEvents(events: PipelineEvent[]): void {
    for (const event of events) {
      applyEvent(event)
    }
  }

  /** 重置状态 */
  function reset(): void {
    runId.value = ''
    status.value = 'idle'
    error.value = null
    reviewTitle.value = ''
    stages.value = STAGE_KEYS.map((key) => ({
      key,
      name: STAGE_NAMES[key],
      status: 'pending',
    }))
    agents.value = [
      { name: '缺陷检测 Agent', key: 'defect', status: 'idle', tools: [], candidatesCount: 0 },
      { name: '意图分析 Agent', key: 'intent', status: 'idle', tools: [], candidatesCount: 0 },
      { name: '验证 Agent', key: 'verifier', status: 'idle', tools: [], candidatesCount: 0 },
    ]
    candidates.value = []
    reportUrl.value = ''
    startTime.value = ''
    endTime.value = ''
  }

  // ---- 内部辅助 ----
  function updateStage(key: string, newStatus: StageInfo['status'], ts: string): void {
    const idx = getStageIndex(key)
    if (idx === -1) return
    stages.value[idx].status = newStatus
    if (newStatus === 'completed' || newStatus === 'failed') {
      stages.value[idx].endTime = ts
    }
  }

  function checkAndAdvanceToVerify(ts: string): void {
    const defectAgent = agents.value.find((a) => a.key === 'defect')
    const intentAgent = agents.value.find((a) => a.key === 'intent')
    const bothDone =
      defectAgent &&
      intentAgent &&
      (defectAgent.status === 'completed' || defectAgent.status === 'failed') &&
      (intentAgent.status === 'completed' || intentAgent.status === 'failed')
    if (bothDone) {
      updateStage('defect', 'completed', ts)
      updateStage('intent', 'completed', ts)
    }
  }

  return {
    // 基础
    runId,
    status,
    error,
    reviewTitle,
    // 阶段
    stages,
    stageProgress,
    // Agent
    agents,
    // 候选
    candidates,
    acceptedFindings,
    rejectedFindings,
    pendingFindings,
    // 报告
    reportUrl,
    // 计时
    startTime,
    endTime,
    totalDurationMs,
    // 方法
    applyEvent,
    applyEvents,
    reset,
  }
})
