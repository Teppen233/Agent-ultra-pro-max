<script setup lang="ts">
import { computed } from 'vue'

import type { AgentInstanceState, AgentStatus } from '@/contracts'
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
            <p>{{ agent.files.join('、') || '未提供负责文件' }}</p>
            <footer>
              <span><b>{{ agent.toolCount }}</b> 工具</span>
              <span><b>{{ agent.mailboxCount }}</b> 协作</span>
              <span><b>{{ agent.candidateCount }}</b> 候选</span>
            </footer>
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
