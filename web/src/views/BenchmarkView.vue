<script setup lang="ts">
import {
  BarChart3,
  CheckCircle2,
  CircleX,
  Clock3,
  ExternalLink,
  GitPullRequest,
  RefreshCw,
  ShieldAlert,
} from 'lucide-vue-next'
import { NButton, NEmpty, NSkeleton, NTag, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'

import FindingCard from '@/components/FindingCard.vue'
import type {
  BenchmarkCollection,
  BenchmarkEntrySummary,
  Finding,
  PipelineEvent,
  RunDetail,
  Severity,
  Verdict,
} from '@/types'

interface BenchmarkDetail {
  entry: BenchmarkEntrySummary
  run: RunDetail
}

const message = useMessage()
const collectionLoading = ref(true)
const collectionError = ref<string | null>(null)
const detailLoading = ref(false)
const entries = ref<BenchmarkEntrySummary[]>([])
const capacity = ref(5)
const selectedRunId = ref<string | null>(null)
const selectedRun = ref<RunDetail | null>(null)
let detailRequestToken = 0

const selectedEntry = computed(
  () => entries.value.find((entry) => entry.run_id === selectedRunId.value) ?? null,
)
const repositoryGroups = computed(() => {
  const groups = new Map<string, BenchmarkEntrySummary[]>()
  for (const entry of entries.value) {
    groups.set(entry.repository, [...(groups.get(entry.repository) ?? []), entry])
  }
  return [...groups.entries()].map(([repository, cases]) => ({
    repository,
    repositoryName: cases[0]?.repository_name ?? repository,
    cases,
  }))
})

const findings = computed(() => deriveFindings(selectedRun.value?.events ?? []))
const keptCount = computed(
  () => findings.value.filter((finding) => finding.verdict !== 'reject').length,
)
const rejectedCount = computed(
  () => findings.value.filter((finding) => finding.verdict === 'reject').length,
)
const elapsedSeconds = computed(() => {
  const events = selectedRun.value?.events ?? []
  if (events.length < 2) return 0
  const timestamps = events.map((event) => event.timestamp)
  return Math.max(0, Math.max(...timestamps) - Math.min(...timestamps))
})
const severityCounts = computed<Record<Severity, number>>(() => {
  const counts: Record<Severity, number> = { critical: 0, high: 0, medium: 0, low: 0 }
  for (const finding of findings.value) counts[finding.severity] += 1
  return counts
})

const severityLabels: Record<Severity, string> = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
}

function deriveFindings(events: PipelineEvent[]): Finding[] {
  const report = [...events].reverse().find((event) => event.type === 'report')
  if (report?.type === 'report' && report.findings) {
    return report.findings.map((finding) => ({ ...finding }))
  }

  const candidates: Finding[] = []
  const verdicts: Verdict[] = []
  for (const event of events) {
    if (event.type === 'finding') candidates.push({ ...event.finding })
    if (event.type === 'verdict') verdicts.push(event.verdict)
  }
  for (const verdict of verdicts) {
    const finding = candidates.find(
      (candidate) => (candidate.source_id ?? candidate.id) === verdict.finding_id,
    )
    if (!finding) continue
    finding.verdict = verdict.verdict
    finding.verdict_reason = verdict.reason
    finding.confidence_adjusted = verdict.confidence_adjusted
  }
  return candidates
}

function statusLabel(status: BenchmarkEntrySummary['status']) {
  if (status === 'ready') return '已完成'
  if (status === 'running') return '审计中'
  return '等待中'
}

function statusType(status: BenchmarkEntrySummary['status']) {
  if (status === 'ready') return 'success'
  if (status === 'running') return 'info'
  return 'warning'
}

function formatElapsed(seconds: number) {
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  return `${(seconds / 60).toFixed(1)} 分钟`
}

async function selectEntry(runId: string) {
  selectedRunId.value = runId
  selectedRun.value = null
  const token = ++detailRequestToken
  const entry = entries.value.find((item) => item.run_id === runId)
  if (!entry || entry.status !== 'ready') {
    detailLoading.value = false
    return
  }

  detailLoading.value = true
  try {
    const response = await fetch(`/api/benchmark/entries/${encodeURIComponent(runId)}`)
    if (!response.ok) throw new Error('审计结果加载失败')
    const payload = (await response.json()) as BenchmarkDetail
    if (token !== detailRequestToken || selectedRunId.value !== runId) return
    selectedRun.value = payload.run
  } catch (error: unknown) {
    if (token !== detailRequestToken) return
    message.error(error instanceof Error ? error.message : '审计结果加载失败')
  } finally {
    if (token === detailRequestToken) detailLoading.value = false
  }
}

