<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { replayEventLog } from '@/api/client'
import AgentTeamGraph from '@/components/AgentTeamGraph.vue'
import BudgetMeter from '@/components/BudgetMeter.vue'
import FindingCard from '@/components/FindingCard.vue'
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
const replayController = new AbortController()
let serverReplaySubscription: { close(): void } | undefined
let currentReplayToken = ''
const connection = computed(() => isPlayback.value ? playbackConnection.value : runs.connection)
const message = computed(() => isPlayback.value ? playbackMessage.value : runs.connectionMessage)
const accepted = computed(() => store.value.candidates.filter((item) => item.verdict === 'accepted'))
const rejected = computed(() => store.value.candidates.filter((item) => item.verdict === 'rejected'))

onMounted(async () => {
  if (isDemo.value) {
    playbackStore.reset()
    const replayToken = `${runId.value}:${Date.now()}`
    currentReplayToken = replayToken
    playbackConnection.value = 'replay'
    playbackMessage.value = '离线回放播放中'
    try {
      await replayEventLog(demoEvents, playbackStore.applyEvent, {
        speed: 1.35,
        signal: replayController.signal,
        runToken: replayToken,
        isCurrent: (token) => token === currentReplayToken,
      })
      if (replayController.signal.aborted) return
      playbackConnection.value = 'closed'
      playbackMessage.value = '离线回放已完成'
    } catch {
      if (replayController.signal.aborted) return
      playbackConnection.value = 'error'
      playbackMessage.value = '演示事件文件无法解析'
    }
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
  currentReplayToken = ''
  replayController.abort()
  serverReplaySubscription?.close()
})
</script>

<template>
  <div class="review-page page-width">
    <section class="run-header">
      <div><span class="eyebrow">审查运行中</span><h1>{{ store.title || 'AI 代码审查进行中' }}</h1><p><span>{{ store.repository || runId }}</span><code>{{ runId }}</code></p></div>
      <div class="run-actions"><span class="connection-pill" :class="connection" role="status" aria-live="polite"><i />{{ message }}</span><BudgetMeter :started-at="store.startedAt" :completed-at="store.completedAt" /></div>
    </section>
    <StageProgress :stages="store.stages" />
    <div class="review-layout">
      <div class="review-main">
        <AgentTeamGraph :agents="store.agents" />
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
          <RouterLink v-if="['completed', 'partial', 'failed'].includes(store.status)" class="primary-button compact-button" :to="{ name: 'result', params: { runId }, query: isDemo ? { demo: '1' } : {} }"><span>查看审查报告</span><b>→</b></RouterLink>
        </section>
      </aside>
    </div>
  </div>
</template>
