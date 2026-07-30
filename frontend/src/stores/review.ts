import { createPinia, defineStore, getActivePinia, setActivePinia } from 'pinia'
import type { Pinia } from 'pinia'

import type {
  AgentInstanceState,
  AgentRole,
  AgentState,
  CandidateRecord,
  Finding,
  OperationCategory,
  OperationRecord,
  PipelineEvent,
  ReviewResult,
  ReviewStatus,
  StageState,
} from '@/contracts'

const stageLabels: Record<string, string> = {
  loading_pr: '加载 PR',
  building_context: '构建上下文',
  planning: '制定计划',
  team_review: '专家并行审查',
  reporting: '生成报告',
}

const initialStages = (): StageState[] => [
  ['loading_pr', '加载 PR'],
  ['building_context', '构建上下文'],
  ['planning', '制定计划'],
  ['team_review', '专家审查'],
  ['reporting', '生成报告'],
].map(([id, label]) => ({ id: id!, label: label!, status: 'waiting' }))

const initialAgents = (): Record<AgentRole, AgentState> => ({
  defect: { role: 'defect', label: '缺陷专家', status: 'waiting', tools: [], candidateCount: 0 },
  intent: { role: 'intent', label: '意图专家', status: 'waiting', tools: [], candidateCount: 0 },
  verifier: { role: 'verifier', label: '独立验证者', status: 'waiting', tools: [], candidateCount: 0 },
})

const asString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.length > 0 ? value : undefined

const asNumber = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined

const asStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []

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

const toolActions: Record<string, string> = {
  'github.load_pr': '拉取 GitHub PR',
  'git.load_diff': '读取 Git 差异',
  'diff.parse': '解析代码差异',
  'context.read_docs': '读取项目文档',
  'context.read_file': '读取相关代码',
  'context.find_tests': '查找相关测试',
  'context.search_symbol': '搜索符号定义',
  'static.semgrep': '执行静态扫描',
  'report.persist': '生成审查报告',
}

const mailboxActions: Record<string, string> = {
  candidate_finding: '发布候选问题',
  evidence_request: '请求补充证据',
  evidence_response: '返回补证结果',
  verifier_final: '发布最终裁决',
  agent_review_completed: '完成专家审查',
}

export const classifyOperationEvent = (event: PipelineEvent): OperationCategory | undefined => {
  if (event.type === 'plan.published') return 'plan'
  if (event.type.startsWith('tool.')) return 'tool'
  if (event.type === 'mailbox.message') return 'mailbox'
  if (event.type === 'agent.candidate') return 'candidate'
  if (event.type === 'verifier.accepted' || event.type === 'verifier.rejected') return 'verdict'
  return undefined
}

