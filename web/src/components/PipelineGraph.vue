<template>
  <div class="pipeline-graph">
    <svg class="pipeline-svg" :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="xMidYMid meet">
      <!-- 连线 -->
      <line v-for="(line, i) in connectorLines" :key="'line-'+i"
        :x1="line.x1" :y1="line.y1" :x2="line.x2" :y2="line.y2"
        :class="['connector', line.status]" />

      <!-- 并行分支连线 -->
      <template v-if="hasParallel">
        <line :x1="centerX" :y1="parallelY - 20" :x2="centerX - 80" :y2="parallelY"
          class="connector branch" />
        <line :x1="centerX" :y1="parallelY - 20" :x2="centerX + 80" :y2="parallelY"
          class="connector branch" />
        <line :x1="centerX - 80" :y1="parallelY + NODE_H" :x2="centerX" :y2="parallelY + NODE_H + 20"
          class="connector branch" />
        <line :x1="centerX + 80" :y1="parallelY + NODE_H" :x2="centerX" :y2="parallelY + NODE_H + 20"
          class="connector branch" />
      </template>

      <!-- 节点 -->
      <FlowNode v-for="node in nodes" :key="node.id"
        :node="node" :x="node.x" :y="node.y"
        @click="$emit('select-agent', node)" />
    </svg>

    <!-- 自适应容器，SVG 外的额外 Finding 摘要 -->
    <div v-if="childFindings.length > 0" class="findings-summary">
      <span class="summary-badge" v-for="f in childFindings" :key="f.id"
        :class="f.severity" :title="f.title">
        {{ f.title.substring(0, 18) }}{{ f.title.length > 18 ? '...' : '' }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { StageInfo, AgentInfo } from '../stores/review'
import FlowNode from './FlowNode.vue'

const props = defineProps<{
  stages: StageInfo[]
  agents: AgentInfo[]
  findings: Array<{ finding: { id: string; title: string; severity: string } }>
}>()

defineEmits<{
  'select-agent': [node: { id: string; type: string; label: string }]
}>()

const NODE_W = 160
const NODE_H = 56
const GAP = 40
const centerX = 300

// 构建节点布局
const nodes = computed(() => {
  const result: Array<{
    id: string; type: string; label: string; status: string
    detail?: string; x: number; y: number
  }> = []
  let y = 30

  // 阶段节点
  for (const stage of props.stages) {
    if (stage.key === 'reviewing') {
      // 并行 Agent 节点
      const defect = props.agents.find(a => a.key === 'defect')
      const intent = props.agents.find(a => a.key === 'intent')
      result.push({
        id: 'defect', type: 'agent',
        label: '缺陷检测', status: defect?.status ?? 'idle',
        detail: defect ? `${defect.candidatesCount} 发现` : '',
        x: centerX - 100, y,
      })
      result.push({
        id: 'intent', type: 'agent',
        label: '意图分析', status: intent?.status ?? 'idle',
        detail: intent ? `${intent.candidatesCount} 发现` : '',
        x: centerX + 100, y,
      })
      y += NODE_H + GAP
      continue
    }
    result.push({
      id: stage.key, type: 'stage',
      label: stage.name, status: stage.status,
      x: centerX, y,
    })
    y += NODE_H + GAP
  }
  return result
})

const hasParallel = computed(() =>
  props.agents.some(a => a.key === 'defect' || a.key === 'intent')
)

const parallelY = computed(() => {
  const idx = props.stages.findIndex(s => s.key === 'reviewing')
  return 30 + idx * (NODE_H + GAP)
})

const height = computed(() => 30 + nodes.value.length / 2 * (NODE_H + GAP) + 20)

const width = computed(() => 600)

// 连线计算
const connectorLines = computed(() => {
  const lines: Array<{ x1: number; y1: number; x2: number; y2: number; status: string }> = []
  const ns = nodes.value
  for (let i = 0; i < ns.length - 1; i++) {
    const a = ns[i]
    // 跳过并行节点的连线（由 SVG 分支线处理）
    if (a.type === 'agent') continue
    const b = ns[i + 1]
    if (b.type === 'agent') continue
    lines.push({
      x1: a.x + NODE_W / 2, y1: a.y + NODE_H,
      x2: b.x + NODE_W / 2, y2: b.y,
      status: a.status === 'completed' ? 'done' : 'pending',
    })
  }
  return lines
})

const childFindings = computed(() =>
  props.findings.slice(0, 6).map(f => f.finding)
)
</script>

<style scoped>
.pipeline-graph {
  background: var(--color-surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 16px;
  margin-bottom: 24px;
  overflow: hidden;
}

.pipeline-svg {
  width: 100%;
  max-width: 600px;
  display: block;
  margin: 0 auto;
}

.connector {
  stroke: var(--color-border);
  stroke-width: 2;
  transition: stroke 0.3s;
}
.connector.done { stroke: var(--color-success); }
.connector.running { stroke: var(--color-primary); }
.connector.branch { stroke-dasharray: 4 2; }

.findings-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 0 0;
  justify-content: center;
}

.summary-badge {
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 11px;
  cursor: default;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
}

.summary-badge.critical { border-color: #dc2626; color: #dc2626; }
.summary-badge.high { border-color: #ea580c; color: #ea580c; }
.summary-badge.medium { border-color: #ca8a04; color: #ca8a04; }
</style>
