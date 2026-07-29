import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import type { PipelineEvent } from '@/contracts'
import { useReviewStore } from '@/stores/review'

const event = (
  sequence: number,
  type: PipelineEvent['type'],
  data: PipelineEvent['data'],
): PipelineEvent => ({
  id: `evt-${sequence}`,
  run_id: 'run-demo',
  sequence,
  timestamp: `2026-07-30T01:00:0${sequence}Z`,
  type,
  data,
})

describe('Review Store 事件归约', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('将启动、候选、拒绝和终态归约为可展示状态', () => {
    const store = useReviewStore()

    ;[
      event(1, 'review.started', { repository: 'reviewcrew/demo', title: '修复权限边界' }),
      event(2, 'agent.started', { agent: 'defect', label: '缺陷专家' }),
      event(3, 'agent.candidate', {
        agent: 'defect',
        finding: {
          id: 'finding-1',
          severity: 'high',
          category: 'security',
          title: '缺少资源归属校验',
          description: '攻击者可以修改其他项目的资源。',
          file: 'src/api/resource.ts',
          line_start: 42,
          line_end: 46,
          trigger: '使用非当前租户的资源 ID 发起请求',
          impact: '导致跨租户数据篡改',
          evidence: [],
          confidence: 0.93,
          recommendation: '查询时同时约束 tenant_id。',
        },
      }),
      event(4, 'verifier.rejected', {
        finding_id: 'finding-1',
        reason: '上游路由已经强制校验资源归属。',
      }),
      event(5, 'review.completed', { status: 'completed' }),
    ].forEach(store.applyEvent)

    expect(store.status).toBe('completed')
    expect(store.stage).toBe('completed')
    expect(store.agents.defect.status).toBe('running')
    expect(store.candidates).toHaveLength(1)
    expect(store.candidates[0]?.verdict).toBe('rejected')
    expect(store.findings).toHaveLength(0)
    expect(store.lastSequence).toBe(5)
  })

  it('忽略重复和倒序事件，终态后不再接受新事件', () => {
    const store = useReviewStore()

    store.applyEvent(event(1, 'review.started', {}))
    store.applyEvent(event(2, 'review.completed', { status: 'partial' }))
    store.applyEvent(event(2, 'review.completed', { status: 'failed' }))
    store.applyEvent(event(3, 'agent.started', { agent: 'intent' }))

    expect(store.status).toBe('partial')
    expect(store.lastSequence).toBe(2)
    expect(store.events).toHaveLength(2)
    expect(store.agents.intent.status).toBe('waiting')
  })

  it('用最终报告补全实时摘要并可安全开始下一次回放', () => {
    const store = useReviewStore()
    store.applyEvent(event(1, 'review.started', {}))
    store.applyEvent(event(2, 'agent.candidate', {
      agent: 'intent', finding_id: 'finding-2', file: 'src/state.ts', line: 88, severity: 'medium',
    }))
    store.applyEvent(event(3, 'verifier.accepted', { finding_id: 'finding-2', verdict: 'confirmed' }))

    store.hydrateResult({
      run_id: 'run-demo',
      status: 'completed',
      repository: 'reviewcrew/demo',
      base_sha: 'abc',
      head_sha: 'def',
      findings: [{
        id: 'finding-2', producer: 'intent', category: 'logic', severity: 'medium', confidence: 0.91,
        file: 'src/state.ts', line_start: 88, line_end: 91, title: '状态遗漏', description: '状态不会收敛。',
        trigger_condition: '请求被取消', impact: '任务永远显示运行中', suggestion: '在 finally 中收敛状态。', evidence: [],
      }],
      rejected_count: 0,
      coverage: ['src/state.ts'],
      warnings: [],
      started_at: '2026-07-30T01:00:00Z',
      completed_at: '2026-07-30T01:00:03Z',
      elapsed_seconds: 3,
    })

    expect(store.findings[0]?.title).toBe('状态遗漏')
    expect(store.repository).toBe('reviewcrew/demo')

    store.reset()
    expect(store.status).toBe('idle')
    expect(store.events).toHaveLength(0)
    expect(store.lastSequence).toBe(0)
  })

  it('将 Verifier 与报告事件映射到阶段进度', () => {
    const store = useReviewStore()
    store.applyEvent(event(1, 'review.started', {}))
    store.applyEvent(event(2, 'verifier.started', { agent: 'verifier' }))
    store.applyEvent(event(3, 'verifier.completed', { accepted: 1 }))
    store.applyEvent(event(4, 'report.generated', { status: 'completed' }))
    store.applyEvent(event(5, 'review.completed', { status: 'completed' }))

    expect(store.stages.find((stage) => stage.id === 'verifying')?.status).toBe('completed')
    expect(store.stages.find((stage) => stage.id === 'reporting')?.status).toBe('completed')
  })
})
