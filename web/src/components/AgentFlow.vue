<script setup lang="ts">
import { Background, BackgroundVariant } from '@vue-flow/background'
import { MarkerType, VueFlow, useVueFlow, type Edge, type Node, type NodeMouseEvent } from '@vue-flow/core'
import { LocateFixed, Maximize2, Network, Radio, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { NButton, NButtonGroup, NTooltip } from 'naive-ui'
import { computed, nextTick, ref, shallowRef, watch } from 'vue'

import type {
  AgentName,
  WorkflowEdge,
  WorkflowKind,
  WorkflowNode,
  WorkflowStatus,
} from '@/types'

const props = defineProps<{
  workflowNodes: WorkflowNode[]
  workflowEdges: WorkflowEdge[]
  layoutWorkflowNodes: WorkflowNode[]
  layoutWorkflowEdges: WorkflowEdge[]
  layoutKey: string | null
  selectedNodeId: string | null
}>()
const emit = defineEmits<{ select: [nodeId: string] }>()
const { fitBounds, fitView, zoomIn: zoomGraphIn, zoomOut: zoomGraphOut } = useVueFlow()

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
  // 统计每个节点关联的工具调用数量
  const toolNodes = sourceNodes.filter((node) => node.kind === 'tool')
  const toolCountByTask = new Map<string, number>()

  for (const tool of toolNodes) {
    const taskId = tool.task_id ?? tool.id
    toolCountByTask.set(taskId, (toolCountByTask.get(taskId) ?? 0) + 1)
  }

  // 完全过滤掉工具节点，只保留主要工作流节点
  const regularNodes = sourceNodes.filter((node) => node.kind !== 'tool')
  const regularIds = new Set(regularNodes.map((node) => node.id))

  // 只保留非工具节点之间的边
  const filteredEdges = sourceEdges.filter(
    (edge) => regularIds.has(edge.source) && regularIds.has(edge.target),
  )

  // 给节点添加工具调用计数信息
  const nodesWithToolCount: WorkflowNode[] = regularNodes.map((node) => ({
    ...node,
    // 保持原始 detail，工具调用数通过单独字段传递
  }))

  return { nodes: nodesWithToolCount, edges: filteredEdges, toolCounts: toolCountByTask }
}

const displayGraph = computed(() => aggregateToolNodes(props.workflowNodes, props.workflowEdges))
const layoutGraph = computed(() =>
  aggregateToolNodes(props.layoutWorkflowNodes, props.layoutWorkflowEdges),
)

const nodeSizes: Record<WorkflowKind, { width: number; height: number }> = {
  input: { width: 192, height: 64 },
  coordinator: { width: 192, height: 68 },
  agent_task: { width: 216, height: 74 },
  tool: { width: 168, height: 64 },
  finding: { width: 216, height: 74 },
  verifier: { width: 216, height: 74 },
  report: { width: 192, height: 64 },
}

type Position = { x: number; y: number }

