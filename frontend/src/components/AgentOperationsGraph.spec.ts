import { describe, expect, it } from 'vitest'

import * as operationsGraph from '@/components/AgentOperationsGraph.vue'
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

  it('把裸零计数转换成可读的工作摘要和当前动作', () => {
    const presentAgentWork = (operationsGraph as Record<string, unknown>).presentAgentWork
    expect(presentAgentWork).toBeTypeOf('function')
    if (typeof presentAgentWork !== 'function') return

    expect(presentAgentWork({
      status: 'waiting', candidateCount: 0, mailboxCount: 0, toolCount: 0,
      files: ['src/auth.ts'],
    })).toEqual({
      fileSummary: '1 个文件 · src/auth.ts',
      inputSource: 'PR Diff + 上下文包',
      currentAction: '等待并发槽位',
      toolSummary: '未主动调用',
      collaborationSummary: '暂无协作消息',
      candidateSummary: '暂无候选',
    })

    expect(presentAgentWork({
      status: 'completed', candidateCount: 2, mailboxCount: 1, toolCount: 3,
      files: ['src/auth.ts', 'src/session.ts'],
    })).toMatchObject({
      currentAction: '已提交 2 个候选，等待 Verifier',
      toolSummary: '主动工具 3 次',
      collaborationSummary: '协作消息 1 条',
      candidateSummary: '已提交 2 个候选',
    })
  })
})
