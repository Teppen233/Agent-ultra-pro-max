<template>
  <div class="agent-card" :class="agent.status">
    <div class="card-header">
      <span class="status-dot" :class="agent.status"></span>
      <h4>{{ agent.name }}</h4>
      <span class="status-text">{{ statusLabel }}</span>
    </div>

    <div class="card-body">
      <div class="metric">
        <span class="metric-value">{{ agent.tools.length }}</span>
        <span class="metric-label">工具调用</span>
      </div>
      <div class="metric">
        <span class="metric-value">{{ agent.candidatesCount }}</span>
        <span class="metric-label">候选发现</span>
      </div>
      <div v-if="agent.startTime && agent.endTime" class="metric">
        <span class="metric-value">{{ formatDuration(agent.startTime, agent.endTime) }}</span>
        <span class="metric-label">耗时</span>
      </div>
    </div>

    <!-- 最近工具调用 -->
    <div v-if="agent.tools.length > 0" class="recent-tools">
      <div v-for="tool in agent.tools.slice(-3).reverse()" :key="tool.timestamp" class="mini-tool">
        <span class="mini-tool-name">{{ tool.tool }}</span>
        <span v-if="tool.durationMs" class="mini-tool-dur">{{ tool.durationMs }}ms</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentInfo } from '../stores/review'

const props = defineProps<{ agent: AgentInfo }>()

const statusLabel = computed(() => {
  switch (props.agent.status) {
    case 'idle':
      return '等待中'
    case 'running':
      return '运行中'
    case 'completed':
      return '已完成'
    case 'failed':
      return '失败'
    default:
      return '未知'
  }
})

function formatDuration(start: string, end: string): string {
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
</script>

<style scoped>
.agent-card {
  background: var(--color-surface);
  border-radius: var(--radius);
  padding: 16px;
  box-shadow: var(--shadow);
  border: 2px solid transparent;
  transition: border-color 0.3s;
}

.agent-card.running {
  border-color: var(--color-primary);
}

.agent-card.completed {
  border-color: var(--color-success);
}

.agent-card.failed {
  border-color: var(--color-danger);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.idle {
  background: var(--color-border);
}

.status-dot.running {
  background: var(--color-primary);
  animation: pulse-dot 1s ease-in-out infinite;
}

.status-dot.completed {
  background: var(--color-success);
}

.status-dot.failed {
  background: var(--color-danger);
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.3); }
}

.card-header h4 {
  font-size: 14px;
  font-weight: 600;
  flex: 1;
}

.status-text {
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--color-bg);
  color: var(--color-text-muted);
}

.agent-card.running .status-text {
  background: rgba(59, 130, 246, 0.1);
  color: var(--color-primary);
}

.agent-card.completed .status-text {
  background: rgba(16, 185, 129, 0.1);
  color: var(--color-success);
}

.agent-card.failed .status-text {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-danger);
}

.card-body {
  display: flex;
  gap: 24px;
  margin-bottom: 12px;
}

.metric {
  display: flex;
  flex-direction: column;
}

.metric-value {
  font-size: 18px;
  font-weight: 700;
}

.metric-label {
  font-size: 11px;
  color: var(--color-text-muted);
}

.recent-tools {
  border-top: 1px solid var(--color-border);
  padding-top: 8px;
}

.mini-tool {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 0;
}

.mini-tool-name {
  font-size: 12px;
  font-family: monospace;
  color: var(--color-text-muted);
}

.mini-tool-dur {
  font-size: 11px;
  color: var(--color-text-muted);
}
</style>
