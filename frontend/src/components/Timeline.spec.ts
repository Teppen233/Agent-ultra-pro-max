import { describe, expect, it } from 'vitest'

import * as timeline from '@/components/Timeline.vue'

describe('Timeline 工具事件标签', () => {
  it('将工具能力降级显示为“已降级”，而不是工具失败', () => {
    const labelEventType = (timeline as Record<string, unknown>).labelEventType
    expect(labelEventType).toBeTypeOf('function')
    if (typeof labelEventType !== 'function') return

    expect(labelEventType('tool.degraded')).toBe('已降级')
  })
})
