<script setup lang="ts">
import { Background, BackgroundVariant } from '@vue-flow/background'
import {
  MarkerType,
  Position,
  VueFlow,
  useVueFlow,
  type Edge,
  type Node,
  type NodeMouseEvent,
} from '@vue-flow/core'
import { Focus, Maximize2, Network, Radio, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { NButton, NButtonGroup, NTooltip } from 'naive-ui'
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'

import type { AgentName, WorkflowEdge, WorkflowKind, WorkflowNode, WorkflowStatus } from '@/types'

import { layoutWorkflowGraph } from './workflowLayout'

const props = defineProps<{
  workflowNodes: WorkflowNode[]
  workflowEdges: WorkflowEdge[]
  selectedNodeId: string | null
}>()
const emit = defineEmits<{ select: [nodeId: string] }>()
const { fitView, zoomIn: zoomGraphIn, zoomOut: zoomGraphOut } = useVueFlow()

const kindLabel: Record<WorkflowKind, string> = {
  input: '输入',
  coordinator: '协调器',
  agent_task: '专家任务',
  tool: '工具证据',
  finding: '候选问题',
  verifier: '独立验证',
  report: '报告',
}

const agentLabel: Record<AgentName, string> = {
  coordinator: 'Coordinator',
  defect: '缺陷专家',
  intent: '意图专家',
  verifier: 'Verifier',
}

const statusLabel: Record<WorkflowStatus, string> = {
  queued: '等待',
  running: '执行中',
  waiting: '待验证',
  completed: '完成',
  failed: '失败',
  cancelled: '驳回',
}

function aggregateToolNodes(sourceNodes: WorkflowNode[], sourceEdges: WorkflowEdge[]) {
  const toolCountByTask = new Map<string, number>()
  for (const tool of sourceNodes.filter((node) => node.kind === 'tool')) {
    const taskId = tool.task_id ?? tool.id
    toolCountByTask.set(taskId, (toolCountByTask.get(taskId) ?? 0) + 1)
  }

  const nodes = sourceNodes.filter((node) => node.kind !== 'tool')
  const nodeIds = new Set(nodes.map((node) => node.id))
  const edges = sourceEdges.filter(
    (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
  )
  return { nodes, edges, toolCounts: toolCountByTask }
}

const displayGraph = computed(() => aggregateToolNodes(props.workflowNodes, props.workflowEdges))
const layoutPositions = computed(() =>
  layoutWorkflowGraph(displayGraph.value.nodes, displayGraph.value.edges),
)
const currentFocusId = ref<string | null>(null)
const focusedBranchIds = shallowRef<Set<string>>(new Set())

const currentFocusLabel = computed(
  () => displayGraph.value.nodes.find((node) => node.id === currentFocusId.value)?.label ?? null,
)

const runningIds = computed(
  () =>
    new Set(
      displayGraph.value.nodes
        .filter((node) => node.status === 'running')
        .map((node) => node.id),
    ),
)

function focusBranch(identifier: string) {
  const visible = new Set(displayGraph.value.nodes.map((node) => node.id))
  const primaryEdges = displayGraph.value.edges.filter(
    (edge) => edge.relation !== 'evidence' && edge.relation !== 'result',
  )
  const branch = new Set([identifier])
  let ancestors = [identifier]
  for (let depth = 0; depth < 3; depth += 1) {
    ancestors = primaryEdges
      .filter((edge) => ancestors.includes(edge.target) && visible.has(edge.source))
      .map((edge) => edge.source)
    ancestors.forEach((id) => branch.add(id))
  }
  let descendants = [identifier]
  for (let depth = 0; depth < 2; depth += 1) {
    descendants = primaryEdges
      .filter((edge) => descendants.includes(edge.source) && visible.has(edge.target))
      .map((edge) => edge.target)
    descendants.forEach((id) => branch.add(id))
  }
  return branch
}

const nodes = computed<Node[]>(() =>
  displayGraph.value.nodes.map((item) => ({
    id: item.id,
    type: 'custom',
    position: layoutPositions.value.get(item.id) ?? { x: 0, y: 0 },
    sourcePosition: Position.Bottom,
    targetPosition: Position.Top,
    data: {
      kindLabel: kindLabel[item.kind],
      agentLabel: item.agent ? agentLabel[item.agent] : null,
      label: item.label,
      statusLabel: statusLabel[item.status],
      detail: item.detail,
      toolCount: displayGraph.value.toolCounts.get(item.id) ?? 0,
    },
    class: [
      'workflow-node',
      `kind-${item.kind}`,
      `status-${item.status}`,
      props.selectedNodeId === item.id ? 'is-selected' : '',
      currentFocusId.value === item.id ? 'is-focused' : '',
      focusedBranchIds.value.has(item.id) ? 'is-focus-context' : '',
    ],
  })),
)

const edges = computed<Edge[]>(() => {
  const visible = new Set(displayGraph.value.nodes.map((node) => node.id))
  return displayGraph.value.edges
    .filter((edge) => visible.has(edge.source) && visible.has(edge.target))
    .map((edge) => {
      const inFocus =
        focusedBranchIds.value.has(edge.source) && focusedBranchIds.value.has(edge.target)
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourcePosition: Position.Bottom,
        targetPosition: Position.Top,
        class: [
          `relation-${edge.relation}`,
          inFocus ? 'is-focus-edge' : '',
          currentFocusId.value && !inFocus ? 'is-muted-edge' : '',
        ],
        animated: runningIds.value.has(edge.source) || runningIds.value.has(edge.target),
        markerEnd: MarkerType.ArrowClosed,
        type: edge.relation === 'evidence' ? 'straight' : 'smoothstep',
      }
    })
})

function selectNode(event: NodeMouseEvent) {
  emit('select', event.node.id)
  currentFocusId.value = event.node.id
  focusedBranchIds.value = focusBranch(event.node.id)
}

function clearFocus() {
  currentFocusId.value = null
  focusedBranchIds.value = new Set()
}

async function fitAll() {
  clearFocus()
  await nextTick()
  await fitView({ padding: 0.18, duration: 360, maxZoom: 1 })
}

let layoutFitTimer: number | null = null

async function fitVisibleGraph(incremental: boolean) {
  await nextTick()
  await new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve()))
  })
  await fitView({
    padding: incremental ? 0.2 : 0.18,
    duration: incremental ? 460 : 360,
    minZoom: incremental ? 0.5 : 0.5,
    maxZoom: incremental ? 0.9 : 1,
  })
}

