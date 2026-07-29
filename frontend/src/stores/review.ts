import { defineStore } from 'pinia'

import type {
  AgentRole,
  AgentState,
  CandidateRecord,
  Finding,
  PipelineEvent,
  ReviewResult,
  ReviewStatus,
  StageState,
} from '@/contracts'

const TERMINAL_EVENTS = new Set<PipelineEvent['type']>(['review.completed', 'review.failed'])

const stageLabels: Record<string, string> = {
  loading_pr: '加载 PR',
  parsing_diff: '解析 Diff',
  building_context: '构建上下文',
  planning: '制定计划',
  team_review: '专家并行审查',
  reviewing: '专家并行审查',
  deduplicating: '候选去重',
  verifying: '独立验证',
  reporting: '生成报告',
  generating_report: '生成报告',
}

const initialStages = (): StageState[] => [
  ['loading_pr', '加载 PR'],
  ['parsing_diff', '解析 Diff'],
  ['building_context', '构建上下文'],
  ['team_review', '专家审查'],
  ['verifying', '独立验证'],
  ['reporting', '生成报告'],
].map(([id, label]) => ({ id: id!, label: label!, status: 'waiting' }))

const initialAgents = (): Record<AgentRole, AgentState> => ({
  defect: { role: 'defect', label: 'Defect Agent', status: 'waiting', tools: [], candidateCount: 0 },
  intent: { role: 'intent', label: 'Intent Agent', status: 'waiting', tools: [], candidateCount: 0 },
  verifier: { role: 'verifier', label: 'Verifier Agent', status: 'waiting', tools: [], candidateCount: 0 },
})

const asString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.length > 0 ? value : undefined

const asNumber = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined

const resolveRole = (data: Record<string, unknown>, fallback?: AgentRole): AgentRole | undefined => {
  const raw = asString(data.role) ?? asString(data.agent) ?? fallback
  if (raw?.startsWith('defect')) return 'defect'
  if (raw?.startsWith('intent')) return 'intent'
  if (raw?.startsWith('verifier')) return 'verifier'
  return fallback
}

const findingFromEvent = (data: Record<string, unknown>): Finding => {
  const nested = data.finding
  if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
    return nested as Finding
  }
  return {
    id: asString(data.finding_id) ?? 'unknown-finding',
    file: asString(data.file),
    line: asNumber(data.line),
    severity: asString(data.severity) as Finding['severity'],
    title: asString(data.title),
  }
}

/**
 * 将实时 SSE 与历史 Replay 归约到同一份展示状态。
 * 归约器只消费公开字段，并按 sequence 保证幂等与终态封口。
 */
