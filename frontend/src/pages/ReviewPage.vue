<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { createEventSubscription, replayEventLog } from '@/api/client'
import AgentTeamGraph from '@/components/AgentTeamGraph.vue'
import BudgetMeter from '@/components/BudgetMeter.vue'
import FindingCard from '@/components/FindingCard.vue'
import StageProgress from '@/components/StageProgress.vue'
import Timeline from '@/components/Timeline.vue'
import demoEvents from '@/fixtures/demo-events.jsonl?raw'
import { useReviewStore } from '@/stores/review'

const route = useRoute()
const store = useReviewStore()
const connection = ref<'connecting' | 'live' | 'reconnecting' | 'replay' | 'closed' | 'error'>('connecting')
const message = ref('正在建立事件连接…')
let subscription: { close(): void } | undefined
const runId = computed(() => String(route.params.runId))
const isDemo = computed(() => route.query.demo === '1')
const accepted = computed(() => store.candidates.filter((item) => item.verdict === 'accepted'))
const rejected = computed(() => store.candidates.filter((item) => item.verdict === 'rejected'))

onMounted(async () => {
  if (store.runId && store.runId !== runId.value) store.reset()
  if (isDemo.value) {
    connection.value = 'replay'
    message.value = '离线 Replay 播放中'
    try {
      await replayEventLog(demoEvents, store.applyEvent, { speed: 1.35 })
      connection.value = 'closed'
      message.value = 'Replay 已完成'
    } catch {
      connection.value = 'error'
      message.value = '演示事件文件无法解析'
    }
    return
  }
  subscription = createEventSubscription(runId.value, {
    onEvent: store.applyEvent,
    onOpen: () => { connection.value = 'live'; message.value = '实时事件已连接' },
    onDisconnect: () => { connection.value = 'reconnecting'; message.value = '连接中断，正在自动恢复…' },
    onError: (detail) => { connection.value = 'error'; message.value = detail },
  }, route.query.replay === '1' ? { replay: true, speed: 2 } : undefined)
})

onBeforeUnmount(() => subscription?.close())
</script>

<template>
  <div class="review-page page-width">
    <section class="run-header">
      <div><span class="eyebrow">RUNNING REVIEW</span><h1>{{ store.title || 'AI 代码审查进行中' }}</h1><p><span>{{ store.repository || runId }}</span><code>{{ runId }}</code></p></div>
      <div class="run-actions"><span class="connection-pill" :class="connection"><i />{{ message }}</span><BudgetMeter :started-at="store.startedAt" :completed-at="store.completedAt" /></div>
    </section>
    <StageProgress :stages="store.stages" />
    <div class="review-layout">
      <div class="review-main">
        <AgentTeamGraph :agents="store.agents" />
        <section class="verdict-board panel">
          <div class="section-heading"><div><span class="eyebrow">VERIFICATION QUEUE</span><h2>候选与裁决</h2></div><div class="verdict-counts"><span class="accepted">{{ accepted.length }} 通过</span><span class="rejected">{{ rejected.length }} 拒绝</span></div></div>
          <div v-if="store.candidates.length" class="candidate-grid">
            <FindingCard v-for="item in store.candidates" :key="item.finding.id" :finding="item.finding" :verdict="item.verdict" :verdict-text="item.verdictReason" />
          </div>
          <div v-else class="scanning-state"><span class="scan-orbit"><i /><i /><i /></span><div><strong>专家正在分析变更</strong><small>候选问题一经发布，会立即进入独立验证队列。</small></div></div>
        </section>
      </div>
      <aside>
        <Timeline :events="store.events" />
        <section class="run-summary panel">
          <span class="eyebrow">RUN SNAPSHOT</span><h2>运行快照</h2>
          <dl><div><dt>公开事件</dt><dd>{{ store.events.length }}</dd></div><div><dt>候选问题</dt><dd>{{ store.candidates.length }}</dd></div><div><dt>最终 Finding</dt><dd>{{ store.findings.length }}</dd></div><div><dt>当前序号</dt><dd>#{{ store.lastSequence }}</dd></div></dl>
          <RouterLink v-if="['completed', 'partial', 'failed'].includes(store.status)" class="primary-button compact-button" :to="{ name: 'result', params: { runId }, query: isDemo ? { demo: '1' } : {} }"><span>查看审查报告</span><b>→</b></RouterLink>
        </section>
      </aside>
    </div>
  </div>
</template>
