<script setup lang="ts">
import { Archive, FileCode2, GitBranch, ShieldCheck } from 'lucide-vue-next'
import { NButton, NEmpty, NSkeleton, useMessage } from 'naive-ui'
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AgentFlow from '@/components/AgentFlow.vue'
import DispatchBoard from '@/components/DispatchBoard.vue'
import FindingCard from '@/components/FindingCard.vue'
import ReplayControls from '@/components/ReplayControls.vue'
import ReviewForm from '@/components/ReviewForm.vue'
import ThoughtStream from '@/components/ThoughtStream.vue'
import { useReviewStore } from '@/stores/review'

const store = useReviewStore()
const route = useRoute()
const router = useRouter()
const message = useMessage()

const fileCounts = computed(() => {
  const counts = new Map<string, number>()
  for (const finding of store.findings) counts.set(finding.file, (counts.get(finding.file) ?? 0) + 1)
  return [...counts.entries()]
})

watch(
  () => store.error,
  (error) => {
    if (error) message.error(error)
  },
)

async function start(prUrl: string, repoPath: string) {
  try {
    const runId = await store.startReview(prUrl, repoPath)
    await router.replace(`/review/${runId}`)
  } catch {
    // The store exposes the actionable message through the toast watcher.
  }
}

async function demo() {
  await router.replace('/review/demo-refresh-token')
  store.playDemo()
}

function toggleReplay() {
  if (store.replaying) store.pauseReplay()
  else store.playReplay()
}

onMounted(() => {
  void store.loadRuns()
})

