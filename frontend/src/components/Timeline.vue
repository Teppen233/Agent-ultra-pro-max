<script setup lang="ts">
import { computed } from 'vue'
import type { PipelineEvent } from '@/contracts'

const props = defineProps<{ events: PipelineEvent[] }>()

const labels: Record<PipelineEvent['type'], string> = {
  'review.started': '审查启动', 'review.completed': '审查完成', 'review.failed': '审查失败',
  'stage.started': '阶段开始', 'stage.completed': '阶段完成', 'stage.failed': '阶段失败',
  'agent.started': 'Agent 启动', 'agent.tool': '工具调用', 'agent.candidate': '发现候选',
  'agent.completed': 'Agent 完成', 'agent.failed': 'Agent 失败', 'verifier.started': 'Verifier 启动',
  'verifier.accepted': '候选通过', 'verifier.rejected': '候选拒绝', 'verifier.completed': '验证完成',
  'report.generated': '报告已生成',
}

// 严格白名单摘要：不读取 prompt、reasoning 或模型响应字段。
const visibleEvents = computed(() => props.events.slice(-10).reverse().map((event) => {
  const data = event.data
  const detail = [data.stage, data.agent, data.role, data.tool_name, data.finding_id, data.verdict, data.status]
    .find((value) => typeof value === 'string')
  return { ...event, label: labels[event.type], detail: detail as string | undefined }
}))
</script>

<template>
  <section class="timeline panel">
    <div class="section-heading compact"><div><span class="eyebrow">公开事件流</span><h2>事件时间线</h2></div><b>{{ events.length }}</b></div>
    <div class="timeline-list">
      <article v-for="event in visibleEvents" :key="event.id" :class="event.type.replace('.', '-')">
        <span class="timeline-dot" />
        <div><strong>{{ event.label }}</strong><small v-if="event.detail">{{ event.detail }}</small></div>
        <time>{{ new Date(event.timestamp).toLocaleTimeString('zh-CN', { hour12: false }) }}</time>
      </article>
      <p v-if="!events.length" class="empty-state">事件流连接后，公开进度会显示在这里。</p>
    </div>
  </section>
</template>