function calculateLayout(): Map<string, Position> {
  // 如果没有节点，返回空 Map
  if (layoutGraph.value.nodes.length === 0) {
    return new Map()
  }

  // 构建邻接表，找出所有的父子关系
  const forwardEdges = layoutGraph.value.edges.filter(
    (edge) => edge.relation !== 'evidence',
  )
  const children = new Map<string, string[]>()
  const parents = new Map<string, string[]>()

  for (const edge of forwardEdges) {
    if (!children.has(edge.source)) children.set(edge.source, [])
    if (!parents.has(edge.target)) parents.set(edge.target, [])
    children.get(edge.source)!.push(edge.target)
    parents.get(edge.target)!.push(edge.source)
  }

  // 找到根节点（没有父节点的节点）
  const allNodes = layoutGraph.value.nodes.map(n => n.id)
  const roots = allNodes.filter(id => !parents.has(id) || parents.get(id)!.length === 0)

  // 树状布局：为每个节点分配位置
  const positions = new Map<string, Position>()
  const processed = new Set<string>()
  const computing = new Set<string>() // 防止循环依赖
  let currentY = 60

  // 计算子树宽度（带循环检测）
  function getSubtreeWidth(nodeId: string): number {
    if (processed.has(nodeId) || computing.has(nodeId)) return 0
    computing.add(nodeId)

    const nodeChildren = children.get(nodeId) || []
    if (nodeChildren.length === 0) {
      computing.delete(nodeId)
      return nodeSizes[layoutGraph.value.nodes.find(n => n.id === nodeId)!.kind].width
    }

    const childrenWidth = nodeChildren
      .map(childId => getSubtreeWidth(childId))
      .reduce((sum, w) => sum + w, 0)

    const spacing = Math.max(0, nodeChildren.length - 1) * 120
    computing.delete(nodeId)
    return Math.max(
      childrenWidth + spacing,
      nodeSizes[layoutGraph.value.nodes.find(n => n.id === nodeId)!.kind].width
    )
  }

  // 递归布局节点
  function layoutNode(nodeId: string, x: number, y: number, availableWidth: number) {
    if (processed.has(nodeId)) return
    processed.add(nodeId)

    const node = layoutGraph.value.nodes.find(n => n.id === nodeId)
    if (!node) return

    const nodeSize = nodeSizes[node.kind]

    // 节点居中放置在可用宽度中
    const nodeX = x + (availableWidth - nodeSize.width) / 2
    positions.set(nodeId, { x: nodeX, y })

    // 布局子节点
    const nodeChildren = children.get(nodeId) || []
    if (nodeChildren.length === 0) return

    // 计算每个子节点的宽度需求
    const childWidths = nodeChildren.map(childId => getSubtreeWidth(childId))
    const totalChildWidth = childWidths.reduce((sum, w) => sum + w, 0)
    const spacing = 120
    const totalWidth = totalChildWidth + spacing * Math.max(0, nodeChildren.length - 1)

    // 从左到右放置子节点
    let childX = x + (availableWidth - totalWidth) / 2
    const childY = y + nodeSize.height + 120

    for (let i = 0; i < nodeChildren.length; i++) {
      const childId = nodeChildren[i]
      const childWidth = childWidths[i]
      if (childId && childWidth !== undefined) {
        layoutNode(childId, childX, childY, childWidth)
        childX += childWidth + spacing
      }
    }
  }

  // 从每个根节点开始布局 - 动态计算实际使用的宽度
  let offsetX = 60
  for (const root of roots) {
    const rootWidth = getSubtreeWidth(root)
    layoutNode(root, offsetX, currentY, rootWidth)

    // 计算这棵树实际使用的宽度（基于已放置节点的实际位置）
    let maxX = 0
    const treeNodeIds = new Set<string>()
    const collectTreeNodes = (nodeId: string) => {
      if (treeNodeIds.has(nodeId)) return
      treeNodeIds.add(nodeId)
      const nodeChildren = children.get(nodeId) || []
      for (const childId of nodeChildren) {
        collectTreeNodes(childId)
      }
    }
    collectTreeNodes(root)

    for (const nodeId of treeNodeIds) {
      const pos = positions.get(nodeId)
      if (pos) {
        const node = layoutGraph.value.nodes.find(n => n.id === nodeId)
        if (node) {
          const nodeSize = nodeSizes[node.kind]
          maxX = Math.max(maxX, pos.x + nodeSize.width)
        }
      }
    }

    offsetX = maxX + 200 // 使用实际宽度，下一棵树从实际结束位置 + 间距开始
  }

  // 处理孤立节点（没有边连接的节点）
  for (const node of layoutGraph.value.nodes) {
    if (!positions.has(node.id)) {
      positions.set(node.id, { x: offsetX, y: currentY })
      offsetX += nodeSizes[node.kind].width + 120
    }
  }

  return positions
}

const stablePositions = shallowRef<Map<string, Position>>(new Map())
const currentFocusId = ref<string | null>(null)
const focusedBranchIds = shallowRef<Set<string>>(new Set())

const currentFocusLabel = computed(
  () => displayGraph.value.nodes.find((node) => node.id === currentFocusId.value)?.label ?? null,
)

