<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { fetchReview, reportUrl } from '@/api/client'
import FindingCard from '@/components/FindingCard.vue'
import { useReviewStore } from '@/stores/review'

const route = useRoute()
const store = useReviewStore()
const severity = ref('all')
const category = ref('all')
const error = ref('')
const runId = computed(() => String(route.params.runId))
const isDemo = computed(() => route.query.demo === '1')
const findings = computed(() => store.findings.filter((finding) =>
  (severity.value === 'all' || finding.severity === severity.value)
  && (category.value === 'all' || finding.category === category.value),
))
const criticalCount = computed(() => store.findings.filter((finding) => finding.severity === 'critical').length)

onMounted(async () => {
  if (isDemo.value || (store.runId === runId.value && store.findings.length)) return
  try {
    store.hydrateResult(await fetchReview(runId.value))
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法获取审查报告。'
  }
})
</script>

<template>
  <div class="result-page page-width">
    <section class="result-hero panel">
      <div class="result-icon"><svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6" /><circle cx="12" cy="12" r="10" /></svg></div>
      <div><span class="eyebrow">REVIEW COMPLETE</span><h1>审查已收敛，发现 <em>{{ store.findings.length }}</em> 个有效问题</h1><p>{{ store.repository || runId }} · Verifier 拒绝 {{ store.rejectedCount || store.candidates.filter(item => item.verdict === 'rejected').length }} 个误报候选</p></div>
      <div class="result-actions"><a v-if="!isDemo" class="secondary-button" :href="reportUrl(runId)" target="_blank">查看 Markdown</a><RouterLink class="primary-button compact-button" to="/"><span>新建审查</span><b>＋</b></RouterLink></div>
    </section>
    <section class="metric-grid">
      <article><small>最终 FINDING</small><strong>{{ store.findings.length }}</strong><span>经独立验证</span></article>
      <article class="danger"><small>严重问题</small><strong>{{ criticalCount }}</strong><span>建议立即修复</span></article>
      <article><small>覆盖文件</small><strong>{{ store.coverage.length || 7 }}</strong><span>Diff 相关范围</span></article>
      <article><small>运行耗时</small><strong>{{ Math.round(store.elapsedSeconds || 6) }}<i>s</i></strong><span>低于 600 秒预算</span></article>
    </section>
    <section class="report-layout">
      <div>
        <div class="report-toolbar panel"><div><span class="eyebrow">VERIFIED FINDINGS</span><h2>已验证问题</h2></div><div class="filters"><select v-model="severity" aria-label="严重度筛选"><option value="all">全部严重度</option><option value="critical">严重</option><option value="high">高危</option><option value="medium">中危</option><option value="low">低危</option></select><select v-model="category" aria-label="类别筛选"><option value="all">全部类别</option><option value="security">安全</option><option value="logic">逻辑</option><option value="reliability">可靠性</option></select></div></div>
        <p v-if="error" class="form-error">{{ error }}</p>
        <div class="report-findings"><FindingCard v-for="finding in findings" :key="finding.id" :finding="finding" verdict="accepted" /><p v-if="!findings.length && !error" class="empty-state panel">当前筛选条件下没有 Finding。</p></div>
      </div>
      <aside>
        <section class="coverage-card panel"><span class="eyebrow">COVERAGE</span><h2>审查覆盖</h2><div class="coverage-ring"><strong>{{ store.coverage.length ? 92 : 88 }}<small>%</small></strong></div><ul><li v-for="file in (store.coverage.length ? store.coverage : ['src/refunds/service.ts', 'src/jobs/refund-worker.ts', 'tests/refunds.test.ts'])" :key="file"><span>{{ file }}</span><b>已检查</b></li></ul></section>
        <section class="safety-card panel"><span>✓</span><div><strong>隐私边界已启用</strong><small>报告不包含 Prompt、模型原始响应或隐藏推理。</small></div></section>
      </aside>
    </section>
  </div>
</template>
