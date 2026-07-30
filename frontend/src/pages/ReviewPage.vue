<script lang="ts">
/** 保持 Demo 与历史服务端回放的报告往返上下文，避免误入 live SSE。 */
export const presentReviewResultLink = (runId: string, isServerReplay: boolean, isDemo: boolean) => ({
  name: 'result',
  params: { runId },
  query: isDemo ? { demo: '1' } : isServerReplay ? { replay: '1' } : {},
})
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { createReplayController, createReplayElapsedClock, parseEventLog } from '@/api/client'
import AgentOperationsGraph from '@/components/AgentOperationsGraph.vue'
import BudgetMeter from '@/components/BudgetMeter.vue'
import FindingCard from '@/components/FindingCard.vue'
import OperationFeed from '@/components/OperationFeed.vue'
import ReplayControls from '@/components/ReplayControls.vue'
import StageProgress from '@/components/StageProgress.vue'
import Timeline from '@/components/Timeline.vue'
import demoEvents from '@/fixtures/demo-events.jsonl?raw'
import { createIsolatedReviewStore, useReviewStore } from '@/stores/review'
import { createServerReplaySubscription, useRunsStore } from '@/stores/runs'

const route = useRoute()
const runId = computed(() => String(route.params.runId))
const isDemo = computed(() => route.query.demo === '1')
const isServerReplay = computed(() => route.query.replay === '1')
const isPlayback = computed(() => isDemo.value || isServerReplay.value)
const liveStore = useReviewStore()
const playbackStore = createIsolatedReviewStore()
const store = computed(() => isPlayback.value ? playbackStore : liveStore)
const runs = useRunsStore()
const playbackConnection = ref<'connecting' | 'replay' | 'reconnecting' | 'closed' | 'error'>('connecting')
const playbackMessage = ref('正在建立回放连接…')
const replaySpeed = ref(1)
const replayPaused = ref(false)
const skipIdle = ref(false)
const replayClock = ref(Date.now())
const replayElapsedClock = createReplayElapsedClock()
const demoReplayEvents = parseEventLog(demoEvents)
const originalReplayElapsedMs = computed(() => {
  const events = isDemo.value ? demoReplayEvents : playbackStore.events
  if (events.length < 2) return 0
  return Math.max(0, Date.parse(events[events.length - 1]!.timestamp) - Date.parse(events[0]!.timestamp))
})
const replayElapsedMs = computed(() => {
  replayClock.value
  return replayElapsedClock.value()
})
let serverReplaySubscription: { close(): void } | undefined
let localReplayController: ReturnType<typeof createReplayController> | undefined
let replayTimer: number | undefined

const startReplayTimer = (): void => {
  if (replayTimer !== undefined) return
  replayTimer = window.setInterval(() => { replayClock.value = Date.now() }, 100)
}

const stopReplayTimer = (): void => {
  if (replayTimer === undefined) return
  window.clearInterval(replayTimer)
  replayTimer = undefined
}

/** 启动或重新开始离线回放，保持其状态与真实 SSE 隔离。 */
const startDemoReplay = (): void => {
  localReplayController?.dispose()
  playbackStore.reset()
  replayPaused.value = false
  replayElapsedClock.start()
  startReplayTimer()
  playbackConnection.value = 'replay'
  playbackMessage.value = '离线回放播放中'
  const controller = createReplayController(demoReplayEvents, playbackStore.applyEvent)
  controller.setSpeed(replaySpeed.value)
  controller.skipIdle = skipIdle.value
  localReplayController = controller
  controller.play()
  void controller.finished.then(() => {
    if (localReplayController !== controller) return
    replayElapsedClock.finish()
    stopReplayTimer()
    playbackConnection.value = 'closed'
    playbackMessage.value = '离线回放已完成'
  })
}

const updateReplaySpeed = (speed: number): void => {
  replaySpeed.value = speed
  localReplayController?.setSpeed(speed)
}

const updateReplayPaused = (paused: boolean): void => {
  replayPaused.value = paused
  if (paused) {
    localReplayController?.pause()
    replayElapsedClock.pause()
    stopReplayTimer()
  } else {
    localReplayController?.play()
    replayElapsedClock.resume()
    startReplayTimer()
  }
}

const updateSkipIdle = (enabled: boolean): void => {
  skipIdle.value = enabled
  if (localReplayController) localReplayController.skipIdle = enabled
}
const connection = computed(() => isPlayback.value ? playbackConnection.value : runs.connection)
const message = computed(() => isPlayback.value ? playbackMessage.value : runs.connectionMessage)
const accepted = computed(() => store.value.candidates.filter((item) => item.verdict === 'accepted'))
const rejected = computed(() => store.value.candidates.filter((item) => item.verdict === 'rejected'))

