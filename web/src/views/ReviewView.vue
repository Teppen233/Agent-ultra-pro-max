<script setup lang="ts">
import {
  Archive,
  ChevronLeft,
  ChevronRight,
  FileCode2,
  FileText,
  GitBranch,
  PanelLeftClose,
  PanelRightClose,
  ShieldCheck,
} from 'lucide-vue-next'
import { NButton, NCollapse, NCollapseItem, NEmpty, NSkeleton, NTooltip, useMessage } from 'naive-ui'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
const leftRailCollapsed = ref(false)
const rightRailCollapsed = ref(false)
const eventsExpanded = ref(false)

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

async function start(prUrl: string, repoPath: string, addToBenchmark: boolean) {
  try {
    const runId = await store.startReview(prUrl, repoPath, addToBenchmark)
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
  void store.loadBenchmarkCapacity()
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
    <header class="run-bar">
      <div class="run-context">
        <span><ShieldCheck :size="14" /> REVIEW WORKSPACE</span>
        <strong>代码审查</strong>
      </div>
      <ReviewForm
        :loading="store.loading"
        :benchmark-count="store.benchmarkCount"
        :benchmark-capacity="store.benchmarkCapacity"
        :benchmark-available="store.benchmarkAvailable"
        @submit="start"
        @demo="demo"
      />
      <div class="run-state" :class="{ active: store.runId }">
        <span>{{ store.live ? 'LIVE' : store.runId ? 'REPLAY' : 'READY' }}</span>
        <b class="mono">{{ store.runId ?? 'NO RUN' }}</b>
      </div>
    </header>

    <section
      class="workbench"
      :class="{
        'left-collapsed': leftRailCollapsed,
        'right-collapsed': rightRailCollapsed,
      }"
    >
      <aside class="left-rail">
        <NTooltip placement="right">
          <template #trigger>
            <NButton
              class="rail-toggle left"
              quaternary
              circle
              size="small"
              :aria-label="leftRailCollapsed ? '展开调度栏' : '收起调度栏'"
              @click="leftRailCollapsed = !leftRailCollapsed"
            >
              <template #icon>
                <ChevronRight v-if="leftRailCollapsed" :size="15" />
                <PanelLeftClose v-else :size="15" />
              </template>
            </NButton>
          </template>
          {{ leftRailCollapsed ? '展开调度栏' : '收起调度栏' }}
        </NTooltip>

        <div class="rail-content">
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

          <NCollapse class="rail-utilities" arrow-placement="right">
            <NCollapseItem name="files">
              <template #header>
                <span class="utility-heading">
                  <GitBranch :size="13" /> 变更命中 <b>{{ fileCounts.length }}</b>
                </span>
              </template>
              <div v-if="fileCounts.length" class="file-list">
                <RouterLink
                  v-for="[file, count] in fileCounts"
                  :key="file"
                  :to="store.runId ? `/review/${store.runId}/diff` : '/review'"
                >
                  <FileCode2 :size="13" /><span>{{ file }}</span><b>{{ count }}</b>
                </RouterLink>
              </div>
              <p v-else class="rail-empty">
                Finding 产生后按文件汇总。
              </p>
            </NCollapseItem>
            <NCollapseItem name="runs">
              <template #header>
                <span class="utility-heading">
                  <Archive :size="13" /> 最近运行 <b>{{ store.runs.length }}</b>
                </span>
              </template>
              <div v-if="store.runs.length" class="recent-list scrollbar">
                <RouterLink v-for="run in store.runs" :key="run.run_id" :to="`/review/${run.run_id}`">
                  <span :class="{ mono: !run.name }" :title="run.run_id">{{ run.name || run.run_id }}</span><i :class="run.status" />
                </RouterLink>
              </div>
              <p v-else class="rail-empty">
                暂无历史运行。
              </p>
            </NCollapseItem>
          </NCollapse>
        </div>
      </aside>

      <section class="center-stage">
        <AgentFlow
          :workflow-nodes="store.workflowNodes"
          :workflow-edges="store.workflowEdges"
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
        <ThoughtStream
          :events="store.events"
          :expanded="eventsExpanded"
          @toggle="eventsExpanded = !eventsExpanded"
        />
      </section>

      <aside class="findings-panel">
        <NTooltip placement="left">
          <template #trigger>
            <NButton
              class="rail-toggle right"
              quaternary
              circle
              size="small"
              :aria-label="rightRailCollapsed ? '展开结论栏' : '收起结论栏'"
              @click="rightRailCollapsed = !rightRailCollapsed"
            >
              <template #icon>
                <ChevronLeft v-if="rightRailCollapsed" :size="15" />
                <PanelRightClose v-else :size="15" />
              </template>
            </NButton>
          </template>
          {{ rightRailCollapsed ? '展开结论栏' : '收起结论栏' }}
        </NTooltip>

        <div class="rail-content">
          <header class="findings-header">
            <div>
              <h2>审查结论</h2>
              <span>
                确认 {{ store.retainedFindings.length }} · 待复核 {{ store.needsReviewCount }} · 排除
                {{ store.rejectedCount }}
              </span>
            </div>
            <div class="finding-actions">
              <NTooltip v-if="store.runId && store.report">
                <template #trigger>
                  <RouterLink :to="`/review/${store.runId}/report`">
                    <NButton quaternary circle aria-label="打开审查报告">
                      <template #icon>
                        <FileText :size="16" />
                      </template>
                    </NButton>
                  </RouterLink>
                </template>
                打开审查报告
              </NTooltip>
              <RouterLink v-if="store.runId && store.diff" :to="`/review/${store.runId}/diff`">
                <NButton quaternary circle aria-label="打开 Diff">
                  <template #icon>
                    <FileCode2 :size="16" />
                  </template>
                </NButton>
              </RouterLink>
            </div>
          </header>

          <div class="finding-list scrollbar">
            <template v-if="store.loading">
              <NSkeleton v-for="index in 3" :key="index" height="6rem" :sharp="true" />
            </template>
            <FindingCard
              v-for="finding in store.findings"
              v-else
              :key="finding.id"
              :finding="finding"
              :run-id="store.runId"
              @select-workflow="store.selectNode"
            />
            <NEmpty
              v-if="!store.loading && store.findings.length === 0"
              size="small"
              description="候选问题会在验证后进入这里"
            />
          </div>
        </div>
      </aside>
    </section>
  </div>
</template>

<style scoped>
.review-page {
  display: grid;
  grid-template-rows: 4.5rem minmax(0, 1fr);
  height: calc(100vh - var(--app-bar-height));
  min-height: 42rem;
  overflow: hidden;
}

.run-bar {
  align-items: center;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  display: grid;
  gap: var(--space-4);
  grid-template-columns: auto minmax(38rem, 1fr) minmax(10rem, auto);
  padding: 0 var(--space-4);
}

.run-context {
  display: grid;
  gap: 0.15rem;
}

.run-context span {
  align-items: center;
  color: var(--color-cyan);
  display: flex;
  font-family: var(--font-mono);
  font-size: 0.6rem;
  gap: var(--space-1);
}

.run-context strong {
  font-size: 0.92rem;
  font-weight: 600;
}

.run-state {
  border-left: 1px solid var(--color-border);
  display: grid;
  gap: 0.1rem;
  min-width: 0;
  padding-left: var(--space-4);
}

.run-state span {
  color: var(--color-subtle);
  font-family: var(--font-mono);
  font-size: 0.58rem;
}

.run-state.active span {
  color: var(--color-green);
}

.run-state b {
  font-size: 0.65rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench {
  display: grid;
  grid-template-columns: var(--left-rail-width) minmax(34rem, 1fr) var(--right-rail-width);
  min-height: 0;
  overflow: hidden;
  transition: grid-template-columns 220ms ease;
}

.workbench.left-collapsed {
  grid-template-columns: var(--collapsed-rail-width) minmax(34rem, 1fr) var(--right-rail-width);
}

.workbench.right-collapsed {
  grid-template-columns: var(--left-rail-width) minmax(34rem, 1fr) var(--collapsed-rail-width);
}

.workbench.left-collapsed.right-collapsed {
  grid-template-columns: var(--collapsed-rail-width) minmax(34rem, 1fr) var(--collapsed-rail-width);
}

.left-rail,
.findings-panel {
  background: var(--color-surface);
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  position: relative;
}

.left-rail {
  border-right: 1px solid var(--color-border);
}

.findings-panel {
  border-left: 1px solid var(--color-border);
}

.rail-content {
  height: 100%;
  overflow-y: auto;
  transition: opacity 140ms ease;
}

.left-collapsed .left-rail .rail-content,
.right-collapsed .findings-panel .rail-content {
  opacity: 0;
  pointer-events: none;
}

.rail-toggle {
  position: absolute;
  top: var(--space-3);
  z-index: 8;
}

.rail-toggle.left {
  right: var(--space-2);
}

.rail-toggle.right {
  left: var(--space-2);
}

.center-stage {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  min-height: 0;
  min-width: 0;
}

.rail-utilities {
  border-top: 1px solid var(--color-border);
  padding: 0 var(--space-3);
}

.finding-actions {
  align-items: center;
  display: flex;
  gap: var(--space-1);
}

.utility-heading {
  align-items: center;
  display: flex;
  font-size: 0.66rem;
  gap: var(--space-2);
  text-transform: uppercase;
}

.utility-heading b {
  color: var(--color-subtle);
  font-family: var(--font-mono);
  font-weight: 500;
}

.rail-utilities :deep(.n-collapse-item__header) {
  min-height: 2.5rem;
}

.rail-utilities :deep(.n-collapse-item__content-inner) {
  padding: 0 0 var(--space-3);
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
  font-size: 0.68rem;
  gap: var(--space-2);
  min-height: 1.9rem;
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
}

.recent-list a {
  grid-template-columns: minmax(0, 1fr) auto;
}

.recent-list {
  max-height: calc(var(--space-4) * 10);
  overflow-y: auto;
  padding-right: var(--space-1);
}

.recent-list span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  font-size: 0.68rem;
  line-height: 1.5;
  margin: 0;
}

.findings-header {
  align-items: center;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  height: 3.5rem;
  justify-content: space-between;
  padding: 0 var(--space-3) 0 3rem;
}

.findings-header h2 {
  font-size: 0.78rem;
  margin: 0;
}

.findings-header span {
  color: var(--color-muted);
  font-family: var(--font-mono);
  font-size: 0.61rem;
}

.finding-list {
  display: grid;
  gap: var(--space-2);
  max-height: calc(100vh - var(--app-bar-height) - 8rem);
  overflow-y: auto;
  padding: var(--space-3);
}

@media (max-width: 1450px) {
  .run-bar {
    grid-template-columns: auto minmax(34rem, 1fr) minmax(8rem, auto);
  }
}
</style>
