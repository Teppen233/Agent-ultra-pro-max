import type { BenchmarkSummary } from '@/contracts'

export interface BenchmarkPresentation {
  kind: 'real' | 'offline' | 'unavailable'
  title: string
  completed: string
  caught: string
  rate: string
  rateLabel: string
  elapsed: string
  note: string
}

const percent = (value: number): string => `${(value * 100).toFixed(1)}%`

/** 只允许明确离线标识的数据使用离线观察率，绝不回填伪造成绩。 */
export const presentBenchmark = (summary: BenchmarkSummary | null): BenchmarkPresentation => {
  if (!summary) {
    return {
      kind: 'unavailable',
      title: '评测数据暂不可用',
      completed: '暂无数据',
      caught: '暂无数据',
      rate: '暂无数据',
      rateLabel: '命中率',
      elapsed: '暂无数据',
      note: '连接评测服务后显示实际完成结果。',
    }
  }
  const real = summary.runner === 'real' && !summary.offline
  const rate = real ? summary.real_catch_rate : summary.observed_offline_catch_rate
  return {
    kind: real ? 'real' : 'offline',
    title: real ? '真实在线评测结果' : '离线评测观察结果',
    completed: String(summary.completed_cases),
    caught: String(summary.caught_cases),
    rate: rate === null ? '暂无数据' : percent(rate),
    rateLabel: real ? '真实命中率' : '离线观察命中率',
    elapsed: `${summary.elapsed_seconds.toFixed(1)}s`,
    note: real ? '仅统计实际完成的 ready 案例。' : '离线观察值，不计入真实命中率。',
  }
}

/** Demo 不请求后端；真实运行只在尚未水合时获取最终 JSON。 */
export const shouldFetchFinalResult = (input: { isDemo: boolean; resultHydrated: boolean }): boolean =>
  !input.isDemo && !input.resultHydrated

interface ResultMetricInput {
  isDemo: boolean
  resultHydrated: boolean
  coverage: string[]
  elapsedSeconds: number
  demo?: { coverage: string[]; elapsedSeconds: number }
}

/** 将合法零值与“尚无数据”区分，演示数据只能从显式 Demo 分支进入。 */
export const presentResultMetrics = (input: ResultMetricInput) => {
  if (input.isDemo && input.demo) {
    return {
      coverageCount: String(input.demo.coverage.length),
      elapsed: `${Math.round(input.demo.elapsedSeconds)}s`,
      coverage: input.demo.coverage,
      demoLabel: '演示数据',
    }
  }
  if (!input.resultHydrated) {
    return { coverageCount: '暂无数据', elapsed: '暂无数据', coverage: [], demoLabel: '' }
  }
  return {
    coverageCount: String(input.coverage.length),
    elapsed: `${Math.round(input.elapsedSeconds)}s`,
    coverage: input.coverage,
    demoLabel: '',
  }
}
