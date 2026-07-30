<script setup lang="ts">
import { Activity, CheckCircle2, ListTodo, Network, Timer, XCircle } from 'lucide-vue-next'
import { NButton, NButtonGroup } from 'naive-ui'
import { computed, ref } from 'vue'

import type { DispatchEntry, WorkflowNode, WorkflowStatus } from '@/types'

const props = defineProps<{
  nodes: WorkflowNode[]
  log: DispatchEntry[]
  elapsed: number
  active: number
  peak: number
  counts: Record<WorkflowStatus, number>
  selected: WorkflowNode | null
}>()
const emit = defineEmits<{ select: [nodeId: string] }>()

const activeView = ref<'tasks' | 'activity'>('tasks')
const remaining = computed(() => Math.max(0, 600 - props.elapsed))
const errorCount = computed(() => props.counts.failed + props.counts.cancelled)
const statusOrder: Record<WorkflowStatus, number> = {
  running: 0,
  waiting: 1,
  queued: 2,
  failed: 3,
  cancelled: 4,
  completed: 5,
}
const missions = computed(() =>
  props.nodes
    .filter((node) => node.kind === 'agent_task' || node.kind === 'verifier')
    .map((node, index) => ({ node, index }))
    .sort((left, right) => statusOrder[left.node.status] - statusOrder[right.node.status] || left.index - right.index)
    .map(({ node }) => node),
)

const agentNames = {
  coordinator: '协调器',
  defect: '缺陷专家',
  intent: '意图专家',
  verifier: 'Verifier',
} as const
</script>

<template>
  <section class="dispatch-board" aria-labelledby="dispatch-heading">
    <header>
      <div>
        <Network :size="14" />
        <h2 id="dispatch-heading">
          动态调度
        </h2>
      </div>
      <span class="countdown">
        <Timer :size="13" />
        {{ Math.floor(remaining / 60) }}:{{ String(Math.floor(remaining % 60)).padStart(2, '0') }}
      </span>
    </header>

    <div class="summary-strip">
      <div>
        <Activity :size="13" />
        <span>并发</span>
        <strong>{{ active }}<small> / 峰值 {{ peak }}</small></strong>
      </div>
      <div>
        <CheckCircle2 :size="13" />
        <span>完成</span>
        <strong>{{ counts.completed }}</strong>
      </div>
      <div :class="{ danger: errorCount > 0 }">
        <XCircle :size="13" />
        <span>异常</span>
        <strong>{{ errorCount }}</strong>
      </div>
    </div>

    <div v-if="selected" class="selected-task">
      <span>当前选中 · {{ selected.agent ? agentNames[selected.agent] : '工作流' }}</span>
      <strong>{{ selected.label }}</strong>
      <p>{{ selected.detail ?? '暂无更多执行详情。' }}</p>
    </div>

    <div class="dispatch-tabs">
      <NButtonGroup size="small" aria-label="调度栏视图">
        <NButton
          :type="activeView === 'tasks' ? 'primary' : 'default'"
          :aria-pressed="activeView === 'tasks'"
          @click="activeView = 'tasks'"
        >
          <ListTodo :size="12" /> 任务 {{ missions.length }}
        </NButton>
        <NButton
          :type="activeView === 'activity' ? 'primary' : 'default'"
          :aria-pressed="activeView === 'activity'"
          @click="activeView = 'activity'"
        >
          <Activity :size="12" /> 动态 {{ log.length }}
        </NButton>
      </NButtonGroup>
    </div>

    <div v-if="activeView === 'tasks'" class="mission-list scrollbar">
      <p v-if="missions.length === 0" class="empty-copy">
        Coordinator 尚未派发任务。
      </p>
      <button
        v-for="mission in missions"
        :key="mission.id"
        type="button"
        :class="[mission.status, { selected: selected?.id === mission.id }]"
        @click="emit('select', mission.id)"
      >
        <i />
        <span>
          <b>{{ mission.agent ? agentNames[mission.agent] : '任务' }}</b>
          {{ mission.label }}
        </span>
      </button>
    </div>

    <div v-else class="dispatch-log scrollbar">
      <p v-if="log.length === 0" class="empty-copy">
        调度事件将在这里按时间记录。
      </p>
      <article v-for="entry in log.slice(0, 12)" :key="entry.id" :class="entry.tone">
        <i />
        <div><strong>{{ entry.title }}</strong><span>{{ entry.detail }}</span></div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.dispatch-board {
  min-width: 0;
}

.dispatch-board > header {
  align-items: center;
  display: flex;
  height: 3.5rem;
  justify-content: space-between;
  padding: 0 3rem 0 var(--space-3);
}

