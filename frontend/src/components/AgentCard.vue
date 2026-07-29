<script setup lang="ts">
import type { AgentState } from '@/contracts'

defineProps<{ agent: AgentState; accent: 'cyan' | 'violet' | 'amber' }>()

const statusText: Record<AgentState['status'], string> = {
  waiting: '等待中', running: '分析中', completed: '已完成', degraded: '已降级', failed: '失败',
}
</script>

<template>
  <article class="agent-card" :class="[accent, agent.status]">
    <div class="agent-card-head">
      <span class="agent-avatar">
        <svg v-if="agent.role === 'defect'" viewBox="0 0 24 24"><path d="M8 7V4m8 3V4M5 12H2m20 0h-3M7 9h10v8a5 5 0 0 1-10 0V9Zm3 4h.01M14 13h.01" /></svg>
        <svg v-else-if="agent.role === 'intent'" viewBox="0 0 24 24"><path d="M12 3a6 6 0 0 0-4 10.5V18h8v-4.5A6 6 0 0 0 12 3Zm-3 19h6M9 15h6" /></svg>
        <svg v-else viewBox="0 0 24 24"><path d="m4 12 5 5L20 6M12 22a10 10 0 1 1 0-20" /></svg>
      </span>
      <span><small>{{ agent.role.toUpperCase() }}</small><strong>{{ agent.label }}</strong></span>
      <em><i />{{ statusText[agent.status] }}</em>
    </div>
    <p v-if="agent.role === 'defect'">静态缺陷 · 安全 · 资源生命周期</p>
    <p v-else-if="agent.role === 'intent'">业务意图 · 状态机 · 架构边界</p>
    <p v-else>反证优先 · 可达性 · 严重度校准</p>
    <div class="agent-stats">
      <span><b>{{ agent.candidateCount }}</b> 候选</span>
      <span><b>{{ agent.tools.length }}</b> 工具</span>
    </div>
    <div v-if="agent.tools.length" class="tool-chips">
      <span v-for="tool in agent.tools.slice(-3)" :key="tool">{{ tool }}</span>
    </div>
  </article>
</template>
