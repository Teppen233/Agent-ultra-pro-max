import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { BenchmarkEntrySummary, Finding, RunDetail } from '@/types'

import BenchmarkView from './BenchmarkView.vue'

const ENTRY: BenchmarkEntrySummary = {
  run_id: 'run-1',
  repository: 'ai-code-review-evaluation/sentry-greptile',
  repository_name: 'sentry-greptile',
  pr_url: 'https://github.com/ai-code-review-evaluation/sentry-greptile/pull/1',
  pr_number: 1,
  status: 'ready',
  created_at: 100,
  completed_at: 140,
}

const FINDING: Finding = {
  id: 'F1',
  category: 'security',
  severity: 'high',
  confidence: 0.9,
  file: 'src/auth.ts',
  line_start: 24,
  line_end: 28,
  title: '越权访问',
  reasoning: '缺少资源所有权校验。',
  trigger_path: 'GET /projects/:id',
  suggestion: '读取资源后校验当前用户。',
  verdict: 'keep',
}

const RUN_DETAIL: RunDetail = {
  run_id: ENTRY.run_id,
  diff: null,
  report: '# Review',
  events: [
    { timestamp: 100, type: 'run' },
    { timestamp: 140, type: 'report', markdown: '# Review', findings: [FINDING] },
  ],
}

function response(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }))
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/benchmark', component: BenchmarkView },
      { path: '/review/:runId?', component: { template: '<div />' } },
      { path: '/review/:runId/diff', component: { template: '<div />' } },
    ],
  })
}

function mountView() {
  const router = makeRouter()
  const host = defineComponent({
    components: { BenchmarkView, NMessageProvider },
    template: '<NMessageProvider><BenchmarkView /></NMessageProvider>',
  })
  return mount(host, { global: { plugins: [router] } })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('BenchmarkView', () => {
  it('shows guidance when no audits have been added', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({ capacity: 5, count: 0, entries: [] })))
    const wrapper = mountView()

    await flushPromises()

    expect(wrapper.text()).toContain('还没有加入 Benchmark 的审计')
    expect(wrapper.text()).toContain('勾选“加入 Benchmark”')
    expect(wrapper.text()).not.toContain('命中率')
  })

  it('shows a saved repository and its existing findings', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => response({ capacity: 5, count: 1, entries: [ENTRY] }))
      .mockImplementationOnce(() => response({ entry: ENTRY, run: RUN_DETAIL }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mountView()

    await flushPromises()

    expect(wrapper.text()).toContain('sentry-greptile')
    expect(wrapper.text()).toContain('PR #1')
    expect(wrapper.text()).toContain('越权访问')
    expect(wrapper.text()).toContain('40 秒')
    expect(wrapper.get('[aria-label="查看完整审计"]').attributes('href')).toContain(
      `/review/${ENTRY.run_id}`,
    )
    expect(fetchMock).toHaveBeenCalledWith('/api/benchmark/entries/run-1')
  })

  it('shows progress for a running audit without fake result metrics', async () => {
    const runningEntry = { ...ENTRY, status: 'running' as const, completed_at: null }
    const fetchMock = vi.fn(() =>
      response({ capacity: 5, count: 1, entries: [runningEntry] }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mountView()

    await flushPromises()

    expect(wrapper.text()).toContain('审计中')
    expect(wrapper.text()).toContain('审计完成后将在这里显示原始结果')
    expect(wrapper.text()).not.toContain('全部问题')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
