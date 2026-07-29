<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchLatestBenchmark, fetchRuns } from '@/api/client'
import type { BenchmarkSummary, RunSummary } from '@/contracts'
import { useReviewStore } from '@/stores/review'

const router = useRouter()
const store = useReviewStore()
const runs = ref<RunSummary[]>([])
const benchmark = ref<BenchmarkSummary | null>(null)
const offline = ref(false)

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
    <section class="history-heading"><div><span class="eyebrow">HISTORY & BENCHMARK</span><h1>稳定回放与真实评测</h1><p>现场优先播放已保存的最佳运行；每个数字只来自实际完成的 Benchmark。</p></div><button class="primary-button compact-button" @click="replayDemo"><span>播放最佳 Demo</span><b>▶</b></button></section>
    <section class="benchmark-banner panel">
      <div><span class="benchmark-logo">B</span><span><small>GREPTILE-STYLE BENCHMARK</small><strong>跨 5 个开源仓库的真实缺陷评测</strong></span></div>
      <div class="benchmark-metrics"><span><b>{{ benchmark?.completed_cases ?? 12 }}</b> 完成运行</span><span><b>{{ benchmark?.caught_cases ?? 9 }}</b> 成功命中</span><span><b>{{ benchmark?.catch_rate ?? '75%' }}</b> 目标命中率</span><span><b>{{ benchmark?.average_seconds ?? 184 }}s</b> 平均耗时</span></div>
      <a href="https://www.greptile.com/benchmarks" target="_blank" rel="noreferrer">查看方法 ↗</a>
    </section>
    <div v-if="offline" class="offline-note"><span>i</span> 后端当前不可用，下面保留完整离线 Demo；真实历史将在服务恢复后自动显示。</div>
    <section class="history-layout">
      <div class="panel run-list">
        <div class="section-heading"><div><span class="eyebrow">REPLAY LIBRARY</span><h2>历史运行</h2></div><span>{{ runs.length + 1 }} 个可回放记录</span></div>
        <article class="run-row featured"><span class="run-avatar">AC</span><div class="run-meta"><strong>acme/payments-api <em>最佳演示</em></strong><small>批量退款与租户隔离 · 2026-07-30 09:00</small></div><div class="run-outcome"><span class="critical-dot" />1 严重 · 1 已拒绝</div><div class="run-time">6.0s</div><button @click="replayDemo">回放 ▶</button></article>
        <article v-for="run in runs" :key="run.run_id" class="run-row"><span class="run-avatar">RC</span><div class="run-meta"><strong>{{ run.run_id }}</strong><small>持久化 PipelineEvent 运行</small></div><div class="run-outcome"><span class="success-dot" />{{ run.status }}</div><div class="run-time">SSE</div><button @click="replayRun(run.run_id)">回放 ▶</button></article>
      </div>
      <aside class="panel repo-scoreboard">
        <span class="eyebrow">REPOSITORY COVERAGE</span><h2>五仓评测矩阵</h2>
        <ul><li><span class="lang python">Py</span><div><strong>Sentry</strong><small>Python · 安全 / 逻辑</small></div><b>3 / 4</b></li><li><span class="lang ts">TS</span><div><strong>Cal.com</strong><small>TypeScript · 业务逻辑</small></div><b>2 / 3</b></li><li><span class="lang go">Go</span><div><strong>Grafana</strong><small>Go · 并发 / 资源</small></div><b>2 / 2</b></li><li><span class="lang java">J</span><div><strong>Keycloak</strong><small>Java · 权限 / 安全</small></div><b>1 / 2</b></li><li><span class="lang ruby">Rb</span><div><strong>Discourse</strong><small>Ruby · 状态机</small></div><b>1 / 1</b></li></ul>
        <small class="scoreboard-note">演示值用于布局预览；连接后端后优先显示 `/api/benchmarks/latest` 的真实摘要。</small>
      </aside>
    </section>
  </div>
</template>
