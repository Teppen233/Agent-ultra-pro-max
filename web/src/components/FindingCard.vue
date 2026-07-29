<template>
  <div class="finding-card" :class="[finding.severity, verifierStatus]">
    <div class="finding-header">
      <div class="finding-header-left">
        <span class="severity-badge" :class="finding.severity">{{ severityLabel }}</span>
        <span class="finding-title">{{ finding.title }}</span>
      </div>
      <div class="finding-header-right">
        <span class="producer-badge" :class="finding.producer">
          {{ finding.producer === 'defect' ? '缺陷检测' : '意图分析' }}
        </span>
        <span v-if="verifierStatus === 'accepted'" class="verdict accepted">已确认</span>
        <span v-else-if="verifierStatus === 'rejected'" class="verdict rejected">已拒绝</span>
        <span v-else class="verdict pending">验证中</span>
      </div>
    </div>

    <div class="finding-meta">
      <span class="meta-item" :title="finding.file">
        {{ shortFilePath(finding.file) }}:{{ finding.line_start }}
      </span>
      <span class="meta-item">{{ finding.category }}</span>
      <span class="meta-item">置信度 {{ Math.round(finding.confidence * 100) }}%</span>
    </div>

    <p class="finding-desc">{{ finding.description }}</p>

    <!-- 详细展开（仅在 showDetail 为 true 时显示） -->
    <div v-if="showDetail" class="finding-detail">
      <div class="detail-section">
        <strong>触发条件</strong>
        <p>{{ finding.trigger_condition || '无' }}</p>
      </div>
      <div class="detail-section">
        <strong>影响分析</strong>
        <p>{{ finding.impact || '无' }}</p>
      </div>
      <div class="detail-section" v-if="finding.suggestion">
        <strong>修复建议</strong>
        <p>{{ finding.suggestion }}</p>
      </div>
      <div class="detail-section" v-if="verifierReason">
        <strong>验证理由</strong>
        <p>{{ verifierReason }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Finding } from '../contracts'

const props = defineProps<{
  finding: Finding
  verifierStatus: 'pending' | 'accepted' | 'rejected'
  verifierReason?: string
  showDetail?: boolean
}>()

const severityLabel = computed(() => {
  switch (props.finding.severity) {
    case 'critical':
      return '严重'
    case 'high':
      return '高'
    case 'medium':
      return '中'
    case 'low':
      return '低'
    default:
      return props.finding.severity
  }
})

function shortFilePath(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/')
  if (parts.length <= 2) return path
  return '.../' + parts.slice(-2).join('/')
}
</script>

<style scoped>
.finding-card {
  background: var(--color-surface);
  border-radius: var(--radius);
  padding: 16px;
  box-shadow: var(--shadow);
  border-left: 4px solid var(--color-border);
  margin-bottom: 12px;
  transition: border-color 0.2s;
}

.finding-card.critical {
  border-left-color: #dc2626;
}

.finding-card.high {
  border-left-color: #ea580c;
}

.finding-card.medium {
  border-left-color: #ca8a04;
}

.finding-card.low {
  border-left-color: var(--color-text-muted);
}

.finding-card.accepted {
  opacity: 1;
}

.finding-card.rejected {
  opacity: 0.6;
}

.finding-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 8px;
}

.finding-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.finding-title {
  font-size: 15px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.severity-badge {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.severity-badge.critical {
  background: #fef2f2;
  color: #dc2626;
}

.severity-badge.high {
  background: #fff7ed;
  color: #ea580c;
}

.severity-badge.medium {
  background: #fefce8;
  color: #ca8a04;
}

.severity-badge.low {
  background: var(--color-bg);
  color: var(--color-text-muted);
}

.finding-header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.producer-badge {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
}

.producer-badge.defect {
  background: rgba(99, 102, 241, 0.1);
  color: var(--color-info);
}

.producer-badge.intent {
  background: rgba(139, 92, 246, 0.1);
  color: #7c3aed;
}

.verdict {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.verdict.accepted {
  background: #ecfdf5;
  color: #065f46;
}

.verdict.rejected {
  background: #fef2f2;
  color: #991b1b;
}

.verdict.pending {
  background: var(--color-bg);
  color: var(--color-text-muted);
}

.finding-meta {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.meta-item {
  font-size: 12px;
  color: var(--color-text-muted);
  font-family: monospace;
}

.finding-desc {
  font-size: 13px;
  color: var(--color-text);
  line-height: 1.5;
}

.finding-detail {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border);
}

.detail-section {
  margin-bottom: 8px;
}

.detail-section strong {
  font-size: 12px;
  color: var(--color-text-muted);
  display: block;
  margin-bottom: 2px;
}

.detail-section p {
  font-size: 13px;
  line-height: 1.5;
}
</style>
