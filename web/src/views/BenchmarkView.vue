<script setup lang="ts">
import { BarChart3, CheckCircle2, Clock3, Crosshair } from 'lucide-vue-next'
import { NDataTable, NEmpty, NSkeleton, NTag, useMessage, type DataTableColumns } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import type { EChartsOption } from 'echarts'

import type { BenchmarkRow, Category } from '@/types'
import { uiTokens } from '@/theme'

use([CanvasRenderer, HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent])

interface BenchmarkPayload {
  available: boolean
  summary: string | null
  results: BenchmarkRow[]
}

const loading = ref(true)
const rows = ref<BenchmarkRow[]>([])
const available = ref(false)
const message = useMessage()

const demoRows: BenchmarkRow[] = [
  { repo: 'django/django', pr_url: '#18421', category: 'security', hit: true, reason: 'line_overlap', finding_count: 3, elapsed_seconds: 341 },
  { repo: 'gin-gonic/gin', pr_url: '#3912', category: 'logic', hit: true, reason: 'semantic_match', finding_count: 4, elapsed_seconds: 288 },
  { repo: 'denoland/deno', pr_url: '#24680', category: 'memory', hit: false, reason: 'miss', finding_count: 2, elapsed_seconds: 407 },
  { repo: 'tokio-rs/tokio', pr_url: '#7124', category: 'architecture', hit: true, reason: 'line_overlap', finding_count: 5, elapsed_seconds: 372 },
  { repo: 'spring-projects/spring', pr_url: '#32990', category: 'static', hit: true, reason: 'line_overlap', finding_count: 2, elapsed_seconds: 315 },
]

const displayRows = computed(() => (rows.value.length ? rows.value : demoRows))
const hitRate = computed(() => displayRows.value.filter((row) => row.hit).length / displayRows.value.length)
const averageFindings = computed(() => displayRows.value.reduce((sum, row) => sum + row.finding_count, 0) / displayRows.value.length)
const averageMinutes = computed(() => displayRows.value.reduce((sum, row) => sum + row.elapsed_seconds, 0) / displayRows.value.length / 60)

const categories: Category[] = ['security', 'logic', 'memory', 'architecture', 'static']
const categoryLabels: Record<Category, string> = {
  security: '安全',
  logic: '逻辑',
  memory: '内存',
  architecture: '架构',
  static: '静态检查',
}
const repositories = computed(() => [...new Set(displayRows.value.map((row) => row.repo))])
const chartOption = computed<EChartsOption>(() => ({
  backgroundColor: 'transparent',
  tooltip: { position: 'top' },
  grid: { top: 18, left: 125, right: 30, bottom: 42 },
  xAxis: { type: 'category', data: categories.map((category) => categoryLabels[category]), axisLabel: { color: uiTokens.muted }, axisLine: { lineStyle: { color: uiTokens.border } } },
  yAxis: { type: 'category', data: repositories.value, axisLabel: { color: uiTokens.muted, width: 110, overflow: 'truncate' }, axisLine: { lineStyle: { color: uiTokens.border } } },
  visualMap: { show: false, min: 0, max: 1, inRange: { color: [uiTokens.surfaceRaised, uiTokens.green] } },
  series: [{
    type: 'heatmap',
    data: displayRows.value.map((row) => [categories.indexOf(row.category), repositories.value.indexOf(row.repo), row.hit ? 1 : 0]),
    label: { show: true, color: uiTokens.text, formatter: '{@[2]}' },
    itemStyle: { borderColor: uiTokens.bg, borderWidth: 3, borderRadius: 3 },
  }],
}))

const columns: DataTableColumns<BenchmarkRow> = [
  { title: '仓库', key: 'repo', ellipsis: { tooltip: true } },
  { title: 'PR', key: 'pr_url', width: 120 },
  { title: '缺陷类型', key: 'category', width: 120, render: (row) => categoryLabels[row.category] },
  { title: '结果', key: 'hit', width: 90, render: (row) => h(NTag, { type: row.hit ? 'success' : 'error', bordered: false, size: 'small' }, { default: () => row.hit ? '命中' : '未命中' }) },
  { title: '问题数', key: 'finding_count', width: 90 },
  { title: '耗时', key: 'elapsed_seconds', width: 100, render: (row) => `${(row.elapsed_seconds / 60).toFixed(1)} 分钟` },
]

