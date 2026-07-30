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
      files: ['src/auth.ts'], role: 'defect', completedChecks: [], pendingChecks: [],
    })).toEqual({
      fileSummary: '1 个文件 · src/auth.ts',
      inputSource: 'PR Diff + 上下文包',
      currentAction: '等待开始分析上下文',
      checkSummary: '计划检查：静态破坏、安全输入、资源生命周期',
      collaborationSummary: '等待 Verifier 或其他专家消息',
      candidateSummary: '尚未形成候选',
    })

    expect(presentAgentWork({
      status: 'completed', candidateCount: 2, mailboxCount: 1, toolCount: 3,
      files: ['src/auth.ts', 'src/session.ts'], role: 'defect',
      completedChecks: ['静态破坏', '安全输入'], pendingChecks: [],
    })).toMatchObject({
      currentAction: '已提交 2 个候选，等待 Verifier',
      checkSummary: '已完成：静态破坏、安全输入',
      collaborationSummary: '已处理 1 条协作消息',
      candidateSummary: '已提交 2 个候选等待验证',
    })
  })

  it('把运行级系统工具归约成共享工具链，而不是让每张卡片显示零工具', () => {
    const presentSharedToolchain = (operationsGraph as Record<string, unknown>).presentSharedToolchain
    expect(presentSharedToolchain).toBeTypeOf('function')
    if (typeof presentSharedToolchain !== 'function') return

    expect(presentSharedToolchain([
      { category: 'tool', eventType: 'tool.completed', actorType: 'system', action: '拉取 GitHub PR', status: 'completed' },
      { category: 'tool', eventType: 'tool.completed', actorType: 'system', action: '解析代码差异', status: 'completed' },
      { category: 'tool', eventType: 'tool.degraded', actorType: 'system', action: '读取相关代码', status: 'degraded' },
      { category: 'mailbox', eventType: 'mailbox.message', action: '完成专家审查', status: 'completed' },
    ])).toEqual({
      summary: '共享工具链：2 项完成 · 1 项降级',
      items: ['拉取 GitHub PR', '解析代码差异', '读取相关代码（降级）'],
    })
  })
})