watch(
  () => route.params.runId,
  async (value) => {
    const runId = typeof value === 'string' ? value : null
    if (!runId) {
      store.reset()
      return
    }
    if (runId === 'demo-refresh-token') {
      store.loadDemo()
      return
    }
    try {
      await store.loadRun(runId)
    } catch {
      // The store reports API failures via toast.
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  store.pauseReplay()
  store.stopSource()
})

watch(
  () => route.query.mode,
  (mode) => {
    if (mode !== 'replay' || store.live || store.replayEvents.length === 0) return
    store.restartReplay()
  },
)
</script>

<template>
  <div class="review-page">
    <section class="command-band">
      <div class="command-heading">
        <div>
          <span class="eyebrow"><ShieldCheck :size="14" /> Multi-Agent 动态审查</span>
          <h1>代码审查驾驶舱</h1>
        </div>
        <span v-if="store.runId" class="run-id mono">RUN / {{ store.runId }}</span>
      </div>
      <ReviewForm :loading="store.loading" @submit="start" @demo="demo" />
    </section>

    <section class="cockpit">
      <aside class="left-rail">
        <DispatchBoard
          :nodes="store.workflowNodes"
          :log="store.dispatchLog"
          :elapsed="store.elapsedSeconds"
          :active="store.activeAgentCount"
          :peak="store.concurrencyPeak"
          :counts="store.taskCounts"
          :selected="store.selectedWorkflowNode"
          @select="store.selectNode"
        />
        <section class="file-section">
          <h2><GitBranch :size="14" /> 变更命中</h2>
          <div v-if="fileCounts.length" class="file-list">
            <RouterLink v-for="[file, count] in fileCounts" :key="file" :to="store.runId ? `/review/${store.runId}/diff` : '/review'">
              <FileCode2 :size="14" /><span>{{ file }}</span><b>{{ count }}</b>
            </RouterLink>
          </div>
          <p v-else class="rail-empty">
            Finding 出现后将在此按文件聚合
          </p>
        </section>
        <section class="recent-section">
          <h2><Archive :size="14" /> 最近运行</h2>
          <div v-if="store.runs.length" class="recent-list">
            <RouterLink v-for="run in store.runs.slice(0, 5)" :key="run.run_id" :to="`/review/${run.run_id}`">
              <span class="mono">{{ run.run_id }}</span><i :class="run.status" />
            </RouterLink>
          </div>
          <p v-else class="rail-empty">
            暂无历史运行
          </p>
        </section>
      </aside>

      <section class="center-stage">
        <AgentFlow
          :workflow-nodes="store.workflowNodes"
          :workflow-edges="store.workflowEdges"
          :layout-workflow-nodes="store.layoutWorkflowNodes"
          :layout-workflow-edges="store.layoutWorkflowEdges"
          :layout-key="store.runId"
          :selected-node-id="store.selectedNodeId"
          @select="store.selectNode"
        >
          <template #controls>
            <ReplayControls
              :index="store.replayIndex"
              :total="store.replayEvents.length"
              :playing="store.replaying"
              :speed="store.replaySpeed"
              :live="store.live"
              @restart="store.restartReplay"
              @previous="store.stepReplay(-1)"
              @toggle="toggleReplay"
              @next="store.stepReplay(1)"
              @seek="store.seekReplay"
              @speed="store.setReplaySpeed"
            />
          </template>
        </AgentFlow>
        <ThoughtStream :events="store.events" />
      </section>

      <aside class="findings-panel">
        <header>
          <div><h2>审查结论</h2><span>保留 {{ store.retainedFindings.length }} · 驳回 {{ store.rejectedCount }}</span></div>
          <RouterLink v-if="store.runId && store.diff" :to="`/review/${store.runId}/diff`">
            <NButton quaternary circle title="打开 Diff">
              <template #icon>
                <FileCode2 :size="17" />
              </template>
            </NButton>
          </RouterLink>
        </header>
        <div class="finding-list scrollbar">
          <template v-if="store.loading">
            <NSkeleton v-for="index in 3" :key="index" height="7rem" :sharp="true" />
          </template>
          <FindingCard
            v-for="finding in store.findings"
            v-else
            :key="finding.id"
            :finding="finding"
            :run-id="store.runId"
            @select-workflow="store.selectNode"
          />
          <NEmpty v-if="!store.loading && store.findings.length === 0" description="提交 PR 或播放 Replay 后，候选 Finding 会实时进入这里" />
        </div>
      </aside>
    </section>
  </div>
</template>

<style scoped>
.review-page {
  min-height: calc(100vh - 3.5rem);
}

.command-band {
  border-bottom: 1px solid var(--color-border);
  padding: var(--space-5);
}

.command-heading {
  align-items: flex-end;
  display: flex;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.eyebrow {
  align-items: center;
  color: var(--color-cyan);
  display: flex;
  font-family: var(--font-mono);
  font-size: 0.68rem;
  gap: var(--space-2);
  text-transform: uppercase;
}

h1 {
  font-size: 1.35rem;
  letter-spacing: 0;
  margin: var(--space-1) 0 0;
}

.run-id {
  color: var(--color-muted);
  font-size: 0.68rem;
}

.cockpit {
  display: grid;
  grid-template-columns: minmax(16rem, 21%) minmax(30rem, 49%) minmax(20rem, 30%);
  min-height: calc(100vh - 12.5rem);
}

.left-rail,
.center-stage {
  border-right: 1px solid var(--color-border);
}

.left-rail {
  max-height: calc(100vh - 12.5rem);
  overflow-y: auto;
}

.file-section,
.recent-section {
  border-bottom: 1px solid var(--color-border);
  padding: var(--space-4);
}

.file-section h2,
.recent-section h2 {
  align-items: center;
  display: flex;
  font-size: 0.72rem;
  gap: var(--space-2);
  margin: 0 0 var(--space-3);
  text-transform: uppercase;
}

.file-list,
.recent-list {
  display: grid;
  gap: var(--space-1);
}

.file-list a,
.recent-list a {
  align-items: center;
  border-radius: var(--radius-sm);
  color: var(--color-muted);
  display: grid;
  font-size: 0.72rem;
  gap: var(--space-2);
  min-height: 2rem;
  padding: var(--space-1) var(--space-2);
  text-decoration: none;
}

.file-list a {
  grid-template-columns: auto minmax(0, 1fr) auto;
}

.file-list a:hover,
.recent-list a:hover {
  background: var(--color-surface-raised);
  color: var(--color-text);
}

.file-list span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-list b {
  color: var(--color-amber);
  font-family: var(--font-mono);
}

.recent-list a {
  grid-template-columns: 1fr auto;
}

.recent-list i {
  background: var(--color-amber);
  border-radius: 50%;
  height: 0.4rem;
  width: 0.4rem;
}

.recent-list i.done {
  background: var(--color-green);
}

.rail-empty {
  color: var(--color-subtle);
  font-size: 0.72rem;
  line-height: 1.5;
}

.findings-panel header {
  align-items: center;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  height: 3.75rem;
  justify-content: space-between;
  padding: 0 var(--space-4);
}

.findings-panel h2 {
  font-size: 0.82rem;
  margin: 0;
}

.findings-panel header span {
  color: var(--color-muted);
  font-family: var(--font-mono);
  font-size: 0.65rem;
}

.finding-list {
  display: grid;
  gap: var(--space-3);
  max-height: calc(100vh - 16.25rem);
  min-height: 24rem;
  overflow-y: auto;
  padding: var(--space-3);
}

@media (max-width: 1100px) {
  .cockpit {
    grid-template-columns: 15rem minmax(24rem, 1fr);
  }

  .findings-panel {
    border-top: 1px solid var(--color-border);
    grid-column: 1 / -1;
  }

  .finding-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-height: none;
  }
}

@media (max-width: 720px) {
  .command-heading {
    align-items: flex-start;
    gap: var(--space-2);
  }

  .run-id {
    max-width: 9rem;
    overflow-wrap: anywhere;
    text-align: right;
  }

  .cockpit {
    display: block;
  }

  .left-rail,
  .center-stage {
    border-right: 0;
  }

  .finding-list {
    grid-template-columns: 1fr;
  }
}
</style>
