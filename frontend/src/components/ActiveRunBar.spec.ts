import { describe, expect, it } from 'vitest'

import { presentActiveRun } from '@/components/ActiveRunBar.vue'

describe('ActiveRunBar 展示模型', () => {
  it('为运行中的审查提供过程入口和不中断提示', () => {
    const view = presentActiveRun({
      runId: 'run-1', repository: 'acme/payments', stage: 'team_review', elapsedSeconds: 42,
      candidateCount: 3, connection: 'live', status: 'running',
    })

    expect(view.repository).toBe('acme/payments')
    expect(view.stage).toBe('专家并行审查')
    expect(view.elapsed).toBe('已用 42 秒')
    expect(view.actions).toEqual([{ label: '进入审查过程', to: '/review/run-1' }])
    expect(view.persistenceNotice).toBe('切换页面不会停止服务端审查。')
  })

  it('为终态审查同时提供过程和报告入口', () => {
    const view = presentActiveRun({
      runId: 'run-1', repository: 'acme/payments', stage: 'completed', elapsedSeconds: 67,
      candidateCount: 5, connection: 'closed', status: 'completed',
    })

    expect(view.actions).toEqual([
      { label: '查看过程', to: '/review/run-1' },
      { label: '查看报告', to: '/result/run-1' },
    ])
    expect(view.connection).toBe('审查已完成')
  })
})