async function loadCollection() {
  collectionLoading.value = true
  collectionError.value = null
  try {
    const response = await fetch('/api/benchmark/entries')
    if (!response.ok) throw new Error('Benchmark 列表加载失败')
    const payload = (await response.json()) as BenchmarkCollection
    capacity.value = payload.capacity
    entries.value = payload.entries
    if (payload.entries[0]) await selectEntry(payload.entries[0].run_id)
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : 'Benchmark 列表加载失败'
    collectionError.value = detail
    message.error(detail)
  } finally {
    collectionLoading.value = false
  }
}

onMounted(loadCollection)
</script>

<template>
  <main class="benchmark-page">
    <header class="page-header">
      <div class="heading-copy">
        <span class="eyebrow"><BarChart3 :size="15" /> GREPTILE DATASET</span>
        <h1>Greptile Benchmark</h1>
        <p>查看 5 个仓库、10 个评测任务的审计结果与完整回放</p>
      </div>
      <div class="capacity">
        <strong>{{ entries.length }} / {{ capacity }}</strong>
        <span>评测任务</span>
      </div>
    </header>

    <section v-if="collectionLoading" class="loading-layout" aria-label="正在加载 Benchmark">
      <NSkeleton height="22rem" :sharp="false" />
      <NSkeleton height="22rem" :sharp="false" />
    </section>

    <section v-else-if="collectionError" class="empty-state">
      <NEmpty :description="collectionError">
        <template #extra>
          <p>Benchmark 服务尚未就绪，请稍后重试。</p>
          <NButton secondary @click="loadCollection">
            <template #icon>
              <RefreshCw :size="15" />
            </template>
            重新加载
          </NButton>
        </template>
      </NEmpty>
    </section>

    <section v-else-if="entries.length === 0" class="empty-state">
      <NEmpty description="还没有加入 Benchmark 的审计">
        <template #extra>
          <p>在审计页提交 GitHub PR 时勾选“加入 Benchmark”，完成后即可在这里查看结果。</p>
          <RouterLink to="/review">
            前往审计页
          </RouterLink>
        </template>
      </NEmpty>
    </section>

    <section v-else class="browser-layout">
      <aside class="repository-panel">
        <header>
          <div>
            <h2>评测仓库</h2>
            <span>选择题目查看结果</span>
          </div>
          <NTag size="small" :bordered="false">
            {{ entries.length }}
          </NTag>
        </header>
        <nav aria-label="Benchmark 仓库">
          <section
            v-for="group in repositoryGroups"
            :key="group.repository"
            class="repository-group"
          >
            <header class="repository-group-header">
              <strong>{{ group.repositoryName }}</strong>
              <span>{{ group.cases.length }} 题</span>
            </header>
            <button
              v-for="entry in group.cases"
              :key="entry.run_id"
              type="button"
              class="repository-item"
              :class="{ selected: entry.run_id === selectedRunId }"
              :aria-pressed="entry.run_id === selectedRunId"
              @click="selectEntry(entry.run_id)"
            >
              <span class="repository-icon"><GitPullRequest :size="17" /></span>
              <span class="repository-copy">
                <strong>{{ entry.name ?? `PR #${entry.pr_number}` }}</strong>
                <small>PR #{{ entry.pr_number }} · {{ entry.repository }}</small>
              </span>
              <NTag :type="statusType(entry.status)" size="small" :bordered="false">
                {{ statusLabel(entry.status) }}
              </NTag>
            </button>
          </section>
        </nav>
      </aside>

      <section class="result-panel">
        <template v-if="selectedEntry">
          <header class="result-header">
            <div>
              <span>{{ selectedEntry.repository }}</span>
              <h2>{{ selectedEntry.name ?? `${selectedEntry.repository_name} · PR #${selectedEntry.pr_number}` }}</h2>
            </div>
            <RouterLink
              :to="`/review/${selectedEntry.run_id}`"
              class="audit-link"
              aria-label="回放完整审计"
            >
              <ExternalLink :size="15" />
              回放完整审计
            </RouterLink>
          </header>

          <div v-if="selectedEntry.status !== 'ready'" class="pending-result">
            <div class="pending-copy">
              <Clock3 :size="18" />
              <div>
                <strong>{{ statusLabel(selectedEntry.status) }}</strong>
                <span>审计完成后将在这里显示原始结果，无需重新运行。</span>
              </div>
            </div>
            <NSkeleton text :repeat="6" />
          </div>

          <div v-else-if="detailLoading" class="detail-loading" aria-label="正在加载审计结果">
            <NSkeleton height="6rem" :sharp="false" />
            <NSkeleton text :repeat="8" />
          </div>

          <template v-else-if="selectedRun">
            <div class="metric-strip">
              <article>
                <ShieldAlert :size="17" />
                <span>全部问题</span>
                <strong>{{ findings.length }}</strong>
              </article>
              <article>
                <CheckCircle2 :size="17" />
                <span>保留</span>
                <strong>{{ keptCount }}</strong>
              </article>
              <article>
                <CircleX :size="17" />
                <span>已排除</span>
                <strong>{{ rejectedCount }}</strong>
              </article>
              <article>
                <Clock3 :size="17" />
                <span>审计耗时</span>
                <strong>{{ formatElapsed(elapsedSeconds) }}</strong>
              </article>
            </div>

            <div class="severity-row" aria-label="严重级别分布">
              <span v-for="(label, severity) in severityLabels" :key="severity">
                <i :data-severity="severity" />{{ label }} {{ severityCounts[severity] }}
              </span>
            </div>

            <div class="findings-section">
              <header>
                <h3>审计 Findings</h3>
                <span>{{ findings.length }} 条原始结果</span>
              </header>
              <div v-if="findings.length" class="finding-list scrollbar">
                <FindingCard
                  v-for="finding in findings"
                  :key="finding.id"
                  :finding="finding"
                  :run-id="selectedEntry.run_id"
                />
              </div>
              <NEmpty v-else description="该次审计没有发现需要展示的问题" />
            </div>
          </template>
        </template>
      </section>
    </section>
  </main>
