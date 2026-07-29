import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useReviewStore } from './review'
import type { PipelineEvent, Finding } from '../contracts'

const findingDefect: Finding = {
  id: 'f-001',
  producer: 'defect',
  category: '空指针解引用',
  severity: 'critical',
  confidence: 0.95,
  file: 'src/component.ts',
  line_start: 245,
  line_end: 260,
  title: '潜在的 NPE',
  description: '回调中可能为 null',
  trigger_condition: '当组件快速卸载时',
  impact: '应用崩溃',
  reasoning_summary: '竞态窗口分析',
  suggestion: '增加空检查',
}

const findingIntent: Finding = {
  id: 'f-002',
  producer: 'intent',
  category: '逻辑错误',
  severity: 'high',
  confidence: 0.88,
  file: 'src/apiWatch.ts',
  line_start: 180,
  line_end: 195,
  title: '返回值类型不一致',
  description: '文档声明与实现不符',
  trigger_condition: 'immediate flush 选项',
  impact: '运行时错误',
  reasoning_summary: '类型声明对比',
}

function makeEvent(overrides: Partial<PipelineEvent>): PipelineEvent {
  return {
    id: overrides.id ?? 'evt-test',
    run_id: overrides.run_id ?? 'run-test',
    sequence: overrides.sequence ?? 1,
    timestamp: overrides.timestamp ?? '2026-07-29T10:00:00.000Z',
    type: overrides.type ?? 'review.started',
    data: overrides.data ?? {},
  }
}