export const useReviewStore = defineStore('review', {
  state: () => ({
    runId: '' as string,
    status: 'idle' as ReviewStatus,
    stage: 'idle' as string,
    stages: initialStages(),
    agents: initialAgents(),
    candidates: [] as CandidateRecord[],
    findings: [] as Finding[],
    events: [] as PipelineEvent[],
    lastSequence: 0,
    repository: '' as string,
    title: '' as string,
    reportReady: false,
    startedAt: '' as string,
    completedAt: '' as string,
    error: '' as string,
    baseSha: '' as string,
    headSha: '' as string,
    elapsedSeconds: 0,
    rejectedCount: 0,
    coverage: [] as string[],
    warnings: [] as string[],
  }),
  actions: {
    applyEvent(event: PipelineEvent): void {
      if (event.sequence <= this.lastSequence || ['completed', 'partial', 'failed'].includes(this.status)) {
        return
      }

      this.runId = event.run_id
      this.lastSequence = event.sequence
      this.events.push(event)
      const data = event.data

      switch (event.type) {
        case 'review.started':
          this.status = 'running'
          this.stage = 'loading_pr'
          this.startedAt = event.timestamp
          this.repository = asString(data.repository) ?? this.repository
          this.title = asString(data.title) ?? this.title
          break
        case 'stage.started': {
          const stage = asString(data.stage)
          if (stage) this.setStageStatus(stage, 'running')
          break
        }
        case 'stage.completed': {
          const stage = asString(data.stage)
          if (stage) this.setStageStatus(stage, 'completed')
          break
        }
        case 'stage.failed': {
          const stage = asString(data.stage)
          if (stage) this.setStageStatus(stage, 'failed')
          break
        }
        case 'agent.started': {
          const role = resolveRole(data)
          if (role) this.agents[role].status = 'running'
          break
        }
        case 'agent.tool': {
          const role = resolveRole(data)
          const tool = asString(data.tool_name)
          if (role && tool && !this.agents[role].tools.includes(tool)) this.agents[role].tools.push(tool)
          break
        }
        case 'agent.candidate': {
          const role = resolveRole(data, 'defect') ?? 'defect'
          const finding = findingFromEvent(data)
          if (!this.candidates.some((item) => item.finding.id === finding.id)) {
            this.candidates.push({ finding, agent: role, verdict: 'pending' })
            this.agents[role].candidateCount += 1
          }
          break
        }
        case 'agent.completed':
        case 'agent.failed': {
          const role = resolveRole(data)
          if (role) {
            this.agents[role].status = event.type === 'agent.completed' ? 'completed' : 'failed'
            this.agents[role].warning = asString(data.warning)
          }
          break
        }
        case 'verifier.started':
          this.agents.verifier.status = 'running'
          this.setStageStatus('verifying', 'running')
          break
        case 'verifier.accepted':
        case 'verifier.rejected':
          this.applyVerdict(event.type === 'verifier.accepted', data)
          break
        case 'verifier.completed':
          this.agents.verifier.status = 'completed'
          this.setStageStatus('verifying', 'completed')
          break
        case 'report.generated':
          this.reportReady = true
          this.setStageStatus('reporting', 'completed')
          break
        case 'review.completed':
          this.status = (asString(data.status) as ReviewStatus | undefined) ?? 'completed'
          this.stage = 'completed'
          this.completedAt = event.timestamp
          break
        case 'review.failed':
          this.status = 'failed'
          this.stage = 'failed'
          this.completedAt = event.timestamp
          this.error = asString(data.message) ?? '审查流程未能完成。'
          break
      }
    },

    setStageStatus(stage: string, status: StageState['status']): void {
      this.stage = stage
      let target = this.stages.find((item) => item.id === stage)
      if (!target) {
        target = { id: stage, label: stageLabels[stage] ?? stage, status: 'waiting' }
        this.stages.push(target)
      }
      target.status = status
    },

    applyVerdict(accepted: boolean, data: Record<string, unknown>): void {
      const findingId = asString(data.finding_id)
      if (!findingId) return
      const candidate = this.candidates.find((item) => item.finding.id === findingId)
      if (!candidate) return
      candidate.verdict = accepted ? 'accepted' : 'rejected'
      candidate.verdictCode = asString(data.verdict)
      candidate.verdictReason = asString(data.reason)
      candidate.verdictConfidence = asNumber(data.confidence)
      if (accepted && !this.findings.some((item) => item.id === findingId)) {
        this.findings.push(candidate.finding)
      }
    },

    /** 用最终 JSON 报告补齐实时事件只提供的 Finding 摘要。 */
    hydrateResult(result: ReviewResult): void {
      this.runId = result.run_id
      this.status = result.status
      this.repository = result.repository
      this.baseSha = result.base_sha
      this.headSha = result.head_sha
      this.findings = result.findings
      this.rejectedCount = result.rejected_count
      this.coverage = result.coverage
      this.warnings = result.warnings
      this.startedAt = result.started_at
      this.completedAt = result.completed_at
      this.elapsedSeconds = result.elapsed_seconds
      for (const finding of result.findings) {
        const candidate = this.candidates.find((item) => item.finding.id === finding.id)
        if (candidate) candidate.finding = finding
      }
    },

    /** 清空上一运行，保证演示 Replay 可重复执行。 */
    reset(): void {
      this.$reset()
    },
  },
})
