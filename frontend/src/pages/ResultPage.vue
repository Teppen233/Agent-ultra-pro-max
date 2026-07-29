<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { pollReviewResult, reportUrl } from '@/api/client'
import FindingCard from '@/components/FindingCard.vue'
import type { ReviewResult } from '@/contracts'
import { presentResultMetrics, presentResultStatus, shouldFetchFinalResult } from '@/pages/view-models'
import { useReviewStore } from '@/stores/review'

const route = useRoute()
const store = useReviewStore()
const severity = ref('all')
const category = ref('all')
const error = ref('')
const loadState = ref<'loading' | 'pending' | 'ready' | 'failed' | 'error'>('loading')
const pendingText = ref('正在获取最终审查报告…')
const controller = new AbortController()
const runId = computed(() => String(route.params.runId))
const isDemo = computed(() => route.query.demo === '1')
const findings = computed(() => store.findings.filter((finding) =>
  (severity.value === 'all' || finding.severity === severity.value)
  && (category.value === 'all' || finding.category === category.value),
))
const criticalCount = computed(() => store.findings.filter((finding) => finding.severity === 'critical').length)
const rejectedCount = computed(() => isDemo.value
  ? store.candidates.filter((item) => item.verdict === 'rejected').length
  : store.rejectedCount)
const terminalStatus = computed<ReviewResult['status']>(() => {
  if (store.status === 'partial' || store.status === 'failed') return store.status
  return 'completed'
})
const statusView = computed(() => presentResultStatus(terminalStatus.value, isDemo.value))
const metrics = computed(() => presentResultMetrics({
  isDemo: isDemo.value,
  resultHydrated: store.resultHydrated,
  coverage: store.coverage,
  elapsedSeconds: store.elapsedSeconds,
  demo: {
    coverage: ['src/refunds/service.ts', 'src/jobs/refund-worker.ts', 'tests/refunds.test.ts'],
    elapsedSeconds: 6,
  },
}))

onMounted(async () => {
  if (isDemo.value) {
    loadState.value = 'ready'
    return
  }
  if (store.runId && store.runId !== runId.value) store.reset()
  if (!shouldFetchFinalResult({ isDemo: false, resultHydrated: store.resultHydrated })) {
    loadState.value = 'ready'
    return
  }
  try {
    const response = await pollReviewResult(runId.value, {
      signal: controller.signal,
      onPending: (pending) => {
        loadState.value = 'pending'
        pendingText.value = `审查仍在运行（${pending.status}），正在等待最终报告…`
      },
    })
    if (response.kind === 'result') {
      store.hydrateResult(response.result)
      loadState.value = 'ready'
    } else if (response.kind === 'failed') {
      loadState.value = 'failed'
    }
  } catch (cause) {
    if (controller.signal.aborted) return
    loadState.value = 'error'
    error.value = cause instanceof Error ? cause.message : '无法获取审查报告。'
  }
})

onBeforeUnmount(() => controller.abort())
</script>

<template>
  <div class="result-page page-width">
    <section v-if="loadState !== 'ready'" class="result-loading panel" role="status" aria-live="polite">
      <span class="scan-orbit"><i /><i /><i /></span>
      <div v-if="loadState === 'loading' || loadState === 'pending'"><span class="eyebrow">最终报告</span><h1>{{ pendingText }}</h1><p>运行中状态不会被当作完整报告，页面会在终态结果生成后自动更新。</p></div>
      <div v-else-if="loadState === 'failed'"><span class="eyebrow">审查失败</span><h1>审查已失败，未生成完整报告</h1><p>服务端仅返回失败状态，没有可安全展示的完整结果。</p></div>
      <div v-else><span class="eyebrow">报告获取失败</span><h1>暂时无法加载最终报告</h1><p class="form-error">{{ error }}</p></div>
    </section>

    <template v-else>
      <section class="result-hero panel" :class="statusView.tone">
        <div class="result-icon" :class="statusView.tone"><svg viewBox="0 0 24 24"><template v-if="statusView.tone === 'success'"><path d="m5 12 4 4L19 6" /><circle cx="12" cy="12" r="10" /></template><path v-else-if="statusView.tone === 'warning'" d="M12 3 2 21h20L12 3Zm0 6v5m0 3h.01" /><template v-else><path d="m8 8 8 8m0-8-8 8" /><circle cx="12" cy="12" r="10" /></template></svg></div>
        <div><span class="eyebrow">{{ statusView.eyebrow }}</span><h1>{{ statusView.summaryLead }} <em>{{ store.findings.length }}</em> {{ statusView.summaryUnit }}</h1><p>{{ store.repository || runId }} · {{ statusView.rejectedPrefix }} {{ rejectedCount }} 个拒绝候选 <b v-if="metrics.demoLabel">· {{ metrics.demoLabel }}</b></p></div>
        <div class="result-actions"><a v-if="!isDemo" class="secondary-button" :href="reportUrl(runId)" target="_blank">查看 Markdown</a><RouterLink class="primary-button compact-button" to="/"><span>新建审查</span><b>＋</b></RouterLink></div>
      </section>
      <section class="metric-grid">
        <article><small>最终问题</small><strong>{{ store.findings.length }}</strong><span>{{ statusView.findingNote }}</span></article>
        <article class="danger"><small>严重问题</small><strong>{{ criticalCount }}</strong><span>建议立即修复</span></article>
        <article><small>覆盖文件</small><strong>{{ metrics.coverageCount }}</strong><span>Diff 相关范围</span></article>
        <article><small>运行耗时</small><strong>{{ metrics.elapsed }}</strong><span>{{ statusView.elapsedNote }}</span></article>
      </section>
      <section class="report-layout">
        <div>
          <div class="report-toolbar panel"><div><span class="eyebrow">{{ statusView.listEyebrow }}</span><h2>问题明细</h2></div><div class="filters"><select v-model="severity" aria-label="严重度筛选"><option value="all">全部严重度</option><option value="critical">严重</option><option value="high">高危</option><option value="medium">中危</option><option value="low">低危</option></select><select v-model="category" aria-label="类别筛选"><option value="all">全部类别</option><option value="security">安全</option><option value="logic">逻辑</option><option value="reliability">可靠性</option></select></div></div>
          <div class="report-findings"><FindingCard v-for="finding in findings" :key="finding.id" :finding="finding" :verdict="statusView.findingVerdict" :verdict-text="statusView.findingVerdictText" /><p v-if="!findings.length" class="empty-state panel">当前筛选条件下没有问题。</p></div>
        </div>
        <aside>
          <section class="coverage-card panel"><span class="eyebrow">审查覆盖</span><h2>已检查文件</h2><div class="coverage-ring"><strong>{{ metrics.coverageCount }}</strong><small>个文件</small></div><ul v-if="metrics.coverage.length"><li v-for="file in metrics.coverage" :key="file"><span>{{ file }}</span><b>已检查</b></li></ul><p v-else class="empty-state">暂无覆盖文件数据。</p></section>
          <section class="safety-card panel"><span>✓</span><div><strong>隐私边界已启用</strong><small>报告不包含 Prompt、模型原始响应或隐藏推理。</small></div></section>
        </aside>
      </section>
    </template>
  </div>
</template>
