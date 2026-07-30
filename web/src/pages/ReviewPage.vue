<template>
  <div class="review-page">
    <!-- 头部 -->
    <div class="review-header">
      <div class="header-left">
        <h2>审查管线</h2>
        <span v-if="store.reviewTitle" class="review-title">{{ store.reviewTitle }}</span>
        <span class="run-id">Run: {{ store.runId }}</span>
      </div>
      <div class="header-right">
        <div class="countdown" :class="{ warning: remainingSecs < 60, danger: remainingSecs < 30 }">
          {{ store.status === 'completed' ? formatTime(0) : formatTime(remainingSecs) }}
        </div>
      </div>
    </div>

    <!-- SSE 连接错误 -->
    <div v-if="sseError" class="status-banner error">
      <div>
        <p><strong>{{ sseError }}</strong></p>
        <p class="error-hint">请确认后端服务已启动：<code>uvicorn reviewcrew.server.app:app --reload</code></p>
      </div>
      <div class="error-actions">
        <button class="btn btn-sm" @click="retryConnection">重试</button>
        <router-link to="/" class="btn btn-sm btn-secondary">返回首页</router-link>
      </div>
    </div>

    <!-- 管线图谱 -->
    <PipelineGraph
      v-if="store.stages.length"
      :stages="store.stages"
      :agents="store.agents"
      :findings="store.candidates"
      @select-agent="openDetail"
    />

    <!-- 完成 / 失败 -->
    <div v-if="store.status === 'completed'" class="status-banner success">
      ✅ 审查完成 — {{ store.acceptedFindings.length }} 个确认发现
      <router-link :to="{ name: 'result', params: { runId: store.runId } }" class="btn btn-sm">查看详情</router-link>
    </div>
    <div v-if="store.status === 'failed'" class="status-banner error">
      ❌ 审查失败: {{ store.error }}
      <router-link to="/" class="btn btn-sm">返回首页</router-link>
    </div>

    <!-- 详情面板 -->
    <DetailPanel
      :visible="panelVisible"
      :title="panelTitle"
      :findings="panelFindings"
      @close="panelVisible = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useReviewStore } from '../stores/review'
import { connectSSE, replayEvents } from '../api/client'
import PipelineGraph from '../components/PipelineGraph.vue'
import DetailPanel from '../components/DetailPanel.vue'

const route = useRoute()
const store = useReviewStore()

const runId = route.params.runId as string | undefined
const sseError = ref<string | null>(null)

// 详情面板
const panelVisible = ref(false)
const panelTitle = ref('')
const panelFindings = ref<Array<{ finding: any; verifierStatus: 'pending' | 'accepted' | 'rejected'; verifierReason?: string }>>([])

function openDetail(node: { id: string; type: string; label: string }) {
  panelTitle.value = node.label
  if (node.id === 'defect') {
    panelFindings.value = store.candidates.filter(c => c.finding.producer === 'defect')
  } else if (node.id === 'intent') {
    panelFindings.value = store.candidates.filter(c => c.finding.producer === 'intent')
  } else {
    panelFindings.value = store.candidates
  }
  panelVisible.value = true
}

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

</script>

<style scoped>
.review-page { max-width: 960px; margin: 0 auto; }

.review-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 24px;
}

.review-title { color: var(--color-text-muted); font-size: 14px; }
.run-id { display: block; font-size: 12px; color: var(--color-text-muted); font-family: monospace; }

.countdown { font-size: 20px; font-weight: 700; font-family: monospace; color: var(--color-text); }
.countdown.warning { color: var(--color-warning); }
.countdown.danger { color: var(--color-danger); animation: pulse 1s ease-in-out infinite; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-banner {
  margin-top: 24px; padding: 16px 20px; border-radius: var(--radius);
  display: flex; align-items: center; gap: 12px; font-size: 14px; flex-wrap: wrap;
}
.status-banner.success { background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }
.status-banner.error { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }

.error-hint { font-size: 12px; margin-top: 6px; opacity: 0.8; }
.error-hint code { background: rgba(153,27,27,0.08); padding: 1px 6px; border-radius: 3px; font-size: 11px; }
.error-actions { display: flex; gap: 8px; flex-shrink: 0; }

.btn-sm {
  padding: 6px 16px; background: var(--color-primary); color: #fff;
  border-radius: 4px; text-decoration: none; font-size: 13px;
  font-weight: 500; white-space: nowrap; border: none; cursor: pointer;
}
.btn-secondary { background: #e5e7eb; color: #374151; }

@media (max-width: 640px) {
  .review-header { flex-direction: column; gap: 12px; }
  .countdown { font-size: 16px; }
}
</style>