onMounted(async () => {
  try {
    const response = await fetch('/api/benchmark/latest')
    if (!response.ok) throw new Error('评测接口暂不可用')
    const payload = (await response.json()) as BenchmarkPayload
    available.value = payload.available
    rows.value = payload.results
  } catch (error: unknown) {
    message.error(error instanceof Error ? error.message : 'Benchmark 加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="benchmark-page">
    <header class="benchmark-header">
      <span><BarChart3 :size="15" /> Greptile 评测</span>
      <div>
        <h1>评测仪表盘</h1><NTag v-if="!available" size="small" :bordered="false">
          演示数据
        </NTag>
      </div>
    </header>
    <section class="metric-band">
      <article><CheckCircle2 :size="18" /><span>目标漏洞命中率</span><strong>{{ (hitRate * 100).toFixed(0) }}%</strong><small>目标 ≥ 60%</small></article>
      <article><Crosshair :size="18" /><span>平均问题数</span><strong>{{ averageFindings.toFixed(1) }}</strong><small>目标 ≤ 8</small></article>
      <article><Clock3 :size="18" /><span>平均耗时</span><strong>{{ averageMinutes.toFixed(1) }} 分钟</strong><small>目标 ≤ 8 分钟</small></article>
    </section>
    <section class="benchmark-grid">
      <div class="chart-panel">
        <header><h2>仓库 × 缺陷类型</h2><span>命中矩阵</span></header>
        <NSkeleton v-if="loading" height="22rem" :sharp="true" />
        <VChart v-else class="heatmap" :option="chartOption" autoresize />
      </div>
      <div class="table-panel">
        <header><h2>PR 评测明细</h2><span>{{ displayRows.length }} 个案例</span></header>
        <NSkeleton v-if="loading" height="18rem" :sharp="true" />
        <NDataTable v-else-if="displayRows.length" :columns="columns" :data="displayRows" :bordered="false" :single-line="false" :scroll-x="720" />
        <NEmpty v-else description="运行 benchmark harness 后将在此展示结果" />
      </div>
    </section>
  </div>
</template>

<style scoped>
.benchmark-page {
  height: calc(100vh - var(--app-bar-height));
  overflow-y: auto;
}

.benchmark-header {
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  margin: 0;
  padding: var(--space-4) var(--space-6);
}

.benchmark-header > span {
  align-items: center;
  color: var(--color-cyan);
  display: flex;
  font-family: var(--font-mono);
  font-size: 0.68rem;
  gap: var(--space-2);
  text-transform: uppercase;
}

.benchmark-header div {
  align-items: center;
  display: flex;
  gap: var(--space-3);
}

.benchmark-header h1 {
  font-size: 1.5rem;
  margin: var(--space-1) 0 0;
}

.metric-band {
  border-bottom: 1px solid var(--color-border);
  border-top: 1px solid var(--color-border);
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin: 0;
  padding: 0 var(--space-6);
}

.metric-band article {
  display: grid;
  gap: var(--space-1);
  grid-template-columns: auto 1fr;
  min-height: 7.5rem;
  padding: var(--space-5) var(--space-6);
}

.metric-band article + article {
  border-left: 1px solid var(--color-border);
}

.metric-band svg {
  color: var(--color-cyan);
  grid-row: 1 / 4;
  margin-right: var(--space-3);
}

.metric-band span,
.metric-band small {
  color: var(--color-muted);
  font-size: 0.72rem;
}

.metric-band strong {
  font-family: var(--font-mono);
  font-size: 1.65rem;
  line-height: 1.1;
}

.benchmark-grid {
  display: grid;
  gap: var(--space-6);
  grid-template-columns: minmax(24rem, 0.9fr) minmax(32rem, 1.4fr);
  padding: var(--space-5) var(--space-6) var(--space-6);
}

.chart-panel,
.table-panel {
  background: color-mix(in srgb, var(--color-surface) 72%, transparent);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  min-width: 0;
  padding: var(--space-4);
}

.chart-panel header,
.table-panel header {
  align-items: center;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
}

.chart-panel h2,
.table-panel h2 {
  font-size: 0.86rem;
  margin: 0;
}

.chart-panel header span,
.table-panel header span {
  color: var(--color-muted);
  font-family: var(--font-mono);
  font-size: 0.67rem;
}

.heatmap {
  height: 23rem;
  width: 100%;
}

@media (max-width: 1250px) {
  .benchmark-grid {
    grid-template-columns: 1fr;
  }
}

</style>