</template>

<style scoped>
.benchmark-page {
  height: calc(100vh - var(--app-bar-height));
  overflow-y: auto;
}

.page-header {
  align-items: center;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  min-height: 7rem;
  padding: var(--space-4) var(--space-6);
}

.heading-copy {
  min-width: 0;
}

.eyebrow {
  align-items: center;
  color: var(--color-cyan);
  display: flex;
  font-family: var(--font-mono);
  font-size: 0.68rem;
  gap: var(--space-2);
}

.heading-copy h1 {
  font-size: 1.45rem;
  margin: var(--space-1) 0;
}

.heading-copy p,
.capacity span,
.repository-panel header span,
.result-header span,
.pending-copy span,
.findings-section header span {
  color: var(--color-muted);
  font-size: 0.72rem;
  margin: 0;
}

.capacity {
  border-left: 1px solid var(--color-border);
  display: grid;
  gap: var(--space-1);
  min-width: 7rem;
  padding-left: var(--space-5);
}

.capacity strong {
  font-family: var(--font-mono);
  font-size: 1.25rem;
}

.loading-layout,
.browser-layout {
  display: grid;
  gap: var(--space-5);
  grid-template-columns: minmax(17rem, 21rem) minmax(0, 1fr);
  padding: var(--space-5) var(--space-6) var(--space-6);
}

.empty-state {
  display: grid;
  min-height: 24rem;
  padding: var(--space-6);
  place-items: center;
  text-align: center;
}

.empty-state p {
  color: var(--color-muted);
  margin: var(--space-3) auto;
  max-width: 30rem;
}

.empty-state a,
.audit-link {
  color: var(--color-cyan);
  font-size: 0.76rem;
  text-decoration: none;
}

.empty-state a:hover,
.audit-link:hover {
  color: var(--color-text);
}

.repository-panel,
.result-panel {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  min-width: 0;
  overflow: hidden;
}

.repository-panel {
  align-self: start;
}

.repository-panel > header,
.result-header,
.findings-section > header {
  align-items: center;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  padding: var(--space-4);
}

.repository-panel h2,
.result-header h2,
.findings-section h3 {
  font-size: 0.86rem;
  margin: 0 0 var(--space-1);
}

.repository-panel nav {
  display: grid;
}

.repository-group + .repository-group {
  border-top: 1px solid var(--color-border);
}

.repository-group-header {
  align-items: center;
  background: var(--color-surface-raised);
  display: flex;
  gap: var(--space-3);
  justify-content: space-between;
  min-width: 0;
  padding: var(--space-2) var(--space-4);
}

