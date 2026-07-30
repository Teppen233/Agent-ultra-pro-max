import { describe, expect, it } from 'vitest'

import type { PipelineEvent } from '@/contracts'
import * as reviewStore from '@/stores/review'

const event = (type: string, data: Record<string, unknown>): PipelineEvent => ({
  id: `evt-${type}`,
  run_id: 'run-operations',
  sequence: 1,
  timestamp: '2026-07-30T01:00:00Z',
  type: type as PipelineEvent['type'],
  data,
})

describe('OperationFeed 事件分类', () => {
  it('将工具活动与 Mailbox 协作消息分成不同类别', () => {
    const classifyOperationEvent = (reviewStore as Record<string, unknown>).classifyOperationEvent
    expect(classifyOperationEvent).toBeTypeOf('function')
    if (typeof classifyOperationEvent !== 'function') return

    expect(classifyOperationEvent(event('tool.completed', {
      actor: 'context_builder', actor_type: 'system', tool_name: 'context.read_file', status: 'completed',
    }))).toBe('tool')
    expect(classifyOperationEvent(event('tool.degraded', {
      actor: 'github_pr_loader', actor_type: 'system', tool_name: 'git.load_diff', status: 'degraded',
    }))).toBe('tool')
    expect(classifyOperationEvent(event('mailbox.message', {
      sender: 'verifier', recipient: 'defect:ctx-1', kind: 'evidence_request', summary: '请求补证',
    }))).toBe('mailbox')
  })
})
