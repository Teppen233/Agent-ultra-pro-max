<script setup lang="ts">
import { Activity, CheckCircle2, Clock3, ListTodo, Network, Timer, XCircle } from 'lucide-vue-next'
import { computed } from 'vue'

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

const remaining = computed(() => Math.max(0, 600 - props.elapsed))
const missions = computed(() =>
  props.nodes.filter((node) => node.kind === 'agent_task' || node.kind === 'verifier'),
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
      <span class="countdown"><Timer :size="13" /> {{ Math.floor(remaining / 60) }}:{{ String(Math.floor(remaining % 60)).padStart(2, '0') }}</span>
    </header>

    <div class="concurrency-band">
      <div>
        <span>当前并发</span>
        <strong>{{ active }}<small> / 4</small></strong>
      </div>
      <div>
        <span>峰值并发</span>
        <strong>{{ peak }}</strong>
      </div>
      <Activity :size="22" :class="{ active: active > 0 }" />
    </div>

    <div class="task-metrics">
      <span><Clock3 :size="12" /> 等待 <b>{{ counts.queued }}</b></span>
      <span><Activity :size="12" /> 执行 <b>{{ counts.running }}</b></span>
      <span><CheckCircle2 :size="12" /> 完成 <b>{{ counts.completed }}</b></span>
      <span><XCircle :size="12" /> 失败/驳回 <b>{{ counts.failed + counts.cancelled }}</b></span>
    </div>

    <div v-if="selected" class="selected-task">
      <span>当前选中 · {{ selected.agent ? agentNames[selected.agent] : '工作流' }}</span>
      <strong>{{ selected.label }}</strong>
      <p>{{ selected.detail ?? '暂无更多执行详情。' }}</p>
    </div>

    <div class="mission-list">
      <div class="subheading">
        <ListTodo :size="13" /> Coordinator 派发任务
      </div>
      <p v-if="missions.length === 0" class="empty-copy">
        Coordinator 尚未派发任务，任务不会预先固定。
      </p>
      <button
        v-for="mission in missions"
        :key="mission.id"
        type="button"
        :class="[mission.status, { selected: selected?.id === mission.id }]"
        @click="emit('select', mission.id)"
      >
        <i />
        <span><b>{{ mission.agent ? agentNames[mission.agent] : '任务' }}</b>{{ mission.label }}</span>
      </button>
    </div>

    <div class="dispatch-log">
      <div class="subheading">
        <Activity :size="13" /> 调度决策
      </div>
      <p v-if="log.length === 0" class="empty-copy">
        调度事件将按发生顺序记录在这里。
      </p>
      <article v-for="entry in log.slice(0, 6)" :key="entry.id" :class="entry.tone">
        <i />
        <div><strong>{{ entry.title }}</strong><span>{{ entry.detail }}</span></div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.dispatch-board {
  border-bottom: 1px solid var(--color-border);
}

.dispatch-board > header {
  align-items: center;
  display: flex;
  height: 3.8rem;
  justify-content: space-between;
  padding: 0 var(--space-4);
}

.dispatch-board > header div,
.countdown,
.subheading,
.task-metrics span {
  align-items: center;
  display: flex;
}

.dispatch-board > header div,
.subheading {
  gap: var(--space-2);
}

.dispatch-board h2 {
  font-size: 0.75rem;
  margin: 0;
}

.countdown {
  color: var(--color-muted);
  font-family: var(--font-mono);
  font-size: 0.68rem;
  gap: var(--space-1);
}

.concurrency-band {
  align-items: center;
  background: var(--color-surface-raised);
  border-block: 1px solid var(--color-border);
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  padding: var(--space-3) var(--space-4);
}

.concurrency-band div {
  display: grid;
  gap: var(--space-1);
}

.concurrency-band span {
  color: var(--color-subtle);
  font-size: 0.64rem;
}

.concurrency-band strong {
  font-family: var(--font-mono);
  font-size: 1.15rem;
  font-weight: 500;
}

.concurrency-band small {
  color: var(--color-subtle);
  font-size: 0.7rem;
}

.concurrency-band > svg {
  color: var(--color-subtle);
}

.concurrency-band > svg.active {
  animation: pulse-opacity 1.1s ease-in-out infinite;
  color: var(--color-green);
}

.task-metrics {
  display: grid;
  gap: var(--space-2);
  grid-template-columns: 1fr 1fr;
  padding: var(--space-3) var(--space-4);
}

.task-metrics span {
  color: var(--color-muted);
  font-size: 0.65rem;
  gap: var(--space-1);
}

.task-metrics b {
  color: var(--color-text);
  font-family: var(--font-mono);
  margin-left: auto;
}

.selected-task {
  border-block: 1px solid var(--color-border);
  display: grid;
  gap: var(--space-1);
  padding: var(--space-3) var(--space-4);
}

.selected-task > span,
.subheading {
  color: var(--color-cyan);
  font-family: var(--font-mono);
  font-size: 0.62rem;
}

.selected-task strong {
  font-size: 0.75rem;
  font-weight: 600;
}

.selected-task p {
  color: var(--color-muted);
  font-size: 0.68rem;
  line-height: 1.45;
  margin: 0;
}

.mission-list,
.dispatch-log {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
}

.mission-list {
  border-top: 1px solid var(--color-border);
  max-height: 14rem;
  overflow-y: auto;
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

.mission-list button span {
  display: grid;
  font-size: 0.7rem;
  gap: 0.15rem;
  line-height: 1.35;
  min-width: 0;
}

.mission-list button b {
  color: var(--color-subtle);
  font-family: var(--font-mono);
  font-size: 0.59rem;
  font-weight: 500;
}

.dispatch-log {
  border-top: 1px solid var(--color-border);
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

.dispatch-log article div {
  display: grid;
  gap: 0.15rem;
}

.dispatch-log strong {
  font-size: 0.67rem;
  font-weight: 500;
}

.dispatch-log span,
.empty-copy {
  color: var(--color-subtle);
  font-size: 0.62rem;
  line-height: 1.4;
}

.empty-copy {
  margin: var(--space-2) 0;
}
</style>
