<script setup lang="ts">
import type { Finding, VerdictStatus } from '@/contracts'

withDefaults(defineProps<{ finding: Finding; verdict?: VerdictStatus; verdictText?: string }>(), {
  verdict: 'accepted', verdictText: '',
})

const severityText = { critical: '严重', high: '高危', medium: '中危', low: '低危' }
const categoryText: Record<string, string> = {
  security: '安全', logic: '逻辑', business_logic: '业务逻辑', reliability: '可靠性',
  architecture: '架构', memory: '资源', static: '静态缺陷',
}
</script>

<template>
  <article class="finding-card" :class="[finding.severity ?? 'medium', verdict]">
    <div class="finding-head">
      <span class="severity">{{ severityText[finding.severity ?? 'medium'] }}</span>
      <span class="category">{{ categoryText[finding.category ?? ''] ?? finding.category ?? '待分类' }}</span>
      <span class="location">{{ finding.file ?? '未知文件' }}:{{ finding.line_start ?? finding.line ?? '?' }}</span>
      <span class="confidence">{{ Math.round((finding.confidence ?? 0) * 100) }}% 置信</span>
    </div>
    <h3>{{ finding.title ?? '待补全的候选问题' }}</h3>
    <p>{{ finding.description ?? '实时事件仅包含定位摘要，最终报告生成后会补全描述。' }}</p>
    <dl>
      <div><dt>触发条件</dt><dd>{{ finding.trigger_condition ?? finding.trigger ?? '等待最终报告补全' }}</dd></div>
      <div><dt>实际影响</dt><dd>{{ finding.impact ?? '等待最终报告补全' }}</dd></div>
    </dl>
    <details v-if="finding.evidence?.length">
      <summary>查看代码证据 · {{ finding.evidence.length }} 处</summary>
      <pre v-for="evidence in finding.evidence" :key="`${evidence.file}-${evidence.start_line}`"><code>{{ evidence.content }}</code></pre>
    </details>
    <div v-if="finding.suggestion || finding.recommendation" class="suggestion"><strong>修复建议</strong>{{ finding.suggestion ?? finding.recommendation }}</div>
    <footer :class="verdict">
      <svg viewBox="0 0 24 24"><path v-if="verdict === 'accepted'" d="m5 12 4 4L19 6" /><path v-else d="m6 6 12 12M18 6 6 18" /></svg>
      <span><strong>{{ verdict === 'accepted' ? 'Verifier 已确认' : verdict === 'rejected' ? 'Verifier 已拒绝' : verdictText || '等待 Verifier' }}</strong><small v-if="verdictText && verdict !== 'pending'">{{ verdictText }}</small></span>
    </footer>
  </article>
</template>