.repository-group-header strong {
  font-size: 0.7rem;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.repository-group-header span {
  flex-shrink: 0;
  font-family: var(--font-mono);
}

.repository-item {
  align-items: center;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text);
  cursor: pointer;
  display: grid;
  gap: var(--space-3);
  grid-template-columns: 2rem minmax(0, 1fr) auto;
  min-height: 4.5rem;
  padding: var(--space-3) var(--space-4);
  text-align: left;
  width: 100%;
}

.repository-group .repository-item:last-child {
  border-bottom: 0;
}

.repository-item:hover,
.repository-item.selected {
  background: var(--color-surface-raised);
}

.repository-item.selected {
  box-shadow: inset 0.18rem 0 var(--color-cyan);
}

.repository-icon {
  color: var(--color-cyan);
  display: grid;
  place-items: center;
}

.repository-copy {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
}

.repository-copy strong,
.repository-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.repository-copy strong {
  font-size: 0.78rem;
}

.repository-copy small {
  color: var(--color-muted);
  font-family: var(--font-mono);
  font-size: 0.62rem;
}

.result-panel {
  min-height: 30rem;
}

.result-header h2 {
  font-size: 1rem;
  overflow-wrap: anywhere;
}

.result-header > div {
  min-width: 0;
}

.audit-link {
  align-items: center;
  display: flex;
  flex-shrink: 0;
  gap: var(--space-2);
}

.pending-result,
.detail-loading {
  display: grid;
  gap: var(--space-6);
  padding: var(--space-6);
}

.pending-copy {
  align-items: center;
  display: flex;
  gap: var(--space-3);
}

.pending-copy > svg {
  color: var(--color-cyan);
}

.pending-copy div {
  display: grid;
  gap: var(--space-1);
}

.metric-strip {
  border-bottom: 1px solid var(--color-border);
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.metric-strip article {
  display: grid;
  gap: var(--space-1);
  grid-template-columns: auto 1fr;
  min-height: 6.2rem;
  padding: var(--space-4);
}

.metric-strip article + article {
  border-left: 1px solid var(--color-border);
}

.metric-strip svg {
  color: var(--color-cyan);
  grid-row: 1 / 3;
  margin-right: var(--space-2);
}

.metric-strip span {
  color: var(--color-muted);
  font-size: 0.68rem;
}

.metric-strip strong {
  font-family: var(--font-mono);
  font-size: 1.15rem;
}

.severity-row {
  align-items: center;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-5);
  min-height: 3rem;
  padding: var(--space-2) var(--space-4);
}

.severity-row span {
  align-items: center;
  color: var(--color-muted);
  display: flex;
  font-size: 0.68rem;
  gap: var(--space-2);
}

.severity-row i {
  background: var(--color-muted);
  border-radius: 50%;
  height: 0.45rem;
  width: 0.45rem;
}

.severity-row i[data-severity='critical'] {
  background: var(--color-red);
}

.severity-row i[data-severity='high'] {
  background: var(--color-amber);
}

.severity-row i[data-severity='medium'] {
  background: var(--color-blue);
}

.severity-row i[data-severity='low'] {
  background: var(--color-green);
}

.findings-section > header {
  border-bottom: 0;
}

.finding-list {
  display: grid;
  gap: var(--space-3);
  max-height: calc(100vh - 27rem);
  min-height: 12rem;
  overflow-y: auto;
  padding: 0 var(--space-4) var(--space-4);
}

@media (max-width: 68rem) {
  .loading-layout,
  .browser-layout {
    grid-template-columns: 1fr;
  }

  .repository-panel nav {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .repository-item:nth-child(odd) {
    border-right: 1px solid var(--color-border);
  }

  .finding-list {
    max-height: none;
  }
}

@media (max-width: 42rem) {
  .page-header {
    padding: var(--space-4);
  }

  .loading-layout,
  .browser-layout {
    padding: var(--space-4);
  }

  .repository-panel nav,
  .metric-strip {
    grid-template-columns: 1fr;
  }

  .repository-item:nth-child(odd) {
    border-right: 0;
  }

  .metric-strip article + article {
    border-left: 0;
    border-top: 1px solid var(--color-border);
  }

  .result-header {
    align-items: flex-start;
    gap: var(--space-3);
  }

  .audit-link {
    font-size: 0;
  }
}
</style>
