<template>
  <div class="benchmark-page">
    <h2>评测面板</h2>
    <p class="subtitle">5 个开源仓库的审查命中率统计</p>

    <!-- 演示数据提示 -->
    <div class="demo-banner">
      ⚠️ 当前为演示数据，接入真实 API 后将展示实际评测结果。
    </div>

    <!-- 总览 -->
    <div class="stats-row">
      <div class="stat-card">
        <span class="stat-value">{{ overallHitRate }}%</span>
        <span class="stat-label">整体命中率</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ totalFindings }}</span>
        <span class="stat-label">总有效发现</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ totalCandidates }}</span>
        <span class="stat-label">总候选数</span>
      </div>
    </div>

    <!-- 各仓库结果 -->
    <div class="bench-table-wrap">
      <table class="bench-table">
        <thead>
          <tr>
            <th>仓库</th>
            <th>PR 数</th>
            <th>候选</th>
            <th>确认</th>
            <th>命中率</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="repo in repos" :key="repo.name">
            <td class="repo-name">{{ repo.name }}</td>
            <td>{{ repo.prCount }}</td>
            <td>{{ repo.candidates }}</td>
            <td>{{ repo.accepted }}</td>
            <td>
              <span class="hit-badge" :class="hitClass(repo.hitRate)">{{ repo.hitRate }}%</span>
            </td>
            <td>
              <button v-if="repo.bestRunId" class="btn-sm" @click="playReplay(repo.bestRunId)">
                播放最佳
              </button>
              <span v-else class="no-data">-</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

interface RepoResult {
  name: string
  prCount: number
  candidates: number
  accepted: number
  hitRate: number
  bestRunId: string | null
}

// 模拟评测数据（后续接入真实 API）
const repos = ref<RepoResult[]>([
  { name: 'vuejs/core', prCount: 20, candidates: 156, accepted: 128, hitRate: 82, bestRunId: 'demo-001' },
  { name: 'facebook/react', prCount: 15, candidates: 89, accepted: 71, hitRate: 80, bestRunId: 'demo-002' },
  { name: 'axios/axios', prCount: 12, candidates: 45, accepted: 30, hitRate: 67, bestRunId: 'demo-003' },
  { name: 'expressjs/express', prCount: 10, candidates: 38, accepted: 21, hitRate: 55, bestRunId: null },
  { name: 'lodash/lodash', prCount: 8, candidates: 27, accepted: 14, hitRate: 52, bestRunId: null },
])

const totalCandidates = computed(() => repos.value.reduce((s, r) => s + r.candidates, 0))
const totalFindings = computed(() => repos.value.reduce((s, r) => s + r.accepted, 0))
const overallHitRate = computed(() => {
  if (totalCandidates.value === 0) return 0
  return Math.round((totalFindings.value / totalCandidates.value) * 100)
})

function hitClass(rate: number) {
  if (rate >= 80) return 'good'
  if (rate >= 60) return 'medium'
  return 'low'
}

function playReplay(runId: string) {
  router.push({ name: 'review', params: { runId }, query: { replay: '1' } })
}
</script>

<style scoped>
.benchmark-page {
  max-width: 960px;
  margin: 0 auto;
}

.subtitle {
  color: var(--color-text-muted);
  font-size: 14px;
  margin-bottom: 16px;
}

.demo-banner {
  background: #fffbeb;
  color: #92400e;
  border: 1px solid #fcd34d;
  border-radius: var(--radius);
  padding: 10px 16px;
  font-size: 13px;
  margin-bottom: 24px;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 32px;
}

.stat-card {
  background: var(--color-surface);
  border-radius: var(--radius);
  padding: 24px;
  box-shadow: var(--shadow);
  text-align: center;
}

.stat-value {
  display: block;
  font-size: 32px;
  font-weight: 700;
}

.stat-label {
  font-size: 13px;
  color: var(--color-text-muted);
}

.bench-table-wrap {
  background: var(--color-surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}

.bench-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.bench-table th,
.bench-table td {
  padding: 12px 16px;
  text-align: left;
  border-bottom: 1px solid var(--color-border);
}

.bench-table th {
  background: var(--color-bg);
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.repo-name {
  font-weight: 600;
  font-family: monospace;
}

.hit-badge {
  padding: 2px 10px;
  border-radius: 12px;
  font-weight: 600;
  font-size: 13px;
}

.hit-badge.good {
  background: #ecfdf5;
  color: #065f46;
}

.hit-badge.medium {
  background: #fffbeb;
  color: #92400e;
}

.hit-badge.low {
  background: #fef2f2;
  color: #991b1b;
}

.btn-sm {
  padding: 4px 14px;
  border: none;
  border-radius: 4px;
  background: var(--color-primary);
  color: #fff;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.btn-sm:hover {
  background: #2563eb;
}

.btn-sm:focus-visible {
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.4);
}

.no-data {
  color: var(--color-text-muted);
}

@media (max-width: 640px) {
  .stats-row {
    grid-template-columns: 1fr;
  }

  .bench-table {
    font-size: 12px;
  }

  .bench-table th,
  .bench-table td {
    padding: 8px 10px;
  }
}

@media (max-width: 480px) {
  .bench-table-wrap {
    overflow-x: auto;
  }

  .bench-table th,
  .bench-table td {
    padding: 6px 8px;
    font-size: 11px;
  }
}
</style>