function overlapsExisting(
  position: Position,
  node: WorkflowNode,
  positions: Map<string, Position>,
) {
  const size = nodeSizes[node.kind]
  return [...positions].some(([identifier, existing]) => {
    const other = layoutGraph.value.nodes.find((item) => item.id === identifier)
    if (!other) return false
    const otherSize = nodeSizes[other.kind]
    return (
      position.x < existing.x + otherSize.width + 60 &&
      position.x + size.width + 60 > existing.x &&
      position.y < existing.y + otherSize.height + 40 &&
      position.y + size.height + 40 > existing.y
    )
  })
}

watch(
  [
    () => props.layoutKey,
    () => layoutGraph.value.nodes.map((node) => node.id).join('|'),
    () => layoutGraph.value.edges.map((edge) => edge.id).join('|'),
  ],
  ([key], [previousKey]) => {
    const generated = calculateLayout()
    if (key !== previousKey || stablePositions.value.size === 0) {
      stablePositions.value = generated
      return
    }

    const next = new Map(stablePositions.value)
    for (const node of layoutGraph.value.nodes) {
      if (next.has(node.id)) continue
      const candidate = { ...(generated.get(node.id) ?? { x: 0, y: 0 }) }
      while (overlapsExisting(candidate, node, next)) candidate.x += nodeSizes[node.kind].width + 80
      next.set(node.id, candidate)
    }
    stablePositions.value = next
  },
  { immediate: true },
)

const nodes = computed<Node[]>(() =>
  displayGraph.value.nodes.map((item) => {
    const toolCount = displayGraph.value.toolCounts.get(item.id) ?? 0
    return {
      id: item.id,
      type: 'custom',
      position: stablePositions.value.get(item.id) ?? { x: 0, y: 0 },
      data: {
        kind: item.kind,
        kindLabel: kindLabel[item.kind],
        agent: item.agent,
        agentLabel: item.agent ? agentLabel[item.agent] : null,
        label: item.label,
        status: item.status,
        statusLabel: statusLabel[item.status],
        detail: item.detail,
        toolCount,
      },
      class: [
        'workflow-node',
        `kind-${item.kind}`,
        `status-${item.status}`,
        props.selectedNodeId === item.id ? 'is-selected' : '',
        currentFocusId.value === item.id ? 'is-focused' : '',
        focusedBranchIds.value.has(item.id) ? 'is-focus-context' : '',
      ],
    }
  }),
)

const runningIds = computed(
  () =>
    new Set(
      displayGraph.value.nodes
        .filter((item) => item.status === 'running')
        .map((item) => item.id),
    ),
)

const edges = computed<Edge[]>(() =>
  displayGraph.value.edges
    .filter(
      (item) =>
        displayGraph.value.nodes.some((node) => node.id === item.source) &&
        displayGraph.value.nodes.some((node) => node.id === item.target),
    )
    .map((item) => ({
      id: item.id,
      source: item.source,
      target: item.target,
      class: [`relation-${item.relation}`],
      animated: runningIds.value.has(item.source) || runningIds.value.has(item.target),
      markerEnd: MarkerType.ArrowClosed,
      type: item.relation === 'evidence' ? 'straight' : 'smoothstep',
    })),
)

function selectNode(event: NodeMouseEvent) {
  const selected = displayGraph.value.nodes.find((node) => node.id === event.node.id)
  emit('select', selected?.kind === 'tool' && selected.task_id ? selected.task_id : event.node.id)
  void focusNode(event.node.id)
}

function focusBranch(identifier: string) {
  const visible = new Set(displayGraph.value.nodes.map((node) => node.id))
  const forwardEdges = displayGraph.value.edges.filter(
    (edge) => edge.relation !== 'evidence' && edge.relation !== 'result',
  )
  const branch = new Set([identifier])
  let ancestors = [identifier]
  for (let depth = 0; depth < 3; depth += 1) {
    ancestors = forwardEdges
      .filter((edge) => ancestors.includes(edge.target) && visible.has(edge.source))
      .map((edge) => edge.source)
    ancestors.forEach((id) => branch.add(id))
  }
  let descendants = [identifier]
  for (let depth = 0; depth < 2; depth += 1) {
    descendants = forwardEdges
      .filter((edge) => descendants.includes(edge.source) && visible.has(edge.target))
      .map((edge) => edge.target)
    descendants.forEach((id) => branch.add(id))
  }
  return [...branch]
}