export const toOperationRecord = (event: PipelineEvent): OperationRecord | undefined => {
  const category = classifyOperationEvent(event)
  if (!category) return undefined
  const data = event.data
  if (category === 'plan') return {
    id: event.id, category, eventType: event.type, timestamp: event.timestamp,
    actor: 'TeamLead', action: '发布审查计划', target: asStringArray(data.context_ids).join('、'),
    status: 'published', summary: asString(data.summary) ?? '已完成风险路由与上下文分片。',
  }
  if (category === 'tool') {
    const toolName = asString(data.tool_name) ?? 'unknown.tool'
    const summary = asString(data.summary)
    // 兼容旧版本把“能力已降级”错误发布为 tool.failed 的历史回放。
    const legacyDegraded = event.type === 'tool.failed' && summary?.includes('已降级')
    const status = event.type === 'tool.started' ? 'started' : event.type === 'tool.degraded' || legacyDegraded ? 'degraded' : event.type === 'tool.failed' ? 'failed' : 'completed'
    return {
      id: event.id, category, eventType: event.type, timestamp: event.timestamp,
      actor: asString(data.actor) ?? '系统', actorType: asString(data.actor_type) as 'system' | 'agent' | undefined,
      action: toolActions[toolName] ?? `执行 ${toolName}`, target: asString(data.target) ?? '', status,
      summary: summary ?? (status === 'started' ? '操作已开始。' : status === 'degraded' ? '能力已降级。' : status === 'failed' ? '操作未完成。' : '操作已完成。'),
      durationMs: asNumber(data.duration_ms), resultCount: asNumber(data.result_count),
      contextId: asString(data.context_id), agentId: asString(data.agent_id),
    }
  }
  if (category === 'mailbox') {
    const kind = asString(data.kind) ?? ''
    return {
      id: event.id, category, eventType: event.type, timestamp: event.timestamp,
      actor: asString(data.sender) ?? 'Agent', action: mailboxActions[kind] ?? '发送协作消息',
      target: asString(data.recipient) ?? '', status: 'completed', summary: asString(data.summary) ?? '协作消息已送达。',
    }
  }
  if (category === 'candidate') return {
    id: event.id, category, eventType: event.type, timestamp: event.timestamp,
    actor: asString(data.agent) ?? '专家', action: '提交候选问题', target: asString(data.file) ?? '',
    status: 'pending', summary: `候选 ${asString(data.finding_id) ?? '未知'} 已进入验证队列。`, agentId: asString(data.agent),
  }
  const accepted = event.type === 'verifier.accepted'
  return {
    id: event.id, category, eventType: event.type, timestamp: event.timestamp,
    actor: 'Verifier', action: accepted ? '接受候选问题' : '拒绝候选问题',
    target: asString(data.finding_id) ?? '', status: accepted ? 'accepted' : 'rejected',
    summary: asString(data.reason) ?? asString(data.verdict) ?? (accepted ? '证据充分，候选成立。' : '证据不足，候选不成立。'),
  }
}

