<template>
  <div class="history-page">
    <div class="page-header">
      <h2>审查历史</h2>
      <button class="btn" @click="loadHistory" :disabled="loading">
        <span v-if="loading" class="spinner"></span>
        {{ loading ? '加载中...' : '刷新' }}
      </button>
    </div>

    <!-- 统计 -->
    <div class="stats-row">
      <div class="stat-card"><span class="stat-value">{{ summaries.length }}</span><span class="stat-label">总审查数</span></div>
      <div class="stat-card"><span class="stat-value">{{ totalFindings }}</span><span class="stat-label">总发现</span></div>
      <div class="stat-card"><span class="stat-value">{{ avgTime }}</span><span class="stat-label">平均耗时</span></div>
    </div>

    <div v-if="loading && !summaries.length" class="loading-state">
      <div class="skeleton" v-for="i in 4" :key="i"></div>
    </div>
    <div v-else-if="error" class="status-banner error">{{ error }}<button class="btn btn-sm" @click="loadHistory">重试</button></div>
    <div v-else-if="!summaries.length" class="empty-state">暂无审查记录，去<router-link to="/">发起一次审查</router-link>吧。</div>

    <div v-else class="history-list">
      <div v-for="s in summaries" :key="s.run_id" class="history-card" :class="s.status" @click="viewDetail(s.run_id)">
        <div class="card-left">
          <span class="status-dot" :class="s.status"></span>
          <div><div class="repo-name">{{ formatRepo(s.repository) }}</div><div class="run-id">Run: {{ s.run_id }}</div></div>
        </div>
        <div class="card-center">
          <span class="finding-count">{{ s.finding_count }} 发现</span>
          <span v-if="s.rejected_count" class="rejected">+{{ s.rejected_count }} 拒绝</span>
        </div>
        <div class="card-right">
          <span class="elapsed">{{ formatElapsed(s.elapsed_seconds) }}</span>
          <span class="time">{{ formatTime(s.started_at) }}</span>
        </div>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="selectedRun" class="detail-overlay" @click.self="selectedRun = null">
      <div class="detail-modal">
        <div class="modal-header">
          <h3>{{ formatRepo(detailRepo) }} — {{ selectedRun }}</h3>
          <button class="close-btn" @click="selectedRun = null">&times;</button>
        </div>
        <div class="modal-body">
          <div v-if="detailLoading" class="loading-text">加载中...</div>
          <div v-else-if="detailError" class="error-msg">{{ detailError }}</div>
          <template v-else>
            <!-- 管线图 -->
            <PipelineGraph :stages="detailStages" :agents="detailAgents" :findings="(store.candidates as any)" @select-agent="()=>{}" />
            <!-- 阶段耗时 -->
            <div class="timing-stats">
              <div class="timing-card" v-for="t in stageTimings" :key="t.stage">
                <span class="timing-stage">{{ t.label }}</span>
                <span class="timing-dur" :class="t.status">{{ t.duration }}</span>
              </div>
            </div>
            <!-- 双栏 -->
            <div class="detail-columns">
              <div class="detail-col">
                <h4>事件时间线</h4>
                <div class="timeline">
                  <div class="tl-item" v-for="ev in detailEvents" :key="ev.id" :class="cssClass(ev.type)">
                    <span class="tl-time">{{ formatTimeShort(ev.timestamp) }}</span>
                    <span class="tl-type">{{ eventLabel(ev.type) }}</span>
                    <span class="tl-detail">{{ eventDetail(ev) }}</span>
                  </div>
                </div>
              </div>
              <div class="detail-col">
                <h4>审查发现 ({{ detailFindings.length }})</h4>
                <FindingCard v-for="entry in detailFindings" :key="entry.finding.id" :finding="entry.finding" :verifier-status="entry.verifierStatus" :verifier-reason="entry.verifierReason" :show-detail="true" />
                <div v-if="!detailFindings.length" class="empty">✅ 审查通过，未发现缺陷</div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// @ts-nocheck
import { ref, computed, onMounted } from 'vue'
import { useReviewStore } from '../stores/review'
import type { StageInfo, AgentInfo } from '../stores/review'
import { getStatus } from '../api/client'
import FindingCard from '../components/FindingCard.vue'
import PipelineGraph from '../components/PipelineGraph.vue'

const store = useReviewStore()

interface RunSummary { run_id: string; status: string; repository: string; finding_count: number; rejected_count: number; elapsed_seconds: number; started_at: string }
const summaries = ref<RunSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const selectedRun = ref<string | null>(null)
const detailRepo = ref('')
const detailLoading = ref(false)
const detailError = ref<string | null>(null)
const detailFindings = ref<Array<{ finding: any; verifierStatus: 'pending' | 'accepted' | 'rejected'; verifierReason?: string }>>([])
const detailEvents = ref<any[]>([])
const detailStages = ref<StageInfo[]>([])
const detailAgents = ref<AgentInfo[]>([])

