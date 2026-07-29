<template>
  <div class="result-page">
    <!-- 头部 -->
    <div class="result-header">
      <div>
        <h2>审查结果</h2>
        <span class="run-id">Run: {{ store.runId }}</span>
      </div>
      <div class="header-actions">
        <button v-if="store.reportUrl" class="btn" @click="downloadReport">下载 Markdown 报告</button>
        <router-link to="/" class="btn btn-outline">新建审查</router-link>
      </div>
    </div>

    <!-- 统计摘要 -->
    <div class="stats-row">
      <div class="stat-card">
        <span class="stat-value">{{ store.acceptedFindings.length }}</span>
        <span class="stat-label">确认发现</span>
      </div>
      <div class="stat-card rejected">
        <span class="stat-value">{{ store.rejectedFindings.length }}</span>
        <span class="stat-label">已拒绝</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ formatMs(store.totalDurationMs) }}</span>
        <span class="stat-label">总耗时</span>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="filters">
      <div class="filter-group">
        <label>严重度</label>
        <select v-model="filterSeverity" class="select">
          <option value="">全部</option>
          <option value="critical">严重</option>
          <option value="high">高</option>
          <option value="medium">中</option>
          <option value="low">低</option>
        </select>
      </div>
      <div class="filter-group">
        <label>类别</label>
        <select v-model="filterCategory" class="select">
          <option value="">全部</option>
          <option v-for="cat in allCategories" :key="cat" :value="cat">{{ cat }}</option>
        </select>
      </div>
      <div class="filter-group">
        <label>来源</label>
        <select v-model="filterProducer" class="select">
          <option value="">全部</option>
          <option value="defect">缺陷检测</option>
          <option value="intent">意图分析</option>
        </select>
      </div>
    </div>

    <!-- Finding 列表 -->
    <div v-if="filteredFindings.length === 0" class="empty-state">
      暂无匹配的审查发现
    </div>

    <FindingCard
      v-for="entry in filteredFindings"
      :key="entry.finding.id"
      :finding="entry.finding"
      :verifier-status="entry.verifierStatus"
      :verifier-reason="entry.verifierReason"
      :show-detail="true"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useReviewStore } from '../stores/review'
import { getStatus, getReport } from '../api/client'
import FindingCard from '../components/FindingCard.vue'

const route = useRoute()
const store = useReviewStore()
const runId = route.params.runId as string

const filterSeverity = ref('')
const filterCategory = ref('')
const filterProducer = ref('')

onMounted(async () => {
  try {
    const status = await getStatus(runId)
    store.reset()
    store.applyEvents(status.events)
  } catch {
    // 处理错误
  }
})

const allCategories = computed(() => {
  const cats = new Set<string>()
  for (const c of store.candidates) {
    if (c.finding.category) cats.add(c.finding.category)
  }
  return [...cats].sort()
})

const filteredFindings = computed(() => {
  return store.candidates.filter((entry) => {
    const f = entry.finding
    if (filterSeverity.value && f.severity !== filterSeverity.value) return false
    if (filterCategory.value && f.category !== filterCategory.value) return false
    if (filterProducer.value && f.producer !== filterProducer.value) return false
    return true
  })
})

async function downloadReport() {
  try {
    const text = await getReport(runId)
    const blob = new Blob([text], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `review-${runId}.md`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    // 处理错误
  }
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  const secs = (ms / 1000).toFixed(1)
  return `${secs}s`
}
</script>

<style scoped>
.result-page {
  max-width: 960px;
  margin: 0 auto;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.run-id {
  font-size: 12px;
  color: var(--color-text-muted);
  font-family: monospace;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: var(--color-surface);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow);
  text-align: center;
}

.stat-card.rejected {
  background: #fef2f2;
}

.stat-value {
  display: block;
  font-size: 28px;
  font-weight: 700;
}

.stat-label {
  font-size: 13px;
  color: var(--color-text-muted);
}

.filters {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  background: var(--color-surface);
  padding: 16px;
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.filter-group label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.select {
  padding: 6px 10px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  font-size: 13px;
  background: var(--color-surface);
}

.empty-state {
  text-align: center;
  padding: 48px;
  color: var(--color-text-muted);
  font-size: 15px;
}

.btn {
  padding: 8px 20px;
  border: none;
  border-radius: var(--radius);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  background: var(--color-primary);
  color: #fff;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}

.btn-outline {
  background: var(--color-surface);
  color: var(--color-primary);
  border: 1px solid var(--color-primary);
}
</style>
