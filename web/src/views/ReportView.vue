<script setup lang="ts">
import { ArrowLeft, FileText } from 'lucide-vue-next'
import { NButton, NEmpty, NSkeleton, useMessage } from 'naive-ui'
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'

import { useReviewStore } from '@/stores/review'

const route = useRoute()
const store = useReviewStore()
const message = useMessage()
const runId = typeof route.params.runId === 'string' ? route.params.runId : ''

onMounted(async () => {
  if (!runId) return
  try {
    await store.loadRun(runId)
  } catch (error: unknown) {
    message.error(error instanceof Error ? error.message : '报告加载失败')
  }
})
</script>

<template>
  <div class="report-page">
    <header class="report-toolbar">
      <RouterLink :to="`/review/${runId}`">
        <NButton quaternary aria-label="返回审查工作台">
          <template #icon>
            <ArrowLeft :size="16" />
          </template>
          返回审查
        </NButton>
      </RouterLink>
      <div>
        <span><FileText :size="14" /> FINAL REPORT</span>
        <strong>审查报告</strong>
      </div>
      <code>{{ runId }}</code>
    </header>

    <main class="report-content scrollbar">
      <NSkeleton v-if="store.loading" text :repeat="12" />
      <pre v-else-if="store.report">{{ store.report }}</pre>
      <NEmpty v-else description="该运行尚未生成最终报告，请返回审查页查看运行状态" />
    </main>
  </div>
</template>

<style scoped>
.report-page {
  background: var(--color-bg);
  min-height: calc(100vh - var(--app-bar-height));
}

.report-toolbar {
  align-items: center;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  display: grid;
  gap: var(--space-4);
  grid-template-columns: 10rem 1fr auto;
  min-height: 4.5rem;
  padding: var(--space-3) var(--space-5);
  position: sticky;
  top: var(--app-bar-height);
  z-index: 10;
}

.report-toolbar > div {
  display: grid;
  gap: var(--space-1);
}

.report-toolbar span {
  align-items: center;
  color: var(--color-cyan);
  display: flex;
  font-family: var(--font-mono);
  font-size: 0.62rem;
  gap: var(--space-1);
}

.report-toolbar strong {
  font-size: 1rem;
}

.report-toolbar code {
  color: var(--color-muted);
  font-size: 0.68rem;
}

.report-content {
  margin: 0 auto;
  max-width: 62rem;
  padding: var(--space-6) var(--space-5);
}

.report-content pre {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text);
  font-family: var(--font-sans);
  font-size: 0.84rem;
  line-height: 1.75;
  margin: 0;
  overflow-wrap: anywhere;
  padding: var(--space-6);
  white-space: pre-wrap;
}

@media (max-width: 48rem) {
  .report-toolbar {
    grid-template-columns: auto 1fr;
  }

  .report-toolbar code {
    display: none;
  }

  .report-content {
    padding: var(--space-3);
  }
}
</style>