const totalFindings = computed(() => summaries.value.reduce((s, r) => s + r.finding_count, 0))
const avgTime = computed(() => {
  if (!summaries.value.length) return '--'
  return formatElapsed(summaries.value.reduce((s, r) => s + r.elapsed_seconds, 0) / summaries.value.length)
})

const stageTimings = computed(() => {
  const evs = detailEvents.value
  const stages: Record<string, any> = {}
  for (const e of evs) {
    if (e.type === 'stage.started') stages[e.data?.stage || '?'] = { label: e.data?.label || e.data?.stage, start: new Date(e.timestamp).getTime(), end: 0, status: 'running' }
    if (e.type === 'stage.completed' || e.type === 'stage.failed') { const s = stages[e.data?.stage || '?']; if (s) { s.end = new Date(e.timestamp).getTime(); s.status = e.type === 'stage.failed' ? 'failed' : 'done' } }
  }
  return Object.entries(stages).map(([stage, v]) => ({ stage, label: v.label, status: v.status, duration: v.end ? formatElapsed((v.end - v.start) / 1000) : '--' }))
})

async function viewDetail(runId: string) {
  selectedRun.value = runId; detailLoading.value = true; detailError.value = null
  try {
    const status = await getStatus(runId)
    store.reset(); store.applyEvents(status.events || [])
    detailEvents.value = status.events || []
    detailRepo.value = status.events?.[0]?.data?.repo || ''

    const sm: Record<string, StageInfo> = {}
    for (const k of ['loading_pr','building_context','reviewing','verifying','generating_report']) {
      sm[k] = { key: k, name: {loading_pr:'加载 PR',building_context:'构建上下文',reviewing:'并行审查',verifying:'结果验证',generating_report:'生成报告'}[k]||k, status: 'pending' }
    }
    for (const e of status.events||[]) {
      if (e.type==='stage.started' && sm[e.data?.stage]) sm[e.data.stage].status = 'completed'
      if (e.type==='stage.failed' && sm[e.data?.stage]) sm[e.data.stage].status = 'failed'
    }
    detailStages.value = ['loading_pr','building_context','reviewing','verifying','generating_report'].map(k => sm[k])
    detailAgents.value = store.agents

    const aid = new Set((status.events||[]).filter((e:any)=>e.type==='verifier.accepted').map((e:any)=>e.data?.finding_id))
    const rid = new Set((status.events||[]).filter((e:any)=>e.type==='verifier.rejected').map((e:any)=>e.data?.finding_id))
    detailFindings.value = store.candidates.map(c => ({
      finding: c.finding,
      verifierStatus: (aid.has(c.finding.id)?'accepted':rid.has(c.finding.id)?'rejected':'pending') as 'pending'|'accepted'|'rejected',
      verifierReason: ''
    }))
  } catch { detailError.value = '加载详情失败' }
  finally { detailLoading.value = false }
}

async function loadHistory() {
  loading.value = true; error.value = null
  try { const res = await fetch('/api/runs/summary'); if(!res.ok) throw Error(''); summaries.value = (await res.json()).runs||[] }
  catch { error.value = '加载历史失败，请检查后端服务' }
  finally { loading.value = false }
}

const EL: Record<string,string> = {'review.started':'审查启动','review.completed':'审查完成','review.failed':'审查失败','stage.started':'阶段开始','stage.completed':'阶段完成','stage.failed':'阶段失败','agent.started':'Agent启动','agent.completed':'Agent完成','agent.failed':'Agent失败','verifier.started':'验证开始','verifier.accepted':'确认','verifier.rejected':'拒绝','verifier.completed':'验证完成'}
function eventLabel(t: string) { return EL[t]||t }
function eventDetail(ev: any) { const d=ev.data||{}; return d.agent_name||d.stage||(d.findings!==undefined?d.findings+' 发现':'')||d.reason||'' }
function formatTimeShort(ts: string) { return ts?new Date(ts).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'' }
function cssClass(t: string) { return t.replace(/\./g,'_') }
function formatRepo(r: string) { return r?r.replace('https://github.com/','').replace(/\/pull\/\d+.*/,''):'Unknown' }
function formatElapsed(s: number) { if(!s) return '--'; return s<60?`${s.toFixed(0)}s`:`${(s/60).toFixed(1)}min` }
function formatTime(ts: string) { if(!ts) return ''; return new Date(ts).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) }

onMounted(loadHistory)
</script>

