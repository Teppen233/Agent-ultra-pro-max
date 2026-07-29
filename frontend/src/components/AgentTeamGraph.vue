<script setup lang="ts">
import type { AgentRole, AgentState } from '@/contracts'
import AgentCard from './AgentCard.vue'

defineProps<{ agents: Record<AgentRole, AgentState> }>()
</script>

<template>
  <section class="team-graph panel">
    <div class="section-heading">
      <div><span class="eyebrow">LIVE AGENT TEAM</span><h2>并行审查协作拓扑</h2></div>
      <span class="live-pill"><i /> Agent Mailbox 在线</span>
    </div>
    <div class="team-grid">
      <div class="lead-node"><span>TL</span><strong>Team Lead</strong><small>风险路由与预算编排</small></div>
      <div class="graph-line line-left" /><div class="graph-line line-right" />
      <AgentCard :agent="agents.defect" accent="cyan" />
      <AgentCard :agent="agents.intent" accent="violet" />
      <div class="merge-line" />
      <div class="blackboard-node"><span>Evidence Blackboard</span><small>结构化事实 · 证据 · 候选</small></div>
      <div class="verify-line" />
      <AgentCard class="verifier-card" :agent="agents.verifier" accent="amber" />
    </div>
  </section>
</template>
