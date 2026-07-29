import { describe, expect, it } from 'vitest'

import type { BenchmarkSummary } from '@/contracts'
import {
  presentBenchmark,
  presentResultMetrics,
  presentResultStatus,
  shouldFetchFinalResult,
} from '@/pages/view-models'

const summary = (overrides: Partial<BenchmarkSummary> = {}): BenchmarkSummary => ({
  mode: 'quick', runner: 'real', offline: false, selected_cases: 5, completed_cases: 5,
  actually_run_ready_cases: 5, caught_cases: 3, real_catch_rate: 0.6,
  observed_offline_catch_rate: null, offline_results_excluded_from_real_rate: false,
  false_positive_count: 1, verifier_accepted_count: 3, verifier_rejected_count: 1,
  needs_human_review_cases: 0, timed_out_cases: 0, elapsed_seconds: 25.4,
  ...overrides,
})

describe('页面展示模型', () => {
  it('真实报告只以 resultHydrated 判断是否需要最终 JSON', () => {
    expect(shouldFetchFinalResult({ isDemo: false, resultHydrated: false })).toBe(true)
    expect(shouldFetchFinalResult({ isDemo: false, resultHydrated: true })).toBe(false)
    expect(shouldFetchFinalResult({ isDemo: true, resultHydrated: false })).toBe(false)
  })

  it('真实 Benchmark 使用后端字段，不用离线值冒充真实命中率', () => {
    expect(presentBenchmark(summary())).toMatchObject({
      kind: 'real', completed: '5', caught: '3', rate: '60.0%', rateLabel: '真实命中率', elapsed: '25.4s',
    })
  })

  it('fake/offline Benchmark 明确标注离线观察值', () => {
    expect(presentBenchmark(summary({
      runner: 'fake', offline: true, real_catch_rate: null,
      observed_offline_catch_rate: 0.4, offline_results_excluded_from_real_rate: true,
    }))).toMatchObject({
      kind: 'offline', rate: '40.0%', rateLabel: '离线观察命中率',
      note: '离线观察值，不计入真实命中率。',
    })
  })

  it('缺失 Benchmark 和未水合真实报告显示暂无数据', () => {
    expect(presentBenchmark(null)).toMatchObject({
      kind: 'unavailable', completed: '暂无数据', caught: '暂无数据', rate: '暂无数据', elapsed: '暂无数据',
    })
    expect(presentResultMetrics({ isDemo: false, resultHydrated: false, coverage: [], elapsedSeconds: 0 }))
      .toEqual({ coverageCount: '暂无数据', elapsed: '暂无数据', coverage: [], demoLabel: '' })
  })

  it('合法的真实零值保持为零，Demo 数据只在 isDemo 分支出现', () => {
    expect(presentResultMetrics({ isDemo: false, resultHydrated: true, coverage: [], elapsedSeconds: 0 }))
      .toEqual({ coverageCount: '0', elapsed: '0s', coverage: [], demoLabel: '' })
    expect(presentResultMetrics({
      isDemo: true, resultHydrated: false, coverage: [], elapsedSeconds: 0,
      demo: { coverage: ['src/demo.ts'], elapsedSeconds: 6 },
    })).toEqual({ coverageCount: '1', elapsed: '6s', coverage: ['src/demo.ts'], demoLabel: '演示数据' })
  })

  it('按 completed、partial、failed 区分结果语义，Demo 使用离线耗时文案', () => {
    expect(presentResultStatus('completed', false)).toMatchObject({
      tone: 'success', eyebrow: '审查完成', findingNote: '经独立验证', elapsedNote: '服务端实际结果',
      listEyebrow: '已验证问题', findingVerdict: 'accepted', findingVerdictText: '',
    })
    expect(presentResultStatus('partial', false)).toMatchObject({
      tone: 'warning', eyebrow: '审查部分完成', findingNote: '部分结果，需人工复核',
      listEyebrow: '当前可用问题', findingVerdict: 'pending', findingVerdictText: '需人工复核',
    })
    expect(presentResultStatus('partial', false).findingNote).not.toContain('独立验证')
    expect(presentResultStatus('failed', false)).toMatchObject({
      tone: 'danger', eyebrow: '审查失败', findingNote: '失败前保留结果',
      listEyebrow: '当前可用问题', findingVerdict: 'pending', findingVerdictText: '需人工复核',
    })
    expect(presentResultStatus('completed', true).elapsedNote).toBe('离线演示耗时')
  })
})