function branchBounds(identifiers: string[]) {
  const visibleNodes = displayGraph.value.nodes.filter((node) => identifiers.includes(node.id))
  const positioned = visibleNodes
    .map((node) => ({ node, position: stablePositions.value.get(node.id) }))
    .filter((item): item is { node: WorkflowNode; position: Position } => Boolean(item.position))
  if (positioned.length === 0) return null

  const minX = Math.min(...positioned.map((item) => item.position.x))
  const minY = Math.min(...positioned.map((item) => item.position.y))
  const maxX = Math.max(
    ...positioned.map((item) => item.position.x + nodeSizes[item.node.kind].width),
  )
  const maxY = Math.max(
    ...positioned.map((item) => item.position.y + nodeSizes[item.node.kind].height),
  )
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
}

async function focusNode(identifier: string) {
  const identifiers = focusBranch(identifier)
  const bounds = branchBounds(identifiers)
  if (!bounds) return
  currentFocusId.value = identifier
  focusedBranchIds.value = new Set(identifiers)
  await nextTick()
  await fitBounds(bounds, { padding: 0.2, duration: 420 })
}

function focusCurrentBranch() {
  if (currentFocusId.value) void focusNode(currentFocusId.value)
}

function fitAll() {
  currentFocusId.value = null
  focusedBranchIds.value = new Set()
  void fitView({ padding: 0.15, duration: 360 })
}

watch(
  () =>
    displayGraph.value.nodes.map(
      (node) => `${node.id}:${node.status}:${node.label}`,
    ),
  async (signature, previous = []) => {
    if (signature.length === 0 || signature.join('|') === previous.join('|')) return
    await nextTick()
    const previousStates = new Map(
      previous.map((value) => {
        const [id, status, ...label] = value.split(':')
        return [id, { status, label: label.join(':') }] as const
      }),
    )
    const newIds = displayGraph.value.nodes
      .filter((node) => !previousStates.has(node.id))
      .map((node) => node.id)

    if (previous.length === 0) {
      await fitView({ padding: 0.15, duration: 420 })
      return
    }

    // 只在有新节点时聚焦，忽略所有其他变化（包括状态、标签等）
    const focusId = newIds.at(-1)
    if (focusId) await focusNode(focusId)
  },
  { flush: 'post' },
)
</script>

<template>
  <section class="flow-section" aria-labelledby="flow-heading">
    <header class="flow-header">
      <div>
        <span><Network :size="15" /></span>
        <div>
          <h2 id="flow-heading">
            动态任务图
          </h2>
          <p>每个节点和连接都来自真实调度事件</p>
        </div>
      </div>
      <span class="live-indicator" :class="{ active: displayGraph.nodes.some((node) => node.status === 'running') }">
        <Radio :size="13" /> {{ displayGraph.nodes.length }} 节点 · {{ displayGraph.edges.length }} 连接
      </span>
    </header>
    <slot name="controls" />
    <div class="flow-wrap" aria-label="Multi-Agent 动态执行拓扑">
      <div v-if="currentFocusLabel" class="focus-status">
        <LocateFixed :size="14" />
        <span>当前聚焦</span>
        <strong>{{ currentFocusLabel }}</strong>
        <NTooltip>
          <template #trigger>
            <NButton
              quaternary
              circle
              size="tiny"
              aria-label="返回当前聚焦分支"
              @click="focusCurrentBranch"
            >
              <template #icon>
                <LocateFixed :size="14" />
              </template>
            </NButton>
          </template>
          返回当前聚焦分支
        </NTooltip>
      </div>
      <NButtonGroup class="zoom-controls" size="small">
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
          适配完整任务图
        </NTooltip>
      </NButtonGroup>
      <VueFlow
        :nodes="nodes"
        :edges="edges"
        :nodes-draggable="false"
        :zoom-on-scroll="true"
        :pan-on-drag="true"
        :min-zoom="0.4"
        :max-zoom="2"
        @node-click="selectNode"
      >
        <template #node-custom="{ data }">
          <div class="node-content">
            <div v-if="data.toolCount > 0" class="tool-badge">
              {{ data.toolCount }}
            </div>
            <div class="node-header">
              {{ data.kindLabel }}{{ data.agentLabel ? ` · ${data.agentLabel}` : '' }}
            </div>
            <div class="node-label">
              {{ data.label }}
            </div>
            <div v-if="data.detail" class="node-detail">
              {{ data.detail }}
            </div>
            <div class="node-status">
              {{ data.statusLabel }}
            </div>
          </div>
        </template>
        <Background :variant="BackgroundVariant.Dots" :gap="20" :size="1" />
      </VueFlow>
      <div v-if="displayGraph.nodes.length === 0" class="flow-empty">
        <Network :size="26" />
        <strong>等待 Coordinator 建立任务图</strong>
        <span>开始审查或播放演示后，调度节点将从这里逐个生长</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.flow-section {
  min-width: 0;
}