describe('review store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('初始状态正确', () => {
    const store = useReviewStore()
    expect(store.runId).toBe('')
    expect(store.status).toBe('idle')
    expect(store.stages).toHaveLength(6)
    expect(store.stages.every((s) => s.status === 'pending')).toBe(true)
    expect(store.agents).toHaveLength(3)
    expect(store.agents.every((a) => a.status === 'idle')).toBe(true)
    expect(store.candidates).toHaveLength(0)
  })

  it('review.started 初始化状态', () => {
    const store = useReviewStore()
    store.applyEvent(
      makeEvent({
        type: 'review.started',
        data: { pr_title: 'fix: bug', repo: 'test/repo' },
      })
    )

    expect(store.status).toBe('reviewing')
    expect(store.reviewTitle).toBe('fix: bug')
    // 初始化阶段应标记为已完成
    const initStage = store.stages.find((s) => s.key === 'init')
    expect(initStage?.status).toBe('completed')
    // 分析阶段应标记为运行中
    const analysisStage = store.stages.find((s) => s.key === 'analysis')
    expect(analysisStage?.status).toBe('running')
  })

  it('agent.started / agent.tool / agent.candidate / agent.completed 完整流程', () => {
    const store = useReviewStore()

    // agent.started
    store.applyEvent(
      makeEvent({ type: 'agent.started', data: { agent: 'defect' }, timestamp: '2026-07-29T10:00:02.000Z' })
    )
    const defectAgent = store.agents.find((a) => a.key === 'defect')
    expect(defectAgent?.status).toBe('running')

    // agent.tool
    store.applyEvent(
      makeEvent({ type: 'agent.tool', data: { agent: 'defect', tool: 'read_file', duration_ms: 45 } })
    )
    expect(defectAgent?.tools).toHaveLength(1)
    expect(defectAgent?.tools[0].tool).toBe('read_file')

    // agent.candidate
    store.applyEvent(
      makeEvent({
        type: 'agent.candidate',
        data: { agent: 'defect', finding: findingDefect },
      })
    )
    expect(store.candidates).toHaveLength(1)
    expect(store.candidates[0].verifierStatus).toBe('pending')
    expect(defectAgent?.candidatesCount).toBe(1)

    // agent.completed
    store.applyEvent(
      makeEvent({ type: 'agent.completed', data: { agent: 'defect', candidates_count: 1 } })
    )
    expect(defectAgent?.status).toBe('completed')
  })

  it('两个 Agent 并行 + verifier 接受和拒绝', () => {
    const store = useReviewStore()

    // 启动审查
    store.applyEvent(makeEvent({ type: 'review.started' }))

    // 并行启动两个 Agent
    store.applyEvent(makeEvent({ type: 'agent.started', data: { agent: 'defect' } }))
    store.applyEvent(makeEvent({ type: 'agent.started', data: { agent: 'intent' } }))

    // 各自产生候选
    store.applyEvent(
      makeEvent({ type: 'agent.candidate', data: { agent: 'defect', finding: findingDefect } })
    )
    store.applyEvent(
      makeEvent({ type: 'agent.candidate', data: { agent: 'intent', finding: findingIntent } })
    )

    // 各自完成
    store.applyEvent(makeEvent({ type: 'agent.completed', data: { agent: 'defect' } }))
    store.applyEvent(makeEvent({ type: 'agent.completed', data: { agent: 'intent' } }))

    // Verifier 开始
    store.applyEvent(makeEvent({ type: 'verifier.started' }))
    expect(store.status).toBe('verifying')
    const verifierAgent = store.agents.find((a) => a.key === 'verifier')
    expect(verifierAgent?.status).toBe('running')

    // Verifier 接受 f-001
    store.applyEvent(
      makeEvent({
        type: 'verifier.accepted',
        data: { finding_id: 'f-001', reason: '确认存在风险' },
      })
    )
    expect(store.candidates[0].verifierStatus).toBe('accepted')
    expect(store.candidates[0].verifierReason).toBe('确认存在风险')

    // Verifier 拒绝 f-002
    store.applyEvent(
      makeEvent({
        type: 'verifier.rejected',
        data: { finding_id: 'f-002', reason: '误报，类型已匹配' },
      })
    )
    expect(store.candidates[1].verifierStatus).toBe('rejected')
    expect(store.candidates[1].verifierReason).toBe('误报，类型已匹配')

    // Verifier 完成
    store.applyEvent(
      makeEvent({ type: 'verifier.completed', data: { accepted: 1, rejected: 1 } })
    )
    expect(verifierAgent?.status).toBe('completed')

    // 报告生成
    store.applyEvent(makeEvent({ type: 'report.generated', data: { url: '/report.md' } }))
    expect(store.reportUrl).toBe('/report.md')

    // 完成
    store.applyEvent(
      makeEvent({
        type: 'review.completed',
        data: { total_findings: 2, accepted: 1, rejected: 1 },
      })
    )
    expect(store.status).toBe('completed')
  })

  it('计算属性 acceptedFindings / rejectedFindings / pendingFindings', () => {
    const store = useReviewStore()

    store.applyEvent(
      makeEvent({ type: 'agent.candidate', data: { agent: 'defect', finding: findingDefect } })
    )
    store.applyEvent(
      makeEvent({ type: 'agent.candidate', data: { agent: 'intent', finding: findingIntent } })
    )

    // 全部 pending
    expect(store.acceptedFindings).toHaveLength(0)
    expect(store.rejectedFindings).toHaveLength(0)
    expect(store.pendingFindings).toHaveLength(2)

    // 接受一个
    store.applyEvent(
      makeEvent({ type: 'verifier.accepted', data: { finding_id: 'f-001' } })
    )
    expect(store.acceptedFindings).toHaveLength(1)
    expect(store.pendingFindings).toHaveLength(1)

    // 拒绝一个
    store.applyEvent(
      makeEvent({ type: 'verifier.rejected', data: { finding_id: 'f-002' } })
    )
    expect(store.rejectedFindings).toHaveLength(1)
    expect(store.pendingFindings).toHaveLength(0)
  })

  it('review.failed 正确设置错误状态', () => {
    const store = useReviewStore()
    store.applyEvent(makeEvent({ type: 'review.started' }))
    store.applyEvent(
      makeEvent({
        type: 'review.failed',
        data: { reason: '仓库克隆失败' },
      })
    )
    expect(store.status).toBe('failed')
    expect(store.error).toBe('仓库克隆失败')
  })

  it('applyEvents 批量处理事件', () => {
    const store = useReviewStore()
    const events: PipelineEvent[] = [
      makeEvent({ type: 'review.started', sequence: 1 }),
      makeEvent({ type: 'agent.started', sequence: 2, data: { agent: 'defect' } }),
      makeEvent({ type: 'agent.candidate', sequence: 3, data: { agent: 'defect', finding: findingDefect } }),
      makeEvent({ type: 'agent.completed', sequence: 4, data: { agent: 'defect' } }),
      makeEvent({ type: 'agent.started', sequence: 5, data: { agent: 'intent' } }),
      makeEvent({ type: 'agent.candidate', sequence: 6, data: { agent: 'intent', finding: findingIntent } }),
      makeEvent({ type: 'agent.completed', sequence: 7, data: { agent: 'intent' } }),
      makeEvent({ type: 'verifier.started', sequence: 8 }),
      makeEvent({ type: 'verifier.accepted', sequence: 9, data: { finding_id: 'f-001' } }),
      makeEvent({ type: 'verifier.rejected', sequence: 10, data: { finding_id: 'f-002' } }),
      makeEvent({ type: 'verifier.completed', sequence: 11 }),
      makeEvent({ type: 'review.completed', sequence: 12 }),
    ]

    store.applyEvents(events)

    expect(store.status).toBe('completed')
    expect(store.candidates).toHaveLength(2)
    expect(store.acceptedFindings).toHaveLength(1)
    expect(store.rejectedFindings).toHaveLength(1)
  })

  it('reset 恢复初始状态', () => {
    const store = useReviewStore()
    store.applyEvent(makeEvent({ type: 'review.started' }))
    store.applyEvent(makeEvent({ type: 'agent.started', data: { agent: 'defect' } }))
    store.applyEvent(
      makeEvent({ type: 'agent.candidate', data: { agent: 'defect', finding: findingDefect } })
    )

    store.reset()

    expect(store.runId).toBe('')
    expect(store.status).toBe('idle')
    expect(store.candidates).toHaveLength(0)
    expect(store.agents.every((a) => a.status === 'idle')).toBe(true)
    expect(store.stages.every((s) => s.status === 'pending')).toBe(true)
  })

  it('stageProgress 计算进度百分比', () => {
    const store = useReviewStore()
    // 初始 0%
    expect(store.stageProgress.percent).toBe(0)

    store.applyEvent(makeEvent({ type: 'review.started' }))
    // init 完成, analysis 运行中
    expect(store.stageProgress.completed).toBe(1)
    expect(store.stageProgress.percent).toBe(17)

    // 完成所有阶段
    const events: PipelineEvent[] = [
      makeEvent({ type: 'agent.started', sequence: 1, data: { agent: 'defect' } }),
      makeEvent({ type: 'agent.started', sequence: 2, data: { agent: 'intent' } }),
      makeEvent({ type: 'agent.completed', sequence: 3, data: { agent: 'defect' } }),
      makeEvent({ type: 'agent.completed', sequence: 4, data: { agent: 'intent' } }),
      makeEvent({ type: 'verifier.started', sequence: 5 }),
      makeEvent({ type: 'verifier.completed', sequence: 6 }),
      makeEvent({ type: 'report.generated', sequence: 7 }),
      makeEvent({ type: 'review.completed', sequence: 8 }),
    ]
    store.applyEvents(events)
    expect(store.stageProgress.percent).toBe(100)
  })

  it('totalDurationMs 正确计算耗时', () => {
    const store = useReviewStore()
    store.applyEvent(
      makeEvent({ type: 'review.started', timestamp: '2026-07-29T10:00:00.000Z' })
    )
    store.applyEvent(
      makeEvent({ type: 'review.completed', timestamp: '2026-07-29T10:00:05.000Z' })
    )
    expect(store.totalDurationMs).toBe(5000)
  })

  it('stage.failed 正确标记阶段失败并设置错误', () => {
    const store = useReviewStore()
    store.applyEvent(makeEvent({ type: 'review.started' }))
    store.applyEvent(
      makeEvent({
        type: 'stage.failed',
        data: { stage: 'analysis', reason: '分析超时' },
      })
    )
    const analysisStage = store.stages.find((s) => s.key === 'analysis')
    expect(analysisStage?.status).toBe('failed')
    expect(store.status).toBe('failed')
    expect(store.error).toContain('分析')
  })
})