watch(
  () => displayGraph.value.nodes.map((node) => node.id).sort().join('|'),
  (signature, previous = '') => {
    if (!signature || signature === previous) return
    if (layoutFitTimer !== null) window.clearTimeout(layoutFitTimer)
    layoutFitTimer = window.setTimeout(() => {
      layoutFitTimer = null
      void fitVisibleGraph(Boolean(previous))
    }, 520)
  },
  { flush: 'post', immediate: true },
)

onBeforeUnmount(() => {
  if (layoutFitTimer !== null) window.clearTimeout(layoutFitTimer)
})
</script>

<template>
  <section class="flow-section" aria-labelledby="flow-heading">
    <header class="flow-toolbar">
      <div class="flow-identity">
        <span class="flow-icon"><Network :size="16" /></span>
        <div>
          <h2 id="flow-heading">
            执行拓扑
          </h2>
          <span class="flow-count" :class="{ active: runningIds.size > 0 }">
            <Radio :size="12" /> {{ displayGraph.nodes.length }} 节点 · {{ displayGraph.edges.length }} 连接
          </span>
        </div>
      </div>

      <div v-if="currentFocusLabel" class="focus-chip">
        <Focus :size="13" />
        <span>{{ currentFocusLabel }}</span>
        <button type="button" aria-label="取消节点聚焦" @click="clearFocus">
          ×
        </button>
      </div>

      <div class="flow-actions">
        <NButtonGroup size="small">
          <NTooltip>
            <template #trigger>
              <NButton circle aria-label="放大任务图" @click="zoomGraphIn({ duration: 180 })">
                <template #icon>
                  <ZoomIn :size="15" />
                </template>
              </NButton>
            </template>
            放大
          </NTooltip>
          <NTooltip>
            <template #trigger>
              <NButton circle aria-label="缩小任务图" @click="zoomGraphOut({ duration: 180 })">
                <template #icon>
                  <ZoomOut :size="15" />
                </template>
              </NButton>
            </template>
            缩小
          </NTooltip>
          <NTooltip>
            <template #trigger>
              <NButton circle aria-label="适配完整任务图" @click="fitAll">
                <template #icon>
                  <Maximize2 :size="15" />
                </template>
              </NButton>
            </template>
            适配全图
          </NTooltip>
        </NButtonGroup>
      </div>
    </header>

    <slot name="controls" />

    <div class="flow-wrap" aria-label="Multi-Agent 动态执行拓扑">
      <VueFlow
        :nodes="nodes"
        :edges="edges"
        :nodes-draggable="false"
        :zoom-on-scroll="true"
        :pan-on-drag="true"
        :min-zoom="0.28"
        :max-zoom="1.6"
        @node-click="selectNode"
      >
        <template #node-custom="{ data }">
          <div class="node-content">
            <div class="node-meta">
              <span>{{ data.kindLabel }}{{ data.agentLabel ? ` · ${data.agentLabel}` : '' }}</span>
              <b v-if="data.toolCount > 0">{{ data.toolCount }} 工具</b>
            </div>
            <div class="node-label">
              {{ data.label }}
            </div>
            <div v-if="data.detail" class="node-detail">
              {{ data.detail }}
            </div>
            <div class="node-status">
              <i />{{ data.statusLabel }}
            </div>
          </div>
        </template>
        <Background :variant="BackgroundVariant.Dots" :gap="24" :size="1" />
      </VueFlow>

      <div v-if="displayGraph.nodes.length === 0" class="flow-empty">
        <span><Network :size="24" /></span>
        <strong>等待任务调度</strong>
        <p>开始审查或播放演示后，执行节点会在这里实时展开。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.flow-section {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  height: 100%;
  min-width: 0;
}

