<script setup lang="ts">
import type { AgentRole, AgentState } from '@/contracts'
import AgentCard from './AgentCard.vue'

defineProps<{ agents: Record<AgentRole, AgentState> }>()
</script>

<template>
  <section class="team-graph panel">
    <div class="section-heading">
      <div><span class="eyebrow">实时智能体团队</span><h2>并行审查协作拓扑</h2></div>
      <span class="live-pill"><i /> 智能体信箱在线</span>
    </div>
    <div class="team-grid">
      <div class="lead-node"><span>领</span><strong>团队负责人</strong><small>风险路由与预算编排</small></div>
      <div class="graph-line line-left" /><div class="graph-line line-right" />
      <AgentCard :agent="agents.defect" accent="cyan" />
      <AgentCard :agent="agents.intent" accent="violet" />
      <div class="merge-line" />
      <div class="blackboard-node"><span>证据黑板</span><small>结构化事实 · 证据 · 候选</small></div>
      <div class="verify-line" />
      <AgentCard class="verifier-card" :agent="agents.verifier" accent="amber" />
    </div>
  </section>
</template>