onMounted(async () => {
  if (isDemo.value) {
    startDemoReplay()
    return
  }
  if (isServerReplay.value) {
    playbackStore.reset()
    serverReplaySubscription = createServerReplaySubscription(runId.value, {
      onEvent: playbackStore.applyEvent,
      onOpen: () => {
        playbackConnection.value = 'replay'
        playbackMessage.value = '历史回放已连接（2 倍速）'
      },
      onDisconnect: () => {
        playbackConnection.value = 'reconnecting'
        playbackMessage.value = '回放连接中断，正在自动恢复…'
      },
      onError: (detail) => {
        playbackConnection.value = 'error'
        playbackMessage.value = detail
      },
      onClosed: (type) => {
        playbackConnection.value = 'closed'
        playbackMessage.value = type === 'review.failed' ? '历史运行失败，回放已关闭' : '历史回放已完成'
      },
    })
    return
  }
  if (liveStore.runId && liveStore.runId !== runId.value) liveStore.reset()
  runs.startSubscription(runId.value)
})

onBeforeUnmount(() => {
  localReplayController?.dispose()
  replayElapsedClock.finish()
  stopReplayTimer()
  serverReplaySubscription?.close()
})
</script>

<template>
  <div class="review-page page-width">
    <section class="run-header">
      <div><span class="eyebrow">审查运行中</span><h1>{{ store.title || 'AI 代码审查进行中' }}</h1><p><span>{{ store.repository || runId }}</span><code>{{ runId }}</code></p></div>
      <div class="run-actions"><span class="connection-pill" :class="connection" role="status" aria-live="polite"><i />{{ message }}</span><BudgetMeter :started-at="store.startedAt" :completed-at="store.completedAt" /></div>
    </section>
    <ReplayControls
      v-if="isDemo"
      :speed="replaySpeed"
      :paused="replayPaused"
      :skip-idle="skipIdle"
      :original-elapsed-ms="originalReplayElapsedMs"
      :replay-elapsed-ms="replayElapsedMs"
      @update:speed="updateReplaySpeed"
      @update:paused="updateReplayPaused"
      @update:skip-idle="updateSkipIdle"
      @restart="startDemoReplay"
    />
    <StageProgress :stages="store.stages" />
    <div class="review-layout">
      <div class="review-main">
        <AgentOperationsGraph
          :instances="store.agentInstances"
          :plan-summary="store.planSummary"
          :candidate-count="store.candidates.length"
          :verdict-count="accepted.length + rejected.length"
          :verifier-status="store.agents.verifier.status"
        />
        <OperationFeed :operations="store.operations" />
        <section class="verdict-board panel">
          <div class="section-heading"><div><span class="eyebrow">验证队列</span><h2>候选与裁决</h2></div><div class="verdict-counts"><span class="accepted">{{ accepted.length }} 通过</span><span class="rejected">{{ rejected.length }} 拒绝</span></div></div>
          <div v-if="store.candidates.length" class="candidate-grid">
            <FindingCard v-for="item in store.candidates" :key="item.finding.id" :finding="item.finding" :verdict="item.verdict" :verdict-text="item.verdictReason" />
          </div>
          <div v-else class="scanning-state"><span class="scan-orbit"><i /><i /><i /></span><div><strong>专家正在分析变更</strong><small>候选问题一经发布，会立即进入独立验证队列。</small></div></div>
        </section>
      </div>
      <aside>
        <Timeline :events="store.events" />
        <section class="run-summary panel">
          <span class="eyebrow">运行快照</span><h2>公开状态摘要</h2>
          <dl><div><dt>公开事件</dt><dd>{{ store.events.length }}</dd></div><div><dt>候选问题</dt><dd>{{ store.candidates.length }}</dd></div><div><dt>最终 Finding</dt><dd>{{ store.findings.length }}</dd></div><div><dt>当前序号</dt><dd>#{{ store.lastSequence }}</dd></div></dl>
          <RouterLink v-if="['completed', 'partial', 'failed'].includes(store.status)" class="primary-button compact-button" :to="presentReviewResultLink(runId, isServerReplay, isDemo)"><span>查看审查报告</span><b>→</b></RouterLink>
        </section>
      </aside>
    </div>
  </div>
</template>