.flow-toolbar {
  align-items: center;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  gap: var(--space-3);
  min-height: 3.5rem;
  padding: 0 var(--space-3) 0 var(--space-4);
}

.flow-identity {
  align-items: center;
  display: flex;
  gap: var(--space-3);
  min-width: 0;
}

.flow-icon {
  align-items: center;
  background: color-mix(in srgb, var(--color-cyan) 13%, transparent);
  border-radius: var(--radius-md);
  color: var(--color-cyan);
  display: inline-flex;
  height: 2rem;
  justify-content: center;
  width: 2rem;
}

.flow-identity h2 {
  font-size: 0.82rem;
  font-weight: 600;
  margin: 0;
}

.flow-count {
  align-items: center;
  color: var(--color-subtle);
  display: flex;
  font-family: var(--font-mono);
  font-size: 0.64rem;
  gap: var(--space-1);
  margin-top: 0.15rem;
}

.flow-count.active {
  color: var(--color-green);
}

.focus-chip {
  align-items: center;
  background: color-mix(in srgb, var(--color-cyan) 8%, var(--color-surface-raised));
  border: 1px solid color-mix(in srgb, var(--color-cyan) 38%, var(--color-border));
  border-radius: var(--radius-md);
  color: var(--color-cyan);
  display: flex;
  font-size: 0.66rem;
  gap: var(--space-2);
  margin-left: auto;
  max-width: 22rem;
  min-width: 0;
  padding: var(--space-1) var(--space-2);
}

.focus-chip span {
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-chip button {
  background: transparent;
  border: 0;
  color: var(--color-muted);
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  padding: 0;
}

.focus-chip button:hover {
  color: var(--color-text);
}

.flow-actions {
  margin-left: auto;
}

.focus-chip + .flow-actions {
  margin-left: 0;
}

.flow-wrap {
  background: var(--color-bg);
  min-height: 28rem;
  min-width: 0;
  position: relative;
}

.flow-empty {
  align-items: center;
  color: var(--color-subtle);
  display: flex;
  flex-direction: column;
  inset: 0;
  justify-content: center;
  pointer-events: none;
  position: absolute;
  text-align: center;
}

.flow-empty > span {
  align-items: center;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-muted);
  display: inline-flex;
  height: 3rem;
  justify-content: center;
  margin-bottom: var(--space-3);
  width: 3rem;
}

.flow-empty strong {
  color: var(--color-text);
  font-size: 0.84rem;
  font-weight: 600;
}

.flow-empty p {
  font-size: 0.7rem;
  margin: var(--space-1) 0 0;
}

.flow-wrap :deep(.vue-flow__node) {
  background: color-mix(in srgb, var(--color-surface-raised) 96%, transparent);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  box-shadow: 0 8px 24px color-mix(in srgb, var(--color-bg) 42%, transparent);
  color: var(--color-muted);
  cursor: pointer;
  font-family: var(--font-mono);
  height: 7rem;
  overflow: hidden;
  padding: var(--space-3);
  text-align: left;
  transition: transform 460ms cubic-bezier(0.2, 0.8, 0.2, 1), border-color 180ms ease, box-shadow 180ms ease, opacity 180ms ease;
  width: 15.5rem;
}

.flow-wrap :deep(.vue-flow__node.kind-input),
.flow-wrap :deep(.vue-flow__node.kind-coordinator),
.flow-wrap :deep(.vue-flow__node.kind-report) {
  height: 5.5rem;
  width: 13rem;
}

