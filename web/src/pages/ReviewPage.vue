<template>
  <div class="review-page">
    <!-- 头部元信息 -->
    <div class="review-header">
      <div class="header-left">
        <h2>实时审查进行中</h2>
        <span v-if="store.reviewTitle" class="review-title">{{ store.reviewTitle }}</span>
        <span class="run-id">Run: {{ store.runId }}</span>
      </div>
      <div class="header-right">
        <div class="countdown" :class="{ warning: remainingSecs < 60, danger: remainingSecs < 30 }">
          剩余 {{ formatTime(remainingSecs) }}
        </div>
      </div>
    </div>

    <!-- 阶段进度条 -->
    <StageProgress :stages="store.stages" :progress="store.stageProgress" />

    <!-- SSE / Replay 连接错误 -->
    <div v-if="sseError" class="status-banner error">
      <div>
        <p><strong>{{ sseError }}</strong></p>
        <p class="error-hint">请确认后端服务已启动：<code>uvicorn reviewcrew.server.app:app --reload</code></p>
      </div>
      <div class="error-actions">
        <button class="btn btn-sm" @click="retryConnection">重试连接</button>
        <router-link to="/" class="btn btn-sm btn-secondary">返回首页</router-link>
      </div>
    </div>

    <!-- Agent 状态卡片 -->
    <div class="agent-grid">
      <AgentCard v-for="agent in store.agents" :key="agent.key" :agent="agent" />
    </div>

    <!-- 实时工具调用摘要 -->
    <div class="tools-summary" v-if="allTools.length > 0">
      <h3>最近工具调用</h3>
      <div class="tool-list">
        <div
          v-for="(tool, idx) in allTools.slice(-8).reverse()"
          :key="idx"
          class="tool-item"
        >
          <span class="tool-agent">{{ getAgentName(tool.agent) }}</span>
          <span class="tool-name">{{ tool.tool }}</span>
          <span v-if="tool.durationMs" class="tool-duration">{{ tool.durationMs }}ms</span>
        </div>
      </div>
    </div>

    <!-- 候选 Finding 列表 -->
    <div class="findings-section" v-if="store.candidates.length > 0">
      <h3>审查发现 ({{ store.acceptedFindings.length }}/{{ store.candidates.length }})</h3>
      <FindingCard
        v-for="entry in store.candidates"
        :key="entry.finding.id"
        :finding="entry.finding"
        :verifier-status="entry.verifierStatus"
        :verifier-reason="entry.verifierReason"
      />
    </div>

    <!-- 完成 / 失败状态 -->
    <div v-if="store.status === 'completed'" class="status-banner success">
      审查已完成！生成 {{ store.acceptedFindings.length }} 个有效发现。
      <router-link :to="{ name: 'result', params: { runId: store.runId } }" class="btn btn-sm">
        查看结果
      </router-link>
    </div>
    <div v-if="store.status === 'failed'" class="status-banner error">
      审查失败: {{ store.error }}
      <router-link to="/" class="btn btn-sm">返回首页</router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useReviewStore } from '../stores/review'
import { connectSSE, replayEvents } from '../api/client'
import StageProgress from '../components/StageProgress.vue'
import AgentCard from '../components/AgentCard.vue'
import FindingCard from '../components/FindingCard.vue'

const route = useRoute()
const store = useReviewStore()

const runId = route.params.runId as string | undefined
const sseError = ref<string | null>(null)

// 响应式当前时间，用于驱动倒计时每秒更新
const now = ref(Date.now())
let timerHandle: ReturnType<typeof setInterval> | null = null
let currentEventSource: EventSource | null = null

function setupConnection(): void {
  if (!runId) {
    sseError.value = '缺少审查 Run ID，请返回首页重新发起审查。'
    return
  }

  // 关闭已有连接
  if (currentEventSource) {
    currentEventSource.close()
    currentEventSource = null
  }

  sseError.value = null
  store.reset()

  const isReplay = route.query.replay === '1'
  const replaySpeed = Number(route.query.speed) || 1

  currentEventSource = isReplay
    ? replayEvents(
        runId,
        replaySpeed,
        (event) => {
          store.applyEvent(event)
        },
        (err) => {
          sseError.value = 'Replay 连接失败，请检查网络或稍后重试。'
          console.error('Replay SSE error:', err)
        },
        () => {
          // SSE 正常完成
        }
      )
    : connectSSE(
        runId,
        (event) => {
          store.applyEvent(event)
        },
        (err) => {
          sseError.value = 'SSE 连接失败，请检查网络或稍后重试。'
          console.error('SSE error:', err)
        },
        () => {
          // SSE 正常完成
        }
      )
}

