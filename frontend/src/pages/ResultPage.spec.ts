import { describe, expect, it } from 'vitest'

import { presentResultProcessLink } from '@/pages/ResultPage.vue'
import { presentReviewResultLink } from '@/pages/ReviewPage.vue'

describe('ResultPage 审查过程入口', () => {
  it.each(['pending', 'partial', 'failed', 'completed'] as const)(
    '%s 状态始终可以返回审查过程',
    (status) => {
      expect(presentResultProcessLink('run-return-path', status, { demo: '1' })).toEqual({
        label: '返回审查过程',
        to: { name: 'review', params: { runId: 'run-return-path' }, query: { demo: '1' } },
      })
    },
  )
})

describe('回放上下文路由', () => {
  it('历史 Replay 从报告返回过程时保留 replay=1', () => {
    expect(presentResultProcessLink('run-history', 'completed', { replay: '1' })).toEqual({
      label: '返回审查过程',
      to: { name: 'review', params: { runId: 'run-history' }, query: { replay: '1' } },
    })
  })

  it('历史 Replay 查看审查报告时也保留 replay=1', () => {
    expect(presentReviewResultLink('run-history', true, false)).toEqual({
      name: 'result', params: { runId: 'run-history' }, query: { replay: '1' },
    })
  })
})
