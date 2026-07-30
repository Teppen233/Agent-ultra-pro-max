<script lang="ts">
import type { RepositoryBenchmarkSummary, RepositoryBenchmarkStatus } from '@/contracts'

export interface RepositoryBenchmarkPresentation {
  status: string
  catchRate: string
  targetStatus: string
  elapsed: string
  offlineNotice: string
  canOpenRun: boolean
  runPath: string
  replayPath: string
  unavailableRunNotice: string
}

const statusLabels: Record<RepositoryBenchmarkStatus, string> = {
  needs_data: '待补齐',
  pending: '待评测',
  running: '评测中',
  completed: '已完成',
  partial: '部分完成',
  failed: '评测失败',
}

const percent = (value: number): string => `${(value * 100).toFixed(1)}%`

/** 仅完整执行的案例具有可判定的目标命中结论。 */
export const presentCaseTargetStatus = (item: RepositoryBenchmarkSummary['cases'][number]): string => {
  if (item.status !== 'completed') return '暂无判定'
  return item.judge.caught ? '目标命中' : '目标未命中'
}

/** 将逐仓原始评测数据归一为不伪造成绩的中文展示状态。 */
export const presentRepositoryBenchmark = (
  repository: RepositoryBenchmarkSummary,
  offline: boolean,
): RepositoryBenchmarkPresentation => {
  const runId = repository.latest_run_id
  const canOpenRun = !offline && runId !== null
  const hasConclusion = repository.catch_rate !== null
  return {
    status: statusLabels[repository.status],
    catchRate: repository.catch_rate === null
      ? '暂无数据'
      : repository.catch_rate === 0 ? '未命中' : percent(repository.catch_rate),
    targetStatus: !hasConclusion
      ? '暂无判定'
      : repository.target_caught > 0 ? `目标命中 ${repository.target_caught}` : '目标未命中',
    elapsed: `${repository.elapsed_seconds.toFixed(2)}s`,
    offlineNotice: offline ? '离线链路验证' : '',
    canOpenRun,
    runPath: canOpenRun && runId ? `/result/${encodeURIComponent(runId)}` : '',
    replayPath: canOpenRun && runId ? `/review/${encodeURIComponent(runId)}?replay=1` : '',
    unavailableRunNotice: offline ? '离线结果无运行回放' : '',
  }
}
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  repositories: RepositoryBenchmarkSummary[]
  offline: boolean
}>()

const expandedRepository = ref<string | null>(null)
const rows = computed(() => props.repositories.map((repository) => ({
  repository,
  view: presentRepositoryBenchmark(repository, props.offline),
})))

const toggleCases = (repository: string): void => {
  expandedRepository.value = expandedRepository.value === repository ? null : repository
}
</script>

<template>
  <section class="repository-benchmark-matrix panel" aria-labelledby="repository-benchmark-heading">
    <div class="section-heading">
      <div><span class="eyebrow">逐仓评测</span><h2 id="repository-benchmark-heading">五仓真实评测矩阵</h2></div>
      <span v-if="offline" class="offline-badge">离线链路验证</span>
    </div>
    <div class="repository-table" role="table" aria-label="逐仓评测结果">
      <div class="repository-row repository-head" role="row">
        <span role="columnheader">仓库</span><span role="columnheader">状态</span><span role="columnheader">目标命中</span>
        <span role="columnheader">命中率</span><span role="columnheader">运行统计</span><span role="columnheader">操作</span>
      </div>
      <template v-for="row in rows" :key="row.repository.repository">
        <article class="repository-row" role="row" :class="`status-${row.repository.status}`">
          <div role="cell"><strong>{{ row.repository.repository }}</strong><small>{{ row.repository.language }}</small></div>
          <div role="cell"><span class="repository-status">{{ row.view.status }}</span><small v-if="row.view.offlineNotice" class="repository-offline">{{ row.view.offlineNotice }}</small></div>
          <div role="cell"><strong>{{ row.view.targetStatus }}</strong><small>其他 Finding {{ row.repository.other_findings }} · 拒绝 {{ row.repository.rejected_count }}</small></div>
          <div role="cell"><strong>{{ row.view.catchRate }}</strong><small v-if="row.repository.catch_rate === null">尚无可计算命中率</small></div>
          <div role="cell"><strong>{{ row.repository.executed_cases }} / {{ row.repository.total_cases }} 例</strong><small>{{ row.view.elapsed }}</small></div>
          <div class="repository-actions" role="cell">
            <button type="button" @click="toggleCases(row.repository.repository)">查看案例</button>
            <RouterLink v-if="row.view.canOpenRun" :to="row.view.runPath">查看运行</RouterLink>
            <RouterLink v-if="row.view.canOpenRun" :to="row.view.replayPath">回放过程</RouterLink>
            <span v-else class="repository-no-run">{{ row.view.unavailableRunNotice || '暂无运行' }}</span>
          </div>
        </article>
        <div v-if="expandedRepository === row.repository.repository" class="repository-cases" role="region" :aria-label="`${row.repository.repository} 案例`">
          <p v-if="!row.repository.cases.length">暂无已运行案例。</p>
          <ul v-else>
            <li v-for="item in row.repository.cases" :key="item.case_id">
              <strong>{{ item.case_id }}</strong><span>{{ item.status }}</span><span>{{ presentCaseTargetStatus(item) }}</span>
            </li>
          </ul>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.repository-benchmark-matrix { margin-top: 18px; padding: 22px; border-radius: 9px; }
.offline-badge, .repository-status { width: fit-content; border: 1px solid rgba(255, 184, 77, .42); border-radius: 999px; color: var(--amber); background: rgba(255, 184, 77, .08); padding: 4px 7px; font-size: 8px; }
.repository-table { overflow-x: auto; }.repository-row { min-width: 810px; display: grid; grid-template-columns: 1.1fr .8fr 1.1fr .8fr .8fr 1.4fr; gap: 12px; align-items: center; padding: 13px 0; border-top: 1px solid var(--line); }.repository-head { color: #617a8e; font-size: 8px; }.repository-row > div { display: flex; min-width: 0; flex-direction: column; gap: 5px; }.repository-row strong { color: #dbeaf4; font-size: 10px; }.repository-row small { color: #6d869a; font-size: 8px; }.repository-offline { color: var(--amber) !important; }.repository-actions { flex-direction: row !important; flex-wrap: wrap; align-items: center; }.repository-actions :is(a, button) { border: 1px solid #2c4a60; border-radius: 4px; background: #10253a; color: #a8bdcc; padding: 5px 7px; font-size: 8px; }.repository-actions :is(a, button):hover { border-color: var(--cyan); color: var(--cyan); }.repository-no-run { color: #657c90; font-size: 8px; }.repository-cases { margin: -1px 0 0; border-top: 1px dashed #29465e; padding: 11px 0 3px; color: #8298aa; font-size: 8px; }.repository-cases p { margin: 0; }.repository-cases ul { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }.repository-cases li { display: flex; gap: 12px; }.repository-cases li strong { color: #c9dbe8; }
</style>
