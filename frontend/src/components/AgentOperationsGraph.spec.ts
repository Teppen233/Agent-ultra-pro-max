import { describe, expect, it } from 'vitest'

import * as reviewStore from '@/stores/review'

describe('AgentOperationsGraph 展示模型', () => {
  it('按 context 分组时不折叠同角色的不同实例', () => {
    const groupAgentInstances = (reviewStore as Record<string, unknown>).groupAgentInstances
    expect(groupAgentInstances).toBeTypeOf('function')
    if (typeof groupAgentInstances !== 'function') return

    const groups = groupAgentInstances([
      { id: 'defect:ctx-1', role: 'defect', contextId: 'ctx-1' },
      { id: 'intent:ctx-1', role: 'intent', contextId: 'ctx-1' },
      { id: 'defect:ctx-2', role: 'defect', contextId: 'ctx-2' },
      { id: 'intent:ctx-2', role: 'intent', contextId: 'ctx-2' },
      { id: 'defect:ctx-3', role: 'defect', contextId: 'ctx-3' },
      { id: 'intent:ctx-3', role: 'intent', contextId: 'ctx-3' },
    ]) as Array<{ contextId: string; agents: Array<{ id: string }> }>

    expect(groups.map((group) => [group.contextId, group.agents.map((agent) => agent.id)]))
      .toEqual([
        ['ctx-1', ['defect:ctx-1', 'intent:ctx-1']],
        ['ctx-2', ['defect:ctx-2', 'intent:ctx-2']],
        ['ctx-3', ['defect:ctx-3', 'intent:ctx-3']],
      ])
  })
})
