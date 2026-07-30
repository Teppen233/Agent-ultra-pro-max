import { describe, expect, it } from 'vitest'

import {
  presentCaseTargetStatus,
  presentRepositoryBenchmark,
} from '@/components/RepositoryBenchmarkMatrix.vue'
import type { RepositoryBenchmarkSummary } from '@/contracts'

const repository = (overrides: Partial<RepositoryBenchmarkSummary> = {}): RepositoryBenchmarkSummary => ({
  repository: 'sentry',
  language: 'Python',
  total_cases: 1,
  verified_cases: 1,
  executed_cases: 1,
  target_caught: 0,
  other_findings: 4,
  rejected_count: 2,
  elapsed_seconds: 319.87,
  status: 'partial',
  latest_run_id: 'run-20260730-012450-d90a1b5b',
  catch_rate: 0,
  observed_offline_catch_rate: null,
  cases: [],
  ...overrides,
})

describe('RepositoryBenchmarkMatrix 展示模型', () => {
  it('未运行仓库显示待评测而不是伪造的 0% 命中率', () => {
    expect(presentRepositoryBenchmark(repository({
      status: 'pending', total_cases: 0, verified_cases: 0, executed_cases: 0,
      target_caught: 0, other_findings: 0, rejected_count: 0, elapsed_seconds: 0,
      latest_run_id: null, catch_rate: null,
    }), false)).toMatchObject({
      status: '待评测', catchRate: '暂无数据', targetStatus: '暂无判定', canOpenRun: false,
    })
  })

  it('缺少数据的仓库显示待补齐', () => {
    expect(presentRepositoryBenchmark(repository({
      status: 'needs_data', total_cases: 0, verified_cases: 0, executed_cases: 0,
      target_caught: 0, other_findings: 0, rejected_count: 0, elapsed_seconds: 0,
      latest_run_id: null, catch_rate: null,
    }), false)).toMatchObject({ status: '待补齐', targetStatus: '暂无判定' })
  })

  it('离线 Fake 结果醒目标注为离线链路验证，但不伪造运行或回放入口', () => {
    expect(presentRepositoryBenchmark(repository(), true)).toMatchObject({
      status: '部分完成', catchRate: '未命中', offlineNotice: '离线链路验证',
      elapsed: '319.87s', canOpenRun: false, runPath: '', replayPath: '',
      unavailableRunNotice: '离线结果无运行回放',
    })
  })

  it('未完成的案例不以 caught=false 伪造成目标未命中', () => {
    expect(presentCaseTargetStatus({
      case_id: 'sentry-pending', project: 'sentry', language: 'Python', status: 'partial',
      elapsed_seconds: 2, timed_out: false, run_id: null,
      judge: {
        caught: false, matched_finding_id: null, location_match: false, semantic_match: false,
        used_line_tolerance: null, needs_human_review: false, reason: '运行中断',
        false_positive_count: 0, verifier_accepted_count: 0, verifier_rejected_count: 0,
      },
    })).toBe('暂无判定')
  })
})
