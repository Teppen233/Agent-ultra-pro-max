<script lang="ts">
import type { AgentInstanceState } from '@/contracts'

type AgentWorkInput = Pick<
  AgentInstanceState,
  'status' | 'candidateCount' | 'mailboxCount' | 'toolCount' | 'files'
>

export const presentAgentWork = (agent: AgentWorkInput) => {
  const visibleFiles = agent.files.slice(0, 2).join('、')
  const fileSummary = agent.files.length
    ? `${agent.files.length} 个文件 · ${visibleFiles}${agent.files.length > 2 ? ' 等' : ''}`
    : '负责范围待分配'
  let currentAction = '正在读取上下文包'
  if (agent.status === 'waiting') currentAction = '等待并发槽位'
  else if (agent.status === 'failed') currentAction = '执行未完成，等待汇总'
  else if (agent.status === 'degraded') currentAction = '已降级，等待汇总'
  else if (agent.candidateCount > 0) currentAction = `已提交 ${agent.candidateCount} 个候选，等待 Verifier`
  else if (agent.status === 'completed') currentAction = '初审完成，暂无候选'
  else if (agent.mailboxCount > 0) currentAction = '正在处理协作补证'
  else if (agent.toolCount > 0) currentAction = '正在分析代码差异'

  return {
    fileSummary,
    inputSource: 'PR Diff + 上下文包',
    currentAction,
    toolSummary: agent.toolCount ? `主动工具 ${agent.toolCount} 次` : '未主动调用',
    collaborationSummary: agent.mailboxCount ? `协作消息 ${agent.mailboxCount} 条` : '暂无协作消息',
    candidateSummary: agent.candidateCount ? `已提交 ${agent.candidateCount} 个候选` : '暂无候选',
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
}>()

const groups = computed(() => groupAgentInstances(Object.values(props.instances)))
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
            </dl>
            <div class="instance-facts">
              <span>{{ presentAgentWork(agent).toolSummary }}</span>
              <span>{{ presentAgentWork(agent).collaborationSummary }}</span>
              <span>{{ presentAgentWork(agent).candidateSummary }}</span>
            </div>
            <small class="tool-scope-note">仅统计主动工具 · 系统工具见操作流水线</small>
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