function retryConnection(): void {
  setupConnection()
}

onMounted(() => {
  // 路由参数空值检查
  if (!runId) {
    sseError.value = '缺少审查 Run ID，请返回首页重新发起审查。'
    return
  }

  store.reset()

  timerHandle = setInterval(() => {
    now.value = Date.now()
  }, 1000)

  setupConnection()
})

let onUnmountedCleanup: () => void = () => {}
onUnmounted(() => {
  onUnmountedCleanup()
  if (currentEventSource) {
    currentEventSource.close()
    currentEventSource = null
  }
  if (timerHandle) {
    clearInterval(timerHandle)
    timerHandle = null
  }
})

// 600 秒倒计时
const remainingSecs = computed(() => {
  if (!store.startTime) return 600
  // 触发 now 的响应式依赖
  void now.value
  const startMs = new Date(store.startTime).getTime()
  const elapsed = (store.endTime ? new Date(store.endTime).getTime() : Date.now()) - startMs
  const remaining = Math.max(0, 600_000 - elapsed)
  return Math.ceil(remaining / 1000)
})

function formatTime(secs: number): string {
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

// 汇总所有工具调用（带 agent 标记）
const allTools = computed(() => {
  const result: Array<{ agent: string; tool: string; durationMs?: number }> = []
  for (const agent of store.agents) {
    for (const t of agent.tools) {
      result.push({ agent: agent.key, tool: t.tool, durationMs: t.durationMs })
    }
  }
  return result
})

function getAgentName(key: string): string {
  const agent = store.agents.find((a) => a.key === key)
  return agent?.name ?? key
}
</script>

<style scoped>
.review-page {
  max-width: 960px;
  margin: 0 auto;
}

.review-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.review-title {
  color: var(--color-text-muted);
  font-size: 14px;
}

.run-id {
  display: block;
  font-size: 12px;
  color: var(--color-text-muted);
  font-family: monospace;
}

.countdown {
  font-size: 20px;
  font-weight: 700;
  font-family: monospace;
  color: var(--color-text);
}

.countdown.warning {
  color: var(--color-warning);
}

.countdown.danger {
  color: var(--color-danger);
  animation: pulse 1s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

@media (max-width: 800px) {
  .agent-grid {
    grid-template-columns: 1fr;
  }
}

.tools-summary {
  background: var(--color-surface);
  border-radius: var(--radius);
  padding: 16px;
  box-shadow: var(--shadow);
  margin-bottom: 24px;
}

.tools-summary h3 {
  font-size: 14px;
  margin-bottom: 12px;
}

.tool-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tool-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  padding: 4px 8px;
  background: var(--color-bg);
  border-radius: 4px;
}

.tool-agent {
  color: var(--color-primary);
  font-weight: 600;
  font-size: 12px;
  padding: 1px 6px;
  background: rgba(59, 130, 246, 0.1);
  border-radius: 3px;
}

.tool-name {
  font-family: monospace;
  font-size: 12px;
}

.tool-duration {
  margin-left: auto;
  color: var(--color-text-muted);
  font-size: 11px;
}

.findings-section h3 {
  font-size: 16px;
  margin-bottom: 12px;
}

.status-banner {
  margin-top: 24px;
  padding: 16px 20px;
  border-radius: var(--radius);
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
}

.status-banner.success {
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}

.status-banner.error {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.error-hint {
  font-size: 12px;
  margin-top: 6px;
  opacity: 0.8;
}

.error-hint code {
  background: rgba(153, 27, 27, 0.08);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
}

.error-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.btn-sm {
  padding: 6px 16px;
  background: var(--color-primary);
  color: #fff;
  border-radius: 4px;
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  border: none;
  cursor: pointer;
}

.btn-sm:focus-visible {
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.4);
}

.btn-secondary {
  background: #e5e7eb;
  color: #374151;
}

.btn-secondary:hover {
  background: #d1d5db;
}

@media (max-width: 640px) {
  .review-header {
    flex-direction: column;
    gap: 12px;
  }

  .countdown {
    font-size: 16px;
  }

  .tool-item {
    flex-wrap: wrap;
  }
}
</style>