.flow-header {
  align-items: center;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  height: 3.8rem;
  justify-content: space-between;
  padding: 0 var(--space-4);
}

.flow-header > div {
  align-items: center;
  display: flex;
  gap: var(--space-3);
}

.flow-header > div > span {
  align-items: center;
  background: color-mix(in srgb, var(--color-cyan) 13%, transparent);
  border-radius: var(--radius-md);
  color: var(--color-cyan);
  display: inline-flex;
  height: 2rem;
  justify-content: center;
  width: 2rem;
}

.flow-header h2 {
  font-size: 0.82rem;
  font-weight: 600;
  margin: 0;
}

.flow-header p {
  color: var(--color-subtle);
  font-size: 0.66rem;
  margin: var(--space-1) 0 0;
}

.live-indicator {
  align-items: center;
  color: var(--color-subtle);
  display: inline-flex;
  font-family: var(--font-mono);
  font-size: 0.64rem;
  gap: var(--space-1);
}

.live-indicator.active {
  color: var(--color-green);
}

.flow-wrap {
  height: max(40rem, calc(100vh - 16rem));
  min-height: 40rem;
  position: relative;
}

.zoom-controls {
  position: absolute;
  right: var(--space-3);
  top: var(--space-3);
  z-index: 10;
}

.focus-status {
  align-items: center;
  background: color-mix(in srgb, var(--color-surface-raised) 94%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-cyan) 55%, var(--color-border));
  border-radius: var(--radius-md);
  color: var(--color-cyan);
  display: grid;
  font-size: 0.66rem;
  gap: var(--space-2);
  grid-template-columns: auto auto minmax(0, 1fr) auto;
  left: var(--space-3);
  max-width: min(30rem, calc(100% - 11rem));
  padding: var(--space-1) var(--space-2);
  position: absolute;
  top: var(--space-3);
  z-index: 10;
}

.focus-status strong {
  color: var(--color-text);
  font-family: var(--font-mono);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.flow-empty {
  align-items: center;
  color: var(--color-subtle);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  inset: 0;
  justify-content: center;
  pointer-events: none;
  position: absolute;
  text-align: center;
}

.flow-empty strong {
  color: var(--color-muted);
  font-size: 0.82rem;
  font-weight: 500;
}

.flow-empty span {
  font-size: 0.7rem;
  max-width: 19rem;
}

.flow-wrap :deep(.vue-flow__node) {
  animation: node-enter 360ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
  background: color-mix(in srgb, var(--color-surface-raised) 94%, transparent);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-muted);
  font-family: var(--font-mono);
  font-size: 0.62rem;
  line-height: 1.5;
  min-height: 4rem;
  padding: var(--space-2) var(--space-3);
  text-align: left;
  width: 13.5rem;
}

.node-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
  position: relative;
}

