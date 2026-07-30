<script setup lang="ts">
import { ChevronDown, ChevronRight, FileCode2, Route, Wrench } from 'lucide-vue-next'
import { NProgress, NTag, NTooltip } from 'naive-ui'
import { computed, ref } from 'vue'

import type { Finding } from '@/types'

const props = defineProps<{ finding: Finding; runId: string | null }>()
const emit = defineEmits<{ selectWorkflow: [nodeId: string] }>()
const expanded = ref(false)
const confidence = computed(
  () => props.finding.confidence_adjusted ?? props.finding.confidence,
)
const rejected = computed(() => props.finding.verdict === 'reject')
const verdictLabel = computed(() => {
  if (props.finding.verdict === 'reject') return 'Verifier 已排除'
  if (props.finding.verdict === 'keep' && confidence.value >= 0.45) return '已确认'
  return '待人工复核'
})
const verdictType = computed(() => {
  if (props.finding.verdict === 'reject') return 'default'
  if (props.finding.verdict === 'keep' && confidence.value >= 0.45) return 'success'
  return 'warning'
})

const severityType = computed(() => {
  if (props.finding.severity === 'critical') return 'error'
  if (props.finding.severity === 'high') return 'warning'
  if (props.finding.severity === 'medium') return 'info'
  return 'default'
})

const severityLabels = { critical: '严重', high: '高危', medium: '中危', low: '低危' } as const
const categoryLabels = {
  logic: '逻辑',
  security: '安全',
  memory: '内存',
  architecture: '架构',
  static: '静态检查',
} as const

function toggle() {
  expanded.value = !expanded.value
  emit('selectWorkflow', `finding-${props.finding.id}`)
}
</script>

<template>
  <article v-motion-fade-visible class="finding-card" :class="{ rejected }">
    <button class="finding-summary" type="button" @click="toggle">
      <span class="severity-bar" :data-severity="finding.severity" />
      <span class="finding-main">
        <span class="finding-meta">
          <NTag :type="severityType" size="small" :bordered="false">{{ severityLabels[finding.severity] }}</NTag>
          <NTag :type="verdictType" size="small" :bordered="false">{{ verdictLabel }}</NTag>
          <span>{{ categoryLabels[finding.category] }}</span>
        </span>
        <strong>{{ finding.title }}</strong>
        <span class="location mono"><FileCode2 :size="13" /> {{ finding.file }}:{{ finding.line_start }}</span>
      </span>
      <NTooltip trigger="hover">
        <template #trigger>
          <span class="confidence">
            <NProgress type="circle" :percentage="Math.round(confidence * 100)" :stroke-width="10" :show-indicator="false" />
            <small>{{ Math.round(confidence * 100) }}</small>
          </span>
        </template>
        Verifier 复核后问题仍成立的置信度
      </NTooltip>
      <ChevronDown v-if="expanded" :size="17" />
      <ChevronRight v-else :size="17" />
    </button>
    <div v-if="expanded" class="finding-details">
      <p>{{ finding.reasoning }}</p>
      <div class="detail-block">
        <Route :size="14" /><span><b>触发路径</b>{{ finding.trigger_path }}</span>
      </div>
      <div class="detail-block">
        <Wrench :size="14" /><span><b>修复建议</b>{{ finding.suggestion }}</span>
      </div>
      <p v-if="finding.verdict_reason" class="verdict-note">
        {{ finding.verdict_reason }}
      </p>
      <RouterLink v-if="runId" class="diff-link" :to="`/review/${runId}/diff`">
        查看 Diff
      </RouterLink>
    </div>
  </article>
</template>

<style scoped>
.finding-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.finding-card:hover {
  border-color: var(--color-border-strong);
}

.finding-card.rejected {
  border-style: dashed;
  opacity: 0.78;
}

.finding-summary {
  align-items: center;
  background: transparent;
  border: 0;
  color: var(--color-text);
  cursor: pointer;
  display: grid;
  gap: var(--space-3);
  grid-template-columns: 0.2rem minmax(0, 1fr) 2.15rem 1rem;
  min-height: 6.2rem;
  padding: 0 var(--space-3) 0 0;
  text-align: left;
  width: 100%;
}

.finding-summary:hover {
  background: var(--color-surface-raised);
}

.severity-bar {
  align-self: stretch;
  background: var(--color-muted);
}

.severity-bar[data-severity='critical'] {
  background: var(--color-red);
}

.severity-bar[data-severity='high'] {
  background: var(--color-amber);
}

.severity-bar[data-severity='medium'] {
  background: var(--color-blue);
}

.severity-bar[data-severity='low'] {
  background: var(--color-green);
}

.finding-main {
  min-width: 0;
}

.finding-main strong {
  display: -webkit-box;
  font-size: 0.8rem;
  line-height: 1.35;
  margin: var(--space-1) 0 var(--space-2);
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.finding-meta,
.location {
  align-items: center;
  color: var(--color-muted);
  display: flex;
  font-size: 0.68rem;
  gap: var(--space-2);
}

.location {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.confidence {
  display: grid;
  height: 2.15rem;
  place-items: center;
  position: relative;
  width: 2.15rem;
}

.confidence :deep(.n-progress) {
  grid-area: 1 / 1;
  height: 2.15rem;
  width: 2.15rem;
}

.confidence small {
  font-family: var(--font-mono);
  font-size: 0.61rem;
  grid-area: 1 / 1;
}

.finding-details {
  border-top: 1px solid var(--color-border);
  color: var(--color-muted);
  font-size: 0.78rem;
  line-height: 1.6;
  padding: var(--space-4);
}

.finding-details > p:first-child {
  color: var(--color-text);
  margin-top: 0;
}

.detail-block {
  align-items: flex-start;
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.detail-block b {
  color: var(--color-text);
  display: block;
  font-size: 0.7rem;
  margin-bottom: var(--space-1);
  text-transform: uppercase;
}

.verdict-note {
  border-left: 2px solid var(--color-violet);
  padding-left: var(--space-2);
}

.diff-link {
  color: var(--color-cyan);
  display: inline-block;
  margin-top: var(--space-3);
  text-decoration: none;
}
</style>