<style scoped>
.history-page { max-width: 960px; margin: 0 auto }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px }
.page-header h2 { font-size: 22px }
.btn { padding: 8px 20px; border: none; border-radius: var(--radius); background: var(--color-primary); color: #fff; font-size: 13px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 6px }
.btn:disabled { opacity: .5; cursor: not-allowed }
.spinner { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,.3); border-top-color: #fff; border-radius: 50%; animation: spin .6s linear infinite }
@keyframes spin { to { transform: rotate(360deg) } }
.stats-row { display: grid; grid-template-columns: repeat(3,1fr); gap: 16px; margin-bottom: 24px }
.stat-card { background: var(--color-surface); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow); text-align: center }
.stat-value { display: block; font-size: 28px; font-weight: 700 }
.stat-label { font-size: 13px; color: var(--color-text-muted) }
.loading-state { padding: 24px 0 }
.skeleton { height: 60px; background: linear-gradient(90deg,var(--color-border) 25%,#e8ecf1 50%,var(--color-border) 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: 8px; margin-bottom: 8px }
@keyframes shimmer { 0%{background-position:-200% 0} 100%{background-position:200% 0} }
.empty-state { text-align: center; padding: 64px 0; color: var(--color-text-muted); font-size: 15px }
.empty-state a { color: var(--color-primary) }
.history-list { display: flex; flex-direction: column; gap: 8px }
.history-card { background: var(--color-surface); border-radius: var(--radius); padding: 14px 20px; box-shadow: var(--shadow); display: flex; align-items: center; justify-content: space-between; cursor: pointer; transition: box-shadow .15s; border-left: 3px solid var(--color-border) }
.history-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.1) }
.history-card.completed { border-left-color: var(--color-success) }
.history-card.failed { border-left-color: var(--color-danger) }
.history-card.partial { border-left-color: var(--color-warning) }
.card-left { display: flex; align-items: center; gap: 12px }
.status-dot { width: 8px; height: 8px; border-radius: 50% }
.status-dot.completed { background: var(--color-success) }
.status-dot.failed { background: var(--color-danger) }
.status-dot.running { background: var(--color-primary); animation: pulse 1s infinite }
.status-dot.partial { background: var(--color-warning) }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
.repo-name { font-size: 15px; font-weight: 600 }
.run-id { font-size: 11px; color: var(--color-text-muted); font-family: monospace }
.card-center { display: flex; gap: 8px; align-items: center }
.finding-count { font-size: 14px; font-weight: 600 }
.rejected { font-size: 12px; color: var(--color-text-muted) }
.card-right { display: flex; flex-direction: column; align-items: flex-end }
.elapsed { font-size: 14px; font-weight: 500 }
.time { font-size: 11px; color: var(--color-text-muted) }
.status-banner.error { background: #fef2f2; color: #991b1b; padding: 12px 16px; border-radius: var(--radius); display: flex; align-items: center; gap: 12px }
.btn-sm { padding: 6px 16px; border-radius: 4px; font-size: 13px; border: none; cursor: pointer; background: var(--color-primary); color: #fff }

.detail-overlay { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,.25); display: flex; align-items: center; justify-content: center }
.detail-modal { background: var(--color-surface); border-radius: 12px; width: 960px; max-width: 95vw; max-height: 92vh; display: flex; flex-direction: column; box-shadow: 0 8px 32px rgba(0,0,0,.15) }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--color-border) }
.modal-header h3 { font-size: 16px }
.close-btn { font-size: 24px; border: none; background: none; cursor: pointer; color: var(--color-text-muted) }
.modal-body { flex: 1; overflow-y: auto; padding: 16px }
.loading-text,.error-msg { text-align: center; padding: 32px; color: var(--color-text-muted) }
.empty { text-align: center; padding: 32px; color: var(--color-text-muted); font-size: 15px }

.timing-stats { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; padding: 12px; background: var(--color-bg); border-radius: var(--radius) }
.timing-card { display: flex; flex-direction: column; align-items: center; padding: 8px 14px; background: var(--color-surface); border-radius: 6px; min-width: 80px }
.timing-stage { font-size: 11px; color: var(--color-text-muted); white-space: nowrap }
.timing-dur { font-size: 15px; font-weight: 700 }
.timing-dur.done { color: var(--color-success) }
.timing-dur.failed { color: var(--color-danger) }

.detail-columns { display: grid; grid-template-columns: 2fr 3fr; gap: 20px; margin-top: 16px }
.detail-col h4 { font-size: 14px; margin-bottom: 10px }
.timeline { max-height: 400px; overflow-y: auto }
.tl-item { display: flex; align-items: center; gap: 8px; padding: 3px 8px; border-radius: 4px; font-size: 12px; border-left: 3px solid var(--color-border); margin-bottom: 2px }
.tl-item._review_started,.tl-item._review_completed { border-left-color: var(--color-primary) }
.tl-item._stage_failed,.tl-item._review_failed,.tl-item._agent_failed { border-left-color: var(--color-danger) }
.tl-item._verifier_accepted { border-left-color: var(--color-success) }
.tl-item._verifier_rejected { border-left-color: var(--color-warning) }
.tl-time { color: var(--color-text-muted); font-family: monospace; min-width: 60px }
.tl-type { font-weight: 600; min-width: 56px }
.tl-detail { color: var(--color-text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap }

@media (max-width: 768px) {
  .stats-row { grid-template-columns: 1fr }
  .history-card { flex-direction: column; gap: 8px; align-items: flex-start }
  .card-right { flex-direction: row; gap: 8px }
  .detail-columns { grid-template-columns: 1fr }
}
</style>
