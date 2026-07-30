<script lang="ts">
/** 全局任务条显示所需的最小公开状态。 */
export interface ActiveRunInput {
  runId: string
  repository: string
  stage: string
  elapsedSeconds: number
  candidateCount: number
  connection: 'idle' | 'connecting' | 'live' | 'reconnecting' | 'closed' | 'error'
  status: 'idle' | 'running' | 'completed' | 'partial' | 'failed'
}

const stageLabels: Record<string, string> = {
  loading_pr: '加载 PR',
  building_context: '构建上下文',
  planning: '制定计划',
  team_review: '专家并行审查',
  reporting: '生成报告',
  completed: '审查完成',
  failed: '审查失败',
}

const connectionLabels: Record<ActiveRunInput['connection'], string> = {
  idle: '等待连接',
  connecting: '正在连接',
  live: '实时连接正常',
  reconnecting: '正在自动重连',
  closed: '审查已完成',
  error: '连接异常',
}

/** 将全局运行状态归约为任务条直接消费的中文展示模型。 */
export const presentActiveRun = (input: ActiveRunInput) => {
  const terminal = ['completed', 'partial', 'failed'].includes(input.status)
  return {
    repository: input.repository || input.runId,
    stage: stageLabels[input.stage] ?? input.stage,
    elapsed: `已用 ${Math.max(0, Math.round(input.elapsedSeconds))} 秒`,
    candidates: `${input.candidateCount} 个候选`,
    connection: terminal
      ? input.status === 'failed' ? '审查已失败' : input.status === 'partial' ? '审查部分完成' : '审查已完成'
      : connectionLabels[input.connection],
    persistenceNotice: '切换页面不会停止服务端审查。',
    actions: terminal
      ? [
          { label: '查看过程', to: `/review/${input.runId}` },
          { label: '查看报告', to: `/result/${input.runId}` },
        ]
      : [{ label: '进入审查过程', to: `/review/${input.runId}` }],
  }
}
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { useReviewStore } from '@/stores/review'
import { useRunsStore } from '@/stores/runs'

const runs = useRunsStore()
const review = useReviewStore()
const now = ref(Date.now())
let timer: number | undefined

const runId = computed(() => runs.activeRunId ?? runs.lastRunId)
const elapsedSeconds = computed(() => review.startedAt
  ? Math.max(0, (Date.parse(review.completedAt || new Date(now.value).toISOString()) - Date.parse(review.startedAt)) / 1000)
  : 0)
const view = computed(() => runId.value ? presentActiveRun({
  runId: runId.value,
  repository: review.repository,
  stage: review.stage,
  elapsedSeconds: elapsedSeconds.value,
  candidateCount: review.candidates.length,
  connection: runs.connection,
  status: review.status,
}) : undefined)

onMounted(() => {
  timer = window.setInterval(() => { now.value = Date.now() }, 1000)
})

onBeforeUnmount(() => {
  if (timer !== undefined) window.clearInterval(timer)
})
</script>

<template>
  <aside v-if="view" class="active-run-bar" role="status" aria-live="polite">
    <div class="active-run-summary">
      <span class="active-run-dot" :class="runs.connection" />
      <div><strong>{{ view.repository }}</strong><small>{{ view.stage }} · {{ view.elapsed }} · {{ view.candidates }}</small></div>
    </div>
    <p>{{ view.connection }} · {{ view.persistenceNotice }}</p>
    <div class="active-run-actions">
      <RouterLink v-for="action in view.actions" :key="action.to" :to="action.to">{{ action.label }}</RouterLink>
    </div>
  </aside>
</template>

<style scoped>
.active-run-bar { display: flex; align-items: center; gap: 16px; padding: 9px 4vw; border-bottom: 1px solid rgba(39, 215, 208, .23); background: rgba(8, 31, 44, .92); color: #b6ccdc; font-size: 10px; }
.active-run-summary { display: flex; min-width: 0; align-items: center; gap: 9px; }
.active-run-summary div { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.active-run-summary strong { overflow: hidden; color: #e7f6ff; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.active-run-summary small { color: #7896a9; font-size: 8px; }
.active-run-dot { width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; background: #27d7d0; box-shadow: 0 0 8px #27d7d0; }
.active-run-dot.reconnecting { background: #ffb84d; box-shadow: 0 0 8px #ffb84d; }.active-run-dot.error { background: #ff6578; box-shadow: 0 0 8px #ff6578; }.active-run-dot.closed { background: #46d991; box-shadow: 0 0 8px #46d991; }
.active-run-bar > p { margin: 0; flex: 1; color: #7896a9; font-size: 8px; }
.active-run-actions { display: flex; gap: 8px; }.active-run-actions a { padding: 5px 8px; border: 1px solid rgba(39, 215, 208, .32); border-radius: 4px; color: #88dfdb; font-size: 9px; }.active-run-actions a:hover { background: rgba(39, 215, 208, .12); }
@media (max-width: 760px) { .active-run-bar { align-items: flex-start; flex-wrap: wrap; padding: 8px 3vw; }.active-run-bar > p { flex-basis: 100%; order: 3; }.active-run-actions { margin-left: auto; } }
</style>
