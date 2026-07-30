<template>
  <g class="flow-node" :class="[node.status, node.type]"
     @click="$emit('click')" style="cursor: pointer">
    <!-- 背景 -->
    <rect :x="node.x" :y="node.y" :width="NODE_W" :height="NODE_H"
      rx="8" class="node-bg" />

    <!-- 状态图标 -->
    <circle v-if="node.status === 'running'" :cx="node.x + 16" :cy="node.y + NODE_H/2" r="5"
      class="pulse-dot" />
    <text v-else-if="node.status === 'completed'" :x="node.x + 16" :y="node.y + NODE_H/2 + 3"
      class="icon-check" text-anchor="middle">&#10003;</text>
    <text v-else-if="node.status === 'failed'" :x="node.x + 16" :y="node.y + NODE_H/2 + 3"
      class="icon-cross" text-anchor="middle">&#10007;</text>

    <!-- 标签 -->
    <text :x="node.x + 32" :y="node.y + 22" class="node-label">{{ node.label }}</text>

    <!-- 详情 -->
    <text v-if="node.detail" :x="node.x + 32" :y="node.y + 40"
      class="node-detail">{{ node.detail }}</text>

    <!-- Agent 类型的额外标记 -->
    <rect v-if="node.type === 'agent' && node.detail"
      :x="node.x + NODE_W - 28" :y="node.y + 8" width="20" height="20" rx="10"
      class="badge-bg" />
    <text v-if="node.type === 'agent' && node.detail"
      :x="node.x + NODE_W - 18" :y="node.y + 22"
      class="badge-text" text-anchor="middle">{{ badgeCount }}</text>
  </g>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const NODE_W = 160
const NODE_H = 56

const props = defineProps<{
  node: {
    id: string; type: string; label: string; status: string
    detail?: string; x: number; y: number
  }
}>()

defineEmits<{ click: [] }>()

const badgeCount = computed(() => {
  const m = props.node.detail?.match(/(\d+)/)
  return m ? m[1] : '?'
})
</script>

<style scoped>
.node-bg {
  fill: var(--color-surface);
  stroke: var(--color-border);
  stroke-width: 2;
  transition: all 0.3s;
}

.flow-node.running .node-bg {
  stroke: var(--color-primary);
  stroke-width: 3;
  filter: drop-shadow(0 0 6px rgba(59,130,246,0.3));
}

.flow-node.completed .node-bg {
  stroke: var(--color-success);
}

.flow-node.failed .node-bg {
  stroke: var(--color-danger);
}

.flow-node.agent .node-bg {
  rx: 12;
}

.flow-node.agent:hover .node-bg {
  fill: rgba(59,130,246,0.04);
}

.pulse-dot {
  fill: var(--color-primary);
  animation: pulse 1s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { r: 5; opacity: 1; }
  50% { r: 7; opacity: 0.6; }
}

.icon-check { fill: var(--color-success); font-size: 14px; font-weight: 700; }
.icon-cross { fill: var(--color-danger); font-size: 14px; font-weight: 700; }

.node-label {
  fill: var(--color-text);
  font-size: 14px;
  font-weight: 600;
}

.node-detail {
  fill: var(--color-text-muted);
  font-size: 11px;
}

.badge-bg {
  fill: var(--color-primary);
}

.badge-text {
  fill: #fff;
  font-size: 10px;
  font-weight: 700;
}
</style>