export const groupAgentInstances = <T extends Pick<AgentInstanceState, 'id' | 'role' | 'contextId'>>(instances: T[]) => {
  const groups = new Map<string, T[]>()
  for (const instance of instances) {
    const agents = groups.get(instance.contextId) ?? []
    agents.push(instance)
    groups.set(instance.contextId, agents)
  }
  return [...groups].map(([contextId, agents]) => ({ contextId, agents }))
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
    agentInstances: {} as Record<string, AgentInstanceState>,
    operations: [] as OperationRecord[],
    planSummary: '' as string,
    planBudgetSeconds: 0,
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
    resultHydrated: false,
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
      const operation = toOperationRecord(event)
      if (operation) this.operations.push(operation)

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
          const agentId = asString(data.agent) ?? role
          if (agentId && role) {
            const instance = this.ensureAgentInstance(agentId, role, data, event.timestamp)
            instance.status = 'running'
            instance.lastAction = '正在分析上下文包'
          }
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
          const agentId = asString(data.agent)
          const finding = findingFromEvent(data)
          if (!this.candidates.some((item) => item.finding.id === finding.id)) {
            this.candidates.push({ finding, agent: role, verdict: 'pending' })
            this.agents[role].candidateCount += 1
            if (agentId) {
              const instance = this.ensureAgentInstance(agentId, role, data, event.timestamp)
              instance.candidateCount += 1
              instance.lastAction = `已提交 ${instance.candidateCount} 个候选，等待 Verifier`
            }
          }
          break
        }
        case 'agent.completed':
        case 'agent.failed': {
          const role = resolveRole(data)
          if (role) {
            this.agents[role].status = event.type === 'agent.completed' ? 'completed' : 'failed'
            this.agents[role].warning = asString(data.warning)
            const agentId = asString(data.agent) ?? role
            const instance = this.ensureAgentInstance(agentId, role, data, event.timestamp)
            instance.status = event.type === 'agent.completed' ? 'completed' : 'failed'
            instance.completedAt = event.timestamp
            instance.warning = asString(data.warning)
            if (Array.isArray(data.completed_checks)) instance.completedChecks = asStringArray(data.completed_checks)
            if (Array.isArray(data.pending_checks)) instance.pendingChecks = asStringArray(data.pending_checks)
            instance.lastAction = event.type === 'agent.failed'
              ? (instance.warning ?? '执行未完成，等待汇总')
              : instance.candidateCount > 0
                ? `已完成上下文审查，提交 ${instance.candidateCount} 个候选等待验证`
                : '已完成上下文审查，未形成可验证候选'
          }
          break
        }
        case 'plan.published':
          this.planSummary = asString(data.summary) ?? ''
          this.planBudgetSeconds = asNumber(data.budget_seconds) ?? 0
          break
        case 'tool.started':
        case 'tool.completed':
        case 'tool.degraded':
        case 'tool.failed': {
          const agentId = asString(data.agent_id)
          const role = resolveRole(data, agentId?.startsWith('intent') ? 'intent' : agentId?.startsWith('verifier') ? 'verifier' : agentId ? 'defect' : undefined)
          if (agentId && role) {
            const instance = this.ensureAgentInstance(agentId, role, data, event.timestamp)
            const tool = asString(data.tool_name)
            if (event.type === 'tool.started') {
              instance.toolCount += 1
              if (tool && !instance.tools.includes(tool)) instance.tools.push(tool)
              instance.lastAction = `正在${toolActions[tool ?? ''] ?? `执行 ${tool ?? '工具'}`}`
            }
          }
          break
        }
        case 'mailbox.message': {
          const kind = asString(data.kind)
          if (kind === 'agent_review_completed') {
            const sender = asString(data.sender)
            if (sender && this.agentInstances[sender]) {
              this.agentInstances[sender].lastAction = '已完成初审，等待协作窗口收敛'
            }
            break
          }
          if (kind !== 'evidence_request' && kind !== 'evidence_response') break
          const participants = new Set([asString(data.sender), asString(data.recipient)])
          for (const agentId of participants) {
            if (!agentId || agentId === '*' || !this.agentInstances[agentId]) continue
            this.agentInstances[agentId].mailboxCount += 1
            this.agentInstances[agentId].lastAction = kind === 'evidence_request'
              ? '正在处理补充证据请求'
              : '已返回补充证据结果'
          }
          break
        }
        case 'verifier.started':
          this.agents.verifier.status = 'running'
          break
        case 'verifier.accepted':
        case 'verifier.rejected':
          this.applyVerdict(event.type === 'verifier.accepted', data)
          break
        case 'verifier.completed':
          this.agents.verifier.status = 'completed'
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

    ensureAgentInstance(
      agentId: string,
      role: AgentRole,
      data: Record<string, unknown>,
      timestamp: string,
    ): AgentInstanceState {
      const existing = this.agentInstances[agentId]
      if (existing) {
        const files = asStringArray(data.files)
        if (files.length) existing.files = files
        if (Array.isArray(data.completed_checks)) existing.completedChecks = asStringArray(data.completed_checks)
        if (Array.isArray(data.pending_checks)) existing.pendingChecks = asStringArray(data.pending_checks)
        return existing
      }
      const contextId = asString(data.context_id) ?? (agentId.split(':').slice(1).join(':') || 'global')
      const instance: AgentInstanceState = {
        id: agentId,
        role,
        label: role === 'defect' ? '缺陷专家' : role === 'intent' ? '意图专家' : '独立验证',
        status: 'waiting',
        contextId,
        files: asStringArray(data.files),
        startedAt: timestamp,
        tools: [],
        toolCount: 0,
        mailboxCount: 0,
        candidateCount: 0,
        completedChecks: asStringArray(data.completed_checks),
        pendingChecks: asStringArray(data.pending_checks),
        lastAction: '等待开始分析上下文',
      }
      this.agentInstances[agentId] = instance
      return instance
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
      this.resultHydrated = true
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

/** 为离线 Demo 创建独立状态容器，避免后台真实 SSE 写入演示时间线。 */
export const createIsolatedReviewStore = (applicationPinia: Pinia | undefined = getActivePinia()) => {
  const store = useReviewStore(createPinia())
  if (applicationPinia) setActivePinia(applicationPinia)
  return store
}