.node-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
}

.node-meta {
  align-items: center;
  color: var(--color-subtle);
  display: flex;
  font-size: 0.62rem;
  gap: var(--space-2);
  justify-content: space-between;
  min-width: 0;
}

.node-meta > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-meta b {
  background: color-mix(in srgb, var(--color-blue) 14%, transparent);
  border-radius: var(--radius-sm);
  color: var(--color-blue);
  flex: 0 0 auto;
  font-size: 0.57rem;
  font-weight: 500;
  padding: 0.1rem 0.3rem;
}

.node-label {
  color: var(--color-text);
  display: -webkit-box;
  font-family: var(--font-sans);
  font-size: 0.78rem;
  font-weight: 600;
  line-height: 1.35;
  margin-top: var(--space-2);
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.node-detail {
  color: var(--color-muted);
  display: -webkit-box;
  font-size: 0.62rem;
  line-height: 1.4;
  margin-top: var(--space-1);
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.node-status {
  align-items: center;
  color: var(--color-muted);
  display: flex;
  font-size: 0.59rem;
  gap: var(--space-1);
  margin-top: auto;
}

.node-status i {
  background: var(--color-subtle);
  border-radius: 50%;
  height: 0.4rem;
  width: 0.4rem;
}

.flow-wrap :deep(.vue-flow__node:hover),
.flow-wrap :deep(.vue-flow__node.is-selected),
.flow-wrap :deep(.vue-flow__node.is-focused) {
  border-color: var(--color-cyan);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-cyan) 18%, transparent), 0 12px 30px color-mix(in srgb, var(--color-bg) 52%, transparent);
}

.flow-wrap :deep(.vue-flow__node.kind-coordinator) {
  border-color: color-mix(in srgb, var(--color-violet) 72%, var(--color-border));
}

.flow-wrap :deep(.vue-flow__node.kind-finding) {
  border-left: 3px solid var(--color-amber);
}

.flow-wrap :deep(.vue-flow__node.kind-verifier) {
  border-color: color-mix(in srgb, var(--color-violet) 68%, var(--color-border));
}

.flow-wrap :deep(.vue-flow__node.status-running) {
  animation: pulse-ring 1.5s infinite;
  border-color: var(--color-cyan);
}

.flow-wrap :deep(.vue-flow__node.status-running .node-status i) {
  animation: pulse-opacity 1s infinite;
  background: var(--color-cyan);
}

.flow-wrap :deep(.vue-flow__node.status-completed .node-status i) {
  background: var(--color-green);
}

.flow-wrap :deep(.vue-flow__node.status-failed),
.flow-wrap :deep(.vue-flow__node.status-cancelled) {
  border-color: color-mix(in srgb, var(--color-red) 65%, var(--color-border));
}

.flow-wrap :deep(.vue-flow__node.status-failed .node-status i),
.flow-wrap :deep(.vue-flow__node.status-cancelled .node-status i) {
  background: var(--color-red);
}

.flow-wrap :deep(.vue-flow__edge-path) {
  stroke: var(--color-border-strong);
  stroke-width: 1.6;
  transition: opacity 180ms ease, stroke 180ms ease, stroke-width 180ms ease;
}

.flow-wrap :deep(.vue-flow__edge.animated .vue-flow__edge-path) {
  stroke: var(--color-cyan);
  stroke-dasharray: 7 5;
  stroke-width: 2;
}

.flow-wrap :deep(.vue-flow__edge.relation-handoff .vue-flow__edge-path) {
  stroke: var(--color-violet);
  stroke-dasharray: 6 4;
}

.flow-wrap :deep(.vue-flow__edge.relation-challenge .vue-flow__edge-path) {
  stroke: var(--color-amber);
  stroke-dasharray: 3 4;
}

.flow-wrap :deep(.vue-flow__edge.relation-evidence .vue-flow__edge-path) {
  opacity: 0.55;
  stroke: var(--color-blue);
  stroke-dasharray: 2 5;
  stroke-width: 1.2;
}

.flow-wrap :deep(.vue-flow__edge.is-focus-edge .vue-flow__edge-path) {
  opacity: 1;
  stroke-width: 2.4;
}

.flow-wrap :deep(.vue-flow__edge.is-muted-edge .vue-flow__edge-path) {
  opacity: 0.18;
}

.flow-wrap :deep(.vue-flow__arrowhead polyline) {
  fill: var(--color-border-strong);
  stroke: var(--color-border-strong);
}
</style>
