<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PipelineEvent } from '@/contracts'

const props = defineProps<{ events: PipelineEvent[] }>()

const labels: Record<PipelineEvent['type'], string> = {
  'review.started': '审查启动', 'review.completed': '审查完成', 'review.failed': '审查失败',
  'stage.started': '阶段开始', 'stage.completed': '阶段完成', 'stage.failed': '阶段失败',
  'agent.started': 'Agent 启动', 'agent.tool': '工具调用', 'agent.candidate': '发现候选',
  'agent.completed': 'Agent 完成', 'agent.failed': 'Agent 失败', 'verifier.started': 'Verifier 启动',
  'plan.published': '计划已发布', 'tool.started': '工具开始', 'tool.completed': '工具完成',
  'tool.failed': '工具失败', 'mailbox.message': '协作消息',
  'verifier.accepted': '候选通过', 'verifier.rejected': '候选拒绝', 'verifier.completed': '验证完成',
  'report.generated': '报告已生成',
}

// 严格白名单摘要：不读取 prompt、reasoning 或模型响应字段。
const selectedType = ref<'all' | PipelineEvent['type']>('all')
const eventTypes = computed(() => [...new Set(props.events.map((event) => event.type))])
const visibleEvents = computed(() => props.events
  .filter((event) => selectedType.value === 'all' || event.type === selectedType.value)
  .reverse().map((event) => {
  const data = event.data
  const detail = [data.stage, data.agent, data.role, data.tool_name, data.finding_id, data.verdict, data.status]
    .find((value) => typeof value === 'string')
  return { ...event, label: labels[event.type], detail: detail as string | undefined }
}))
</script>

<template>
  <section class="timeline panel">
    <div class="section-heading compact"><div><span class="eyebrow">公开事件流</span><h2>事件时间线</h2></div><b>{{ visibleEvents.length }}</b></div>
    <label class="timeline-filter">事件类型
      <select v-model="selectedType"><option value="all">全部事件</option><option v-for="type in eventTypes" :key="type" :value="type">{{ labels[type] }}</option></select>
    </label>
    <div class="timeline-list">
      <article v-for="event in visibleEvents" :key="event.id" :class="event.type.replace('.', '-')">
        <span class="timeline-dot" />
        <div><strong>{{ event.label }}</strong><small v-if="event.detail">{{ event.detail }}</small></div>
        <time>{{ new Date(event.timestamp).toLocaleTimeString('zh-CN', { hour12: false }) }}</time>
      </article>
      <p v-if="!visibleEvents.length" class="empty-state">当前筛选下没有公开事件。</p>
    </div>
  </section>
</template>
