<script setup lang="ts">
import { ArrowLeft, Copy, FileDiff, ShieldAlert } from 'lucide-vue-next'
import { NButton, NEmpty, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { useReviewStore } from '@/stores/review'

interface DiffLine {
  content: string
  kind: 'add' | 'remove' | 'context' | 'header'
  oldLine: number | null
  newLine: number | null
}

const store = useReviewStore()
const route = useRoute()
const message = useMessage()
const selectedId = ref<string | null>(null)

const lines = computed<DiffLine[]>(() => {
  if (!store.diff) return []
  let oldLine = 0
  let newLine = 0
  return store.diff.split('\n').map((content) => {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(content)
    if (hunk?.[1] && hunk[2]) {
      oldLine = Number(hunk[1])
      newLine = Number(hunk[2])
      return { content, kind: 'header', oldLine: null, newLine: null }
    }
    if (content.startsWith('+') && !content.startsWith('+++')) {
      const line = { content, kind: 'add' as const, oldLine: null, newLine }
      newLine += 1
      return line
    }
    if (content.startsWith('-') && !content.startsWith('---')) {
      const line = { content, kind: 'remove' as const, oldLine, newLine: null }
      oldLine += 1
      return line
    }
    if (content.startsWith(' ')) {
      const line = { content, kind: 'context' as const, oldLine, newLine }
      oldLine += 1
      newLine += 1
      return line
    }
    return { content, kind: 'header', oldLine: null, newLine: null }
  })
})

const selectedFinding = computed(() => store.findings.find((item) => item.id === selectedId.value) ?? store.retainedFindings[0] ?? null)

function findingAt(line: DiffLine) {
  if (line.newLine === null) return null
  return store.findings.find((item) => line.newLine !== null && line.newLine >= item.line_start && line.newLine <= item.line_end) ?? null
}

async function copyComment() {
  const finding = selectedFinding.value
  if (!finding) return
  await navigator.clipboard.writeText(`**${finding.severity.toUpperCase()}** ${finding.title}\n\n${finding.reasoning}\n\nSuggested fix: ${finding.suggestion}`)
  message.success('已复制 GitHub Review Comment')
}

onMounted(async () => {
  const runId = typeof route.params.runId === 'string' ? route.params.runId : null
  if (runId === 'demo-refresh-token' && store.runId !== runId) {
    store.loadDemo()
    return
  }
  if (runId && store.runId !== runId) {
    try {
      await store.loadRun(runId)
    } catch {
      message.error('Diff 加载失败')
    }
  }
})
</script>

<template>
  <div class="diff-page">
    <header class="diff-toolbar">
      <RouterLink :to="store.runId ? `/review/${store.runId}` : '/review'">
        <NButton quaternary circle title="返回驾驶舱">
          <template #icon>
            <ArrowLeft :size="18" />
          </template>
        </NButton>
      </RouterLink>
      <div><span><FileDiff :size="14" /> Review Diff</span><h1>{{ store.runId ?? '未选择运行' }}</h1></div>
      <NButton :disabled="!selectedFinding" secondary @click="copyComment">
        <template #icon>
          <Copy :size="15" />
        </template>复制 PR Comment
      </NButton>
    </header>
    <div v-if="lines.length" class="diff-layout">
      <section class="diff-code scrollbar" aria-label="代码差异">
        <button v-for="(line, index) in lines" :key="index" type="button" class="diff-line mono" :class="[line.kind, { flagged: findingAt(line) }]" @click="selectedId = findingAt(line)?.id ?? selectedId">
          <span>{{ line.oldLine ?? '' }}</span><span>{{ line.newLine ?? '' }}</span><code>{{ line.content }}</code>
        </button>
      </section>
      <aside class="finding-detail">
        <template v-if="selectedFinding">
          <span class="detail-kicker"><ShieldAlert :size="14" /> {{ selectedFinding.severity }} / {{ selectedFinding.category }}</span>
          <h2>{{ selectedFinding.title }}</h2>
          <p>{{ selectedFinding.reasoning }}</p>
          <h3>触发路径</h3><p>{{ selectedFinding.trigger_path }}</p>
          <h3>修复建议</h3><p>{{ selectedFinding.suggestion }}</p>
        </template>
        <NEmpty v-else description="选择带标记的代码行查看 Finding" />
      </aside>
    </div>
    <NEmpty v-else class="page-empty" description="该运行尚未保存 Diff" />
  </div>
</template>

<style scoped>
.diff-page {
  min-height: calc(100vh - 3.5rem);
}

.diff-toolbar {
  align-items: center;
  border-bottom: 1px solid var(--color-border);
  display: grid;
  gap: var(--space-3);
  grid-template-columns: auto 1fr auto;
  min-height: 4.5rem;
  padding: var(--space-3) var(--space-5);
}

.diff-toolbar span,
.detail-kicker {
  align-items: center;
  color: var(--color-cyan);
  display: flex;
  font-family: var(--font-mono);
  font-size: 0.68rem;
  gap: var(--space-2);
  text-transform: uppercase;
}

.diff-toolbar h1 {
  font-family: var(--font-mono);
  font-size: 0.9rem;
  margin: var(--space-1) 0 0;
}

.diff-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(19rem, 28%);
}

.diff-code {
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
  min-height: calc(100vh - 8rem);
  overflow: auto;
  padding: var(--space-3) 0;
}

.diff-line {
  background: transparent;
  border: 0;
  color: var(--color-muted);
  cursor: default;
  display: grid;
  font-size: 0.75rem;
  grid-template-columns: 3rem 3rem minmax(max-content, 1fr);
  line-height: 1.65;
  min-height: 1.55rem;
  padding: 0;
  text-align: left;
  width: 100%;
}

.diff-line > span {
  border-right: 1px solid var(--color-border);
  color: var(--color-subtle);
  padding-right: var(--space-2);
  text-align: right;
}

.diff-line code {
  font-family: inherit;
  padding: 0 var(--space-3);
  white-space: pre;
}

.diff-line.add {
  background: color-mix(in srgb, var(--color-green) 10%, transparent);
}

.diff-line.remove {
  background: color-mix(in srgb, var(--color-red) 10%, transparent);
}

.diff-line.header {
  background: color-mix(in srgb, var(--color-blue) 10%, transparent);
  color: var(--color-blue);
  margin: var(--space-2) 0;
}

.diff-line.flagged {
  box-shadow: inset 3px 0 var(--color-red);
  cursor: pointer;
}

.diff-line.flagged:hover {
  background: color-mix(in srgb, var(--color-red) 18%, transparent);
}

.finding-detail {
  padding: var(--space-6);
}

.finding-detail h2 {
  font-size: 1.05rem;
  line-height: 1.35;
  margin: var(--space-3) 0 var(--space-5);
}

.finding-detail h3 {
  color: var(--color-text);
  font-size: 0.72rem;
  margin: var(--space-5) 0 var(--space-2);
  text-transform: uppercase;
}

.finding-detail p {
  color: var(--color-muted);
  font-size: 0.82rem;
  line-height: 1.65;
}

.page-empty {
  margin-top: 20vh;
}

@media (max-width: 800px) {
  .diff-layout {
    display: block;
  }

  .diff-code {
    border-right: 0;
    min-height: 25rem;
  }

  .finding-detail {
    border-top: 1px solid var(--color-border);
  }
}
</style>