.dispatch-board > header div,
.countdown,
.summary-strip div,
.dispatch-tabs :deep(.n-button__content) {
  align-items: center;
  display: flex;
}

.dispatch-board > header div {
  gap: var(--space-2);
}

.dispatch-board h2 {
  font-size: 0.72rem;
  margin: 0;
}

.countdown {
  color: var(--color-muted);
  font-family: var(--font-mono);
  font-size: 0.65rem;
  gap: var(--space-1);
}

.summary-strip {
  background: var(--color-surface-raised);
  border-block: 1px solid var(--color-border);
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr;
}

.summary-strip div {
  color: var(--color-muted);
  display: grid;
  gap: var(--space-1);
  grid-template-columns: auto 1fr;
  min-width: 0;
  padding: var(--space-2) var(--space-3);
}

.summary-strip div + div {
  border-left: 1px solid var(--color-border);
}

.summary-strip span {
  font-size: 0.6rem;
}

.summary-strip strong {
  color: var(--color-text);
  font-family: var(--font-mono);
  font-size: 0.88rem;
  font-weight: 500;
  grid-column: 1 / -1;
}

.summary-strip small {
  color: var(--color-subtle);
  font-size: 0.55rem;
  font-weight: 400;
}

.summary-strip .danger,
.summary-strip .danger strong {
  color: var(--color-red);
}

.selected-task {
  border-bottom: 1px solid var(--color-border);
  display: grid;
  gap: var(--space-1);
  padding: var(--space-3);
}

.selected-task > span {
  color: var(--color-cyan);
  font-family: var(--font-mono);
  font-size: 0.59rem;
}

.selected-task strong {
  font-size: 0.72rem;
  font-weight: 600;
}

.selected-task p {
  color: var(--color-muted);
  font-size: 0.65rem;
  line-height: 1.45;
  margin: 0;
}

.dispatch-tabs {
  border-bottom: 1px solid var(--color-border);
  padding: var(--space-2) var(--space-3);
}

.dispatch-tabs :deep(.n-button-group) {
  display: flex;
  width: 100%;
}

.dispatch-tabs :deep(.n-button) {
  flex: 1 1 50%;
  min-width: 0;
}

.dispatch-tabs :deep(.n-button__content) {
  gap: var(--space-1);
  justify-content: center;
}

.mission-list,
.dispatch-log {
  display: grid;
  gap: var(--space-1);
  max-height: 22rem;
  overflow-y: auto;
  padding: var(--space-2) var(--space-3) var(--space-3);
}

.mission-list button {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: var(--radius-sm);
  color: var(--color-muted);
  cursor: pointer;
  display: grid;
  gap: var(--space-2);
  grid-template-columns: auto minmax(0, 1fr);
  padding: var(--space-2);
  text-align: left;
}

.mission-list button:hover,
.mission-list button.selected {
  background: var(--color-surface-raised);
  color: var(--color-text);
}

.mission-list button > i,
.dispatch-log article > i {
  background: var(--color-subtle);
  border-radius: 50%;
  height: 0.42rem;
  width: 0.42rem;
}

.mission-list button.running > i {
  animation: pulse-opacity 1s infinite;
  background: var(--color-cyan);
}

.mission-list button.completed > i {
  background: var(--color-green);
}

.mission-list button.failed > i,
.mission-list button.cancelled > i {
  background: var(--color-red);
}

.mission-list button.completed {
  opacity: 0.65;
}

.mission-list button span {
  display: grid;
  font-size: 0.68rem;
  gap: 0.15rem;
  line-height: 1.35;
  min-width: 0;
}

.mission-list button b {
  color: var(--color-subtle);
  font-family: var(--font-mono);
  font-size: 0.57rem;
  font-weight: 500;
}

.dispatch-log {
  gap: var(--space-2);
}

.dispatch-log article {
  align-items: flex-start;
  display: grid;
  gap: var(--space-2);
  grid-template-columns: auto minmax(0, 1fr);
}

.dispatch-log article > i {
  margin-top: 0.35rem;
}

.dispatch-log article.active > i {
  background: var(--color-cyan);
}

.dispatch-log article.success > i {
  background: var(--color-green);
}

.dispatch-log article.danger > i {
  background: var(--color-red);
}

.dispatch-log strong,
.dispatch-log span {
  display: block;
  font-size: 0.65rem;
  line-height: 1.4;
}

.dispatch-log strong {
  color: var(--color-text);
  font-weight: 500;
}

.dispatch-log span {
  color: var(--color-subtle);
  margin-top: 0.1rem;
}

.empty-copy {
  color: var(--color-subtle);
  font-size: 0.67rem;
  line-height: 1.5;
  margin: var(--space-3) 0;
  text-align: center;
}
</style>
