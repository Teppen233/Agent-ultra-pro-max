<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchLatestBenchmark, fetchRuns } from '@/api/client'
import type { BenchmarkSummary, RunSummary } from '@/contracts'
import { presentBenchmark } from '@/pages/view-models'
import { useReviewStore } from '@/stores/review'

const router = useRouter()
const store = useReviewStore()
const runs = ref<RunSummary[]>([])
const benchmark = ref<BenchmarkSummary | null>(null)
const offline = ref(false)
const benchmarkView = computed(() => presentBenchmark(benchmark.value))

onMounted(async () => {
  const results = await Promise.allSettled([fetchRuns(), fetchLatestBenchmark()])
  if (results[0].status === 'fulfilled') runs.value = results[0].value.runs
  if (results[1].status === 'fulfilled') benchmark.value = results[1].value
  offline.value = results.some((result) => result.status === 'rejected')
})

const replayDemo = async (): Promise<void> => {
  store.reset()
  await router.push({ name: 'review', params: { runId: 'demo-security-20260730' }, query: { demo: '1' } })
}

const replayRun = async (runId: string): Promise<void> => {
  store.reset()
  await router.push({ name: 'review', params: { runId }, query: { replay: '1' } })
}
</script>

<template>
  <div class="history-page page-width">
    <section class="history-heading"><div><span class="eyebrow">历史与评测</span><h1>稳定回放与可追溯评测</h1><p>现场可播放已保存的演示运行；评测区严格区分真实结果、离线观察值与缺失数据。</p></div><button class="primary-button compact-button" @click="replayDemo"><span>播放离线演示</span><b>▶</b></button></section>
    <section class="benchmark-banner panel" :class="benchmarkView.kind">
      <div><span class="benchmark-logo">B</span><span><small>GREPTILE 风格评测</small><strong>{{ benchmarkView.title }}</strong></span></div>
      <div class="benchmark-metrics"><span><b>{{ benchmarkView.completed }}</b> 完成运行</span><span><b>{{ benchmarkView.caught }}</b> 成功命中</span><span><b>{{ benchmarkView.rate }}</b> {{ benchmarkView.rateLabel }}</span><span><b>{{ benchmarkView.elapsed }}</b> 总耗时</span></div>
      <a href="https://www.greptile.com/benchmarks" target="_blank" rel="noreferrer">查看评测方法 ↗</a>
      <p class="benchmark-note">{{ benchmarkView.note }}</p>
    </section>
    <div v-if="offline" class="offline-note" role="status"><span>i</span> 后端当前不可用。评测数字显示“暂无数据”，离线演示仍可正常播放。</div>
    <section class="history-layout">
      <div class="panel run-list">
        <div class="section-heading"><div><span class="eyebrow">回放记录</span><h2>历史运行</h2></div><span>{{ runs.length + 1 }} 个可回放记录</span></div>
        <article class="run-row featured"><span class="run-avatar">演</span><div class="run-meta"><strong>acme/payments-api <em>离线演示数据</em></strong><small>批量退款与租户隔离 · 内置公开事件 fixture</small></div><div class="run-outcome"><span class="critical-dot" />1 严重 · 1 已拒绝</div><div class="run-time">演示 6.0s</div><button @click="replayDemo">回放 ▶</button></article>
        <article v-for="run in runs" :key="run.run_id" class="run-row"><span class="run-avatar">审</span><div class="run-meta"><strong>{{ run.run_id }}</strong><small>持久化公开事件运行</small></div><div class="run-outcome"><span class="success-dot" />{{ run.status }}</div><div class="run-time">服务端回放</div><button @click="replayRun(run.run_id)">回放 ▶</button></article>
      </div>
      <aside class="panel repo-scoreboard">
        <span class="eyebrow">仓库覆盖</span><h2>五仓评测范围</h2>
        <ul><li><span class="lang python">Py</span><div><strong>Sentry</strong><small>Python · 安全 / 逻辑</small></div><b>暂无逐仓数据</b></li><li><span class="lang ts">TS</span><div><strong>Cal.com</strong><small>TypeScript · 业务逻辑</small></div><b>暂无逐仓数据</b></li><li><span class="lang go">Go</span><div><strong>Grafana</strong><small>Go · 并发 / 资源</small></div><b>暂无逐仓数据</b></li><li><span class="lang java">J</span><div><strong>Keycloak</strong><small>Java · 权限 / 安全</small></div><b>暂无逐仓数据</b></li><li><span class="lang ruby">Rb</span><div><strong>Discourse</strong><small>Ruby · 状态机</small></div><b>暂无逐仓数据</b></li></ul>
        <small class="scoreboard-note">当前摘要契约不包含逐仓成绩，因此不展示推测数字。</small>
      </aside>
    </section>
  </div>
</template>
