import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'

import { fetchReview, parseEventLog, replayEventLog } from '@/api/client'
import type { PipelineEvent, ReviewResult } from '@/contracts'
import { useReviewStore } from '@/stores/review'


const event = (
  sequence: number,
  type: PipelineEvent['type'],
  data: PipelineEvent['data'],
): PipelineEvent => ({
  id: `evt-full-stack-${sequence}`,
  run_id: 'run-full-stack',
  sequence,
  timestamp: `2026-07-30T01:00:${String(sequence).padStart(2, '0')}Z`,
  type,
  data,
})

const backendEvents: PipelineEvent[] = [
  event(1, 'review.started', {
    mode: 'local',
    repository: 'fixture-repo',
    title: '本地审查 base → head',
  }),
  event(2, 'stage.started', { stage: 'loading_pr' }),
  event(3, 'stage.completed', { stage: 'loading_pr' }),
  event(4, 'agent.started', { agent: 'defect:ctx-contract', role: 'defect' }),
  event(5, 'agent.candidate', {
    agent: 'defect:ctx-contract',
    finding_id: 'finding-full-stack',
    file: 'access.py',
    line: 2,
    severity: 'high',
  }),
  event(6, 'agent.completed', { agent: 'defect:ctx-contract', role: 'defect' }),
  event(7, 'verifier.started', { agent: 'verifier' }),
  event(8, 'verifier.accepted', {
    finding_id: 'finding-full-stack',
    verdict: 'confirmed',
    confidence: 0.96,
  }),
  event(9, 'verifier.completed', { accepted: 1 }),
  event(10, 'report.generated', { status: 'completed' }),
  event(11, 'review.completed', { status: 'completed' }),
]

const backendResult: ReviewResult = {
  run_id: 'run-full-stack',
  status: 'completed',
  repository: 'fixture-repo',
  base_sha: 'base-sha',
  head_sha: 'head-sha',
  findings: [{
    id: 'finding-full-stack',
    producer: 'defect',
    category: 'security',
    severity: 'high',
    confidence: 0.96,
    file: 'access.py',
    line_start: 2,
    line_end: 2,
    title: '缺少资源所有权校验',
    description: '修改后的查询不再绑定当前用户。',
    trigger_condition: '攻击者提交其他用户的资源标识。',
    impact: '可能读取其他用户的数据。',
    suggestion: '恢复按用户限定的资源查询。',
    evidence: [{
      source: 'diff',
      file: 'access.py',
      start_line: 2,
      end_line: 2,
      description: '修改行移除了用户条件。',
      content: 'return repository.get(resource_id)',
    }],
    created_at: '2026-07-30T00:00:00Z',
  }],
  rejected_count: 0,
  coverage: ['access.py'],
  warnings: [],
  started_at: '2026-07-30T01:00:01Z',
  completed_at: '2026-07-30T01:00:11Z',
  elapsed_seconds: 10,
}


describe('Task13 全栈公开契约', () => {
  it('将生产 SSE、Replay 与最终结果归约为同一份完整前端状态', async () => {
    setActivePinia(createPinia())
    const store = useReviewStore()
    const log = backendEvents.map((item) => JSON.stringify(item)).join('\n')

    parseEventLog(log).forEach(store.applyEvent)

    expect(store.status).toBe('completed')
    expect(store.repository).toBe('fixture-repo')
    expect(store.title).toBe('本地审查 base → head')
    expect(store.candidates[0]?.verdict).toBe('accepted')
    expect(store.agents.defect.status).toBe('completed')
    expect(store.agents.verifier.status).toBe('completed')
    expect(store.reportReady).toBe(true)

    const response = await fetchReview('run-full-stack', async () => new Response(
      JSON.stringify(backendResult),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ))
    expect(response.kind).toBe('result')
    if (response.kind === 'result') store.hydrateResult(response.result)

    expect(store.resultHydrated).toBe(true)
    expect(store.findings[0]?.title).toBe('缺少资源所有权校验')
    expect(store.findings[0]?.evidence?.[0]?.content).toBe('return repository.get(resource_id)')
    expect(store.baseSha).toBe('base-sha')
    expect(store.headSha).toBe('head-sha')

    store.reset()
    await replayEventLog(log, store.applyEvent, {
      speed: 8,
      wait: async () => undefined,
    })

    expect(store.status).toBe('completed')
    expect(store.lastSequence).toBe(11)
    expect(store.candidates[0]?.verdict).toBe('accepted')
    expect(store.reportReady).toBe(true)
  })
})