.tool-badge {
  position: absolute;
  top: -8px;
  right: -8px;
  background: var(--color-blue);
  color: white;
  font-size: 0.65rem;
  font-weight: 600;
  font-family: var(--font-mono);
  padding: 2px 6px;
  border-radius: var(--radius-full);
  line-height: 1.3;
  min-width: 20px;
  text-align: center;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  z-index: 1;
}

.node-header {
  font-weight: 500;
  opacity: 0.7;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-label {
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.4;
}

.node-detail {
  font-size: 0.56rem;
  opacity: 0.5;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.node-status {
  font-size: 0.58rem;
  opacity: 0.6;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.flow-wrap :deep(.vue-flow__node:hover),
.flow-wrap :deep(.vue-flow__node.is-selected) {
  border-color: var(--color-cyan);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-cyan) 15%, transparent);
  color: var(--color-text);
}

.flow-wrap :deep(.vue-flow__node.is-focus-context) {
  border-color: color-mix(in srgb, var(--color-cyan) 45%, var(--color-border));
}

.flow-wrap :deep(.vue-flow__node.is-focused) {
  border-color: var(--color-cyan);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-cyan) 20%, transparent);
  color: var(--color-text);
  z-index: 5;
}

.flow-wrap :deep(.vue-flow__node.kind-input),
.flow-wrap :deep(.vue-flow__node.kind-coordinator),
.flow-wrap :deep(.vue-flow__node.kind-report) {
  text-align: center;
  width: 12rem;
}

.flow-wrap :deep(.vue-flow__node.kind-coordinator) {
  border-color: color-mix(in srgb, var(--color-violet) 70%, var(--color-border));
}

.flow-wrap :deep(.vue-flow__node.kind-tool) {
  border-style: dashed;
  min-height: 3.3rem;
  width: 10.5rem;
}

.flow-wrap :deep(.vue-flow__node.kind-finding) {
  border-left: 3px solid var(--color-amber);
}

.flow-wrap :deep(.vue-flow__node.kind-verifier) {
  border-color: color-mix(in srgb, var(--color-violet) 65%, var(--color-border));
}

.flow-wrap :deep(.vue-flow__node.status-running) {
  animation: node-enter 360ms ease-out both, pulse-ring 1.5s infinite;
  border-color: var(--color-cyan);
  color: var(--color-text);
}

.flow-wrap :deep(.vue-flow__node.status-completed) {
  border-color: color-mix(in srgb, var(--color-green) 68%, var(--color-border));
}

.flow-wrap :deep(.vue-flow__node.status-failed),
.flow-wrap :deep(.vue-flow__node.status-cancelled) {
  border-color: color-mix(in srgb, var(--color-red) 65%, var(--color-border));
  opacity: 0.55;
}

.flow-wrap :deep(.vue-flow__edge-path) {
  stroke: var(--color-border-strong);
  stroke-width: 1.5;
  transition: stroke 180ms ease, stroke-width 180ms ease;
}

.flow-wrap :deep(.vue-flow__edge.animated .vue-flow__edge-path) {
  stroke: var(--color-cyan);
  stroke-dasharray: 7 5;
  stroke-width: 2;
}

.flow-wrap :deep(.vue-flow__edge.relation-handoff .vue-flow__edge-path) {
  stroke: var(--color-violet);
  stroke-dasharray: 5 4;
  stroke-width: 2.2;
}

.flow-wrap :deep(.vue-flow__edge.relation-challenge .vue-flow__edge-path) {
  stroke: var(--color-amber);
}

.flow-wrap :deep(.vue-flow__edge.relation-evidence .vue-flow__edge-path) {
  stroke: var(--color-blue);
  stroke-dasharray: 3 4;
}

.flow-wrap :deep(.vue-flow__arrowhead polyline) {
  fill: var(--color-border-strong);
  stroke: var(--color-border-strong);
}

@keyframes node-enter {
  from {
    filter: brightness(1.45);
    opacity: 0;
  }
  to {
    filter: brightness(1);
    opacity: 1;
  }
}
</style>
