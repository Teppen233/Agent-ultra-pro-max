<script lang="ts">
import type { AgentInstanceState, OperationRecord } from '@/contracts'

type AgentWorkInput = Pick<
  AgentInstanceState,
  'status' | 'candidateCount' | 'mailboxCount' | 'toolCount' | 'files' |
  'role' | 'completedChecks' | 'pendingChecks' | 'lastAction'
>

const plannedChecks: Record<AgentInstanceState['role'], string[]> = {
  defect: ['静态破坏', '安全输入', '资源生命周期'],
  intent: ['意图与行为偏差', '边界条件', '架构契约'],
  verifier: ['证据完整性', '反证检查', '最终裁决'],
}

export const presentAgentWork = (agent: AgentWorkInput) => {
  const visibleFiles = agent.files.slice(0, 2).join('、')
  const fileSummary = agent.files.length
    ? `${agent.files.length} 个文件 · ${visibleFiles}${agent.files.length > 2 ? ' 等' : ''}`
    : '负责范围待分配'
  let currentAction = agent.lastAction || '正在读取上下文包'
  if (agent.status === 'waiting') currentAction = '等待开始分析上下文'
  else if (agent.status === 'failed') currentAction = '执行未完成，等待汇总'
  else if (agent.status === 'degraded') currentAction = '已降级，等待汇总'
  else if (agent.candidateCount > 0) currentAction = `已提交 ${agent.candidateCount} 个候选，等待 Verifier`
  else if (agent.status === 'completed') currentAction = agent.lastAction || '已完成上下文审查，未形成可验证候选'
  else if (agent.mailboxCount > 0) currentAction = '正在处理协作补证'

  const checkSummary = agent.completedChecks.length
    ? `已完成：${agent.completedChecks.join('、')}`
    : agent.pendingChecks.length
      ? `待检查：${agent.pendingChecks.join('、')}`
      : `计划检查：${plannedChecks[agent.role].join('、')}`

  return {
    fileSummary,
    inputSource: 'PR Diff + 上下文包',
    currentAction,
    checkSummary,
    collaborationSummary: agent.mailboxCount ? `已处理 ${agent.mailboxCount} 条协作消息` : '等待 Verifier 或其他专家消息',
    candidateSummary: agent.candidateCount ? `已提交 ${agent.candidateCount} 个候选等待验证` : '尚未形成候选',
  }
}

type SharedToolOperation = Pick<OperationRecord, 'category' | 'actorType' | 'action' | 'status'>

/** 将运行级系统工具的最终状态去重为卡片上方的共享工具链。 */
export const presentSharedToolchain = (operations: SharedToolOperation[]) => {
  const latest = new Map<string, SharedToolOperation>()
  for (const operation of operations) {
    if (operation.category !== 'tool' || operation.actorType !== 'system' || operation.status === 'started') continue
    latest.set(operation.action, operation)
  }
  const terminal = [...latest.values()]
  const completed = terminal.filter((operation) => operation.status === 'completed').length
  const degraded = terminal.filter((operation) => operation.status === 'degraded').length
  const failed = terminal.filter((operation) => operation.status === 'failed').length
  const counts = [completed ? `${completed} 项完成` : '', degraded ? `${degraded} 项降级` : '', failed ? `${failed} 项失败` : ''].filter(Boolean)
  return {
    summary: counts.length ? `共享工具链：${counts.join(' · ')}` : '共享工具链：等待运行级工具结果',
    items: terminal.map((operation) => `${operation.action}${operation.status === 'degraded' ? '（降级）' : operation.status === 'failed' ? '（失败）' : ''}`),
  }
}
</script>

<script setup lang="ts">
import { computed } from 'vue'

import type { AgentStatus } from '@/contracts'
import { groupAgentInstances } from '@/stores/review'

const props = defineProps<{
  instances: Record<string, AgentInstanceState>
  planSummary: string
  candidateCount: number
  verdictCount: number
  verifierStatus: AgentStatus
  operations: OperationRecord[]
}>()

const groups = computed(() => groupAgentInstances(Object.values(props.instances)))
const sharedToolchain = computed(() => presentSharedToolchain(props.operations))
const statusText: Record<AgentStatus, string> = {
  waiting: '等待中', running: '运行中', completed: '已完成', degraded: '已降级', failed: '失败',
}
</script>

<template>
  <section class="operations-graph panel">
    <div class="section-heading compact">
      <div><span class="eyebrow">真实 Agent 实例</span><h2>并行审查作战图</h2></div>
      <b>{{ Object.keys(instances).length }} 实例</b>
    </div>
    <article class="operations-lead">
      <strong>TeamLead · 审查计划</strong>
      <span>{{ planSummary || '等待计划发布…' }}</span>
    </article>
    <article class="shared-toolchain">
      <strong>{{ sharedToolchain.summary }}</strong>
      <span v-if="sharedToolchain.items.length">{{ sharedToolchain.items.join(' · ') }}</span>
      <span v-else>PR 拉取、Diff 解析和上下文构建会在这里汇总。</span>
    </article>
    <div v-if="groups.length" class="context-groups">
      <section v-for="group in groups" :key="group.contextId" class="context-group">
        <header><strong>{{ group.contextId }}</strong><small>{{ group.agents.length }} 个专家</small></header>
        <div class="instance-grid">
          <article v-for="agent in group.agents" :key="agent.id" class="instance-card" :class="[agent.role, agent.status]">
            <div><strong>{{ agent.label }}</strong><em>{{ statusText[agent.status] }}</em></div>
            <code>{{ agent.id }}</code>
            <div class="instance-action">
              <small>当前动作</small>
              <strong>{{ presentAgentWork(agent).currentAction }}</strong>
            </div>
            <dl class="instance-work-summary">
              <div><dt>负责范围</dt><dd>{{ presentAgentWork(agent).fileSummary }}</dd></div>
              <div><dt>输入来源</dt><dd>{{ presentAgentWork(agent).inputSource }}</dd></div>
              <div><dt>检查进度</dt><dd>{{ presentAgentWork(agent).checkSummary }}</dd></div>
            </dl>
            <div class="instance-facts">
              <span>{{ presentAgentWork(agent).collaborationSummary }}</span>
              <span>{{ presentAgentWork(agent).candidateSummary }}</span>
            </div>
            <small class="tool-scope-note">Agent 消费预构建上下文；运行级工具由上方共享工具链展示。</small>
            <small v-if="agent.warning" class="instance-warning">{{ agent.warning }}</small>
          </article>
        </div>
      </section>
    </div>
    <p v-else class="empty-state">Agent 启动后，会按完整实例 ID 显示在这里。</p>
    <div class="operations-convergence">
      <span>证据黑板 · {{ candidateCount }} 个候选</span>
      <strong>Verifier · {{ statusText[verifierStatus] }}</strong>
      <span>{{ verdictCount }} 个裁决</span>
    </div>
  </section>
</template>
