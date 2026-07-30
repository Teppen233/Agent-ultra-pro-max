# ReviewCrew 1.1.6.1 Frontend Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 600 秒硬上限内稳定运行 ReviewCrew，并通过全局任务条、真实 Agent 作战室、工具活动、倍速回放和五仓评测矩阵完整展示审查过程。

**Architecture:** 后端继续以持久化 `PipelineEvent` 作为实时 SSE 与 Replay 的唯一事实来源，新增公开的计划、工具和协作摘要事件；前端把 SSE 生命周期提升到应用级 Run Controller，页面只消费按 `run_id` 归约的状态。Benchmark 由后端聚合逐仓和逐案例结果，前端不扫描文件或推测成绩。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、pytest、Vue 3、Pinia、TypeScript、Vitest、Vite。

## Global Constraints

- 单个 PR 全流程硬上限为 600 秒，达到上限必须保存当前结果并返回 `partial`，不得后台继续。
- 默认并发为 8，仍允许通过 `REVIEWCREW_MAX_CONCURRENCY` 覆盖，最大值 32。
- 所有解释性代码注释、Python docstring、TSDoc、日志、错误提示和页面文案使用中文。
- 不公开隐藏思维链、原始 Prompt、模型原始响应、密钥或未经脱敏的外部异常。
- 工具事件只能描述真实发生的动作；Mailbox 协作动作单独计数，不冒充工具。
- Fake Benchmark 必须醒目标注为离线链路验证，不计入真实命中率。
- 所有 Git 提交使用中文信息；只本地提交，不推送。
- 保留用户现有的 `design-doc.md` 删除、`doc/` 和审查报告文件，不纳入任何提交。

## File Structure

- `reviewcrew/budget.py`：新增按 Diff 规模计算软预算和共享 600 秒截止时间的纯函数。
- `reviewcrew/events.py`：扩展公开事件类型及脱敏字段白名单。
- `reviewcrew/tool_activity.py`：统一发布系统工具和 Agent 工具活动。
- `reviewcrew/pipeline/orchestrator.py`：接入共享截止时间、并发 8、Verifier 生命周期和工具/计划事件。
- `reviewcrew/context/builder.py`：通过工具活动发布器包装真实读取、检索和 Semgrep 动作。
- `reviewcrew/github/pr_loader.py`：发布 PR 拉取活动，并把空 GitHub Token 当作未配置。
- `benchmark/models.py`、`benchmark/report.py`：增加逐仓、逐案例汇总模型和持久化结果。
- `reviewcrew/server/app.py`：返回逐仓 Benchmark 契约。
- `frontend/src/stores/runs.ts`：应用级活动运行、事件订阅和多页面共享状态。
- `frontend/src/components/ActiveRunBar.vue`：全局迷你任务条。
- `frontend/src/components/AgentOperationsGraph.vue`：真实 Agent 实例拓扑。
- `frontend/src/components/OperationFeed.vue`：工具与协作操作流水线。
- `frontend/src/components/ReplayControls.vue`：倍速、暂停、继续和跳过空闲时间。
- `frontend/src/components/RepositoryBenchmarkMatrix.vue`：五仓真实状态矩阵。
- `frontend/src/pages/ReviewPage.vue`、`ResultPage.vue`、`HistoryPage.vue`：组合新组件，不再自行管理 SSE 生命周期。

---

### Task 1: 修复空 GitHub Token 与 600 秒自适应预算

**Files:**
- Create: `reviewcrew/budget.py`
- Modify: `reviewcrew/config.py`
- Modify: `reviewcrew/github/pr_loader.py`
- Modify: `reviewcrew/pipeline/orchestrator.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`
- Test: `tests/test_pr_loader.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Produces: `ReviewBudget.from_pr(pr: PRData, config: Config) -> ReviewBudget`
- Produces: `ReviewBudget.team_soft_seconds: int`、`ReviewBudget.deadline_monotonic: float`
- Produces: `Config.github_token_value() -> str | None`

- [ ] **Step 1: 写空 GitHub Token 的失败测试**

```python
def test_empty_github_token_is_treated_as_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEWCREW_GITHUB_TOKEN", "")
    assert Config.from_env().github_token_value() is None
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/test_config.py::test_empty_github_token_is_treated_as_unconfigured -q`

- [ ] **Step 3: 实现空值归一化并让 PR Loader 使用该接口**

```python
def github_token_value(self) -> str | None:
    """返回去除首尾空白后的 GitHub Token；空值按未配置处理。"""
    if self.github_token is None:
        return None
    value = self.github_token.get_secret_value().strip()
    return value or None
```

- [ ] **Step 4: 写预算分级与 600 秒绝对上限测试**

```python
@pytest.mark.parametrize(
    ("files", "changed_lines", "expected"),
    [(2, 80, 240), (6, 600, 420), (14, 2400, 600)],
)
def test_review_budget_scales_with_diff_but_never_exceeds_global_limit(
    files: int, changed_lines: int, expected: int
) -> None:
    pr = make_pr(file_count=files, changed_lines=changed_lines)
    budget = ReviewBudget.from_pr(pr, Config(global_timeout_seconds=600))
    assert budget.team_soft_seconds == expected
    assert budget.hard_seconds == 600
```

- [ ] **Step 5: 实现 `ReviewBudget` 并接入 Orchestrator**

实现规则：1–3 文件且变更不超过 300 行为 240 秒；4–10 文件或不超过 1500 行为 420 秒；其余为 600 秒。所有阶段从同一 `deadline_monotonic` 计算剩余时间，报告阶段至少预留 20 秒。

- [ ] **Step 6: 移植 1.1.7 已验证的并发和 Verifier 生命周期修复**

要求：默认 `max_concurrency=8`；Verifier watcher 使用团队生命周期预算，单次模型调用仍使用 `llm_timeout_seconds`。

- [ ] **Step 7: 运行定向测试**

Run: `python -m pytest tests/test_config.py tests/test_pr_loader.py tests/test_orchestrator.py -q`
Expected: 全部通过。

- [ ] **Step 8: 中文提交**

```powershell
git add .env.example reviewcrew/budget.py reviewcrew/config.py reviewcrew/github/pr_loader.py reviewcrew/pipeline/orchestrator.py tests/test_config.py tests/test_pr_loader.py tests/test_orchestrator.py
git commit -m "修复：统一十分钟预算并处理空令牌"
```

### Task 2: 建立真实工具活动与协作事件契约

**Files:**
- Create: `reviewcrew/tool_activity.py`
- Modify: `reviewcrew/events.py`
- Modify: `reviewcrew/schemas.py`
- Modify: `reviewcrew/pipeline/orchestrator.py`
- Modify: `reviewcrew/context/builder.py`
- Modify: `reviewcrew/github/pr_loader.py`
- Test: `tests/test_events.py`
- Test: `tests/test_context_builder.py`
- Test: `tests/test_orchestrator.py`
- Test: `tests/test_full_stack.py`

**Interfaces:**
- Produces: `ToolActivityPublisher.started(...) -> ToolActivityHandle`
- Produces: `ToolActivityHandle.complete(summary: str, result_count: int | None = None) -> None`
- Produces event types: `plan.published`、`tool.started`、`tool.completed`、`tool.failed`、`mailbox.message`

- [ ] **Step 1: 写公开事件白名单失败测试**

```python
def test_tool_event_exposes_summary_but_removes_sensitive_fields(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    event = store.emit("run-1", "tool.completed", {
        "actor": "context_builder",
        "actor_type": "system",
        "tool_name": "context.search_symbol",
        "target": "OptimizedCursorPaginator",
        "summary": "检查 3 个文件，发现 2 处引用",
        "duration_ms": 184,
        "prompt": "不得公开",
    })
    assert "prompt" not in event.data
    assert event.data["duration_ms"] == 184
```

- [ ] **Step 2: 运行并确认事件类型或白名单测试失败**

Run: `python -m pytest tests/test_events.py::test_tool_event_exposes_summary_but_removes_sensitive_fields -q`

- [ ] **Step 3: 实现工具活动发布器**

工具活动字段固定为 `actor`、`actor_type`、`tool_name`、`status`、`target`、`summary`、`duration_ms`、`result_count`、`context_id`、`agent_id`。字符串按公开事件上限裁剪。

- [ ] **Step 4: 为真实系统动作接入事件**

必须覆盖：GitHub PR 拉取、Diff 解析、项目文档读取、文件范围读取、相关测试检索、符号引用检索、Semgrep、报告持久化。没有执行的动作只发布明确的降级事件，不发布成功事件。

- [ ] **Step 5: 发布 TeamLead 计划摘要**

`plan.published` 只包含 `risk_tags`、`context_ids`、`shards`、`budget_seconds` 和中文摘要，不包含 Prompt 或模型原文。

- [ ] **Step 6: 发布安全的 Mailbox 协作摘要**

仅覆盖 `candidate_finding`、`evidence_request`、`evidence_response`、`verifier_final`、`agent_review_completed`，字段为发送者、接收者、kind、correlation_id 和短摘要。

- [ ] **Step 7: 更新全栈公开事件契约测试**

断言 SSE、持久化 JSONL 和 Replay 包含相同的新事件，且所有事件不包含 `prompt`、`reasoning`、`api_key`、`raw_response`。

- [ ] **Step 8: 运行后端事件相关回归**

Run: `python -m pytest tests/test_events.py tests/test_context_builder.py tests/test_orchestrator.py tests/test_full_stack.py -q`

- [ ] **Step 9: 中文提交**

```powershell
git add reviewcrew/tool_activity.py reviewcrew/events.py reviewcrew/schemas.py reviewcrew/pipeline/orchestrator.py reviewcrew/context/builder.py reviewcrew/github/pr_loader.py tests/test_events.py tests/test_context_builder.py tests/test_orchestrator.py tests/test_full_stack.py
git commit -m "功能：公开真实工具活动与协作事件"
```

### Task 3: 将 SSE 生命周期提升为应用级 Run Controller

**Files:**
- Create: `frontend/src/stores/runs.ts`
- Create: `frontend/src/stores/runs.spec.ts`
- Create: `frontend/src/components/ActiveRunBar.vue`
- Create: `frontend/src/components/ActiveRunBar.spec.ts`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/pages/StartPage.vue`
- Modify: `frontend/src/pages/ReviewPage.vue`
- Modify: `frontend/src/stores/review.ts`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Produces: `useRunsStore().startSubscription(runId: string): void`
- Produces: `useRunsStore().stopSubscription(runId: string): void`
- Produces: `useRunsStore().activeRunId: string | null`
- Consumes: `createEventSubscription(runId, handlers)`

- [ ] **Step 1: 写路由切换不关闭订阅的失败测试**

```ts
it('页面卸载后全局运行订阅仍保持连接', () => {
  const source = fakeEventSource()
  const store = useRunsStore()
  store.startSubscription('run-1', () => source)
  store.leaveReviewPage('run-1')
  expect(source.close).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: 运行并确认失败**

Run: `pnpm test -- --run src/stores/runs.spec.ts`

- [ ] **Step 3: 实现按 `run_id` 管理的单例订阅**

同一运行重复调用 `startSubscription` 不创建第二个 EventSource；收到终态后关闭订阅；浏览器刷新后根据 `sessionStorage.activeRunId` 恢复连接。

- [ ] **Step 4: 实现 `ActiveRunBar`**

显示仓库、当前阶段、耗时、候选数、连接状态；运行中点击进入 `/review/{runId}`，终态提供“查看过程”和“查看报告”。文案明确“切换页面不会停止服务端审查”。

- [ ] **Step 5: 移除 ReviewPage 的订阅所有权**

ReviewPage 不再在 `onBeforeUnmount` 中关闭实时 SSE，只读取全局 Store；离线 Demo 的本地播放控制器仍由页面持有。

- [ ] **Step 6: 运行前端定向测试**

Run: `pnpm test -- --run src/stores/runs.spec.ts src/components/ActiveRunBar.spec.ts src/api/client.spec.ts`

- [ ] **Step 7: 中文提交**

```powershell
git add frontend/src/stores/runs.ts frontend/src/stores/runs.spec.ts frontend/src/components/ActiveRunBar.vue frontend/src/components/ActiveRunBar.spec.ts frontend/src/App.vue frontend/src/pages/StartPage.vue frontend/src/pages/ReviewPage.vue frontend/src/stores/review.ts frontend/src/api/client.ts
git commit -m "功能：保持全局审查任务与实时连接"
```

### Task 4: 展示真实 Agent 实例、计划、工具和协作流水线

**Files:**
- Create: `frontend/src/components/AgentOperationsGraph.vue`
- Create: `frontend/src/components/AgentOperationsGraph.spec.ts`
- Create: `frontend/src/components/OperationFeed.vue`
- Create: `frontend/src/components/OperationFeed.spec.ts`
- Modify: `frontend/src/contracts.ts`
- Modify: `frontend/src/stores/review.ts`
- Modify: `frontend/src/stores/review.spec.ts`
- Modify: `frontend/src/pages/ReviewPage.vue`
- Modify: `frontend/src/components/Timeline.vue`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces: `AgentInstanceState` keyed by full `agent_id`
- Produces: `OperationRecord` for `plan`、`tool`、`mailbox`、`candidate`、`verdict`
- Consumes new events from Task 2.

- [ ] **Step 1: 写六个 Agent 不被折叠的失败测试**

```ts
it('按完整 agent id 保存六个并行专家实例', () => {
  for (const id of ['defect:ctx-1', 'defect:ctx-2', 'defect:ctx-3', 'intent:ctx-1', 'intent:ctx-2', 'intent:ctx-3']) {
    store.applyEvent(event('agent.started', { agent: id, role: id.split(':')[0], context_id: id.split(':')[1] }))
  }
  expect(Object.keys(store.agentInstances)).toHaveLength(6)
})
```

- [ ] **Step 2: 扩展前端类型和归约器**

保存完整 Agent ID、context_id、负责文件、开始/结束时间、工具数、协作消息数、候选数和 warning。旧事件缺少新字段时仍能降级展示。

- [ ] **Step 3: 实现真实并行拓扑**

TeamLead 计划位于顶部；中间按 context 分组展示 Defect/Intent 实例；Evidence Blackboard 显示候选与补证数；Verifier 位于收敛端。禁止用动画伪造未发生的消息。

- [ ] **Step 4: 实现操作流水线**

自然语言显示“拉取 PR”“读取文件”“搜索符号”“请求补证”等动作，包含目标、耗时、状态和结果摘要。系统工具、Agent 工具、协作消息使用不同标签。

- [ ] **Step 5: 改造完整时间线**

默认保留全部事件；支持阶段、Agent 和类型筛选；支持自动跟随开关；不再硬编码 `slice(-10)`。

- [ ] **Step 6: 运行组件和 Store 测试**

Run: `pnpm test -- --run src/stores/review.spec.ts src/components/AgentOperationsGraph.spec.ts src/components/OperationFeed.spec.ts`

- [ ] **Step 7: 中文提交**

```powershell
git add frontend/src/contracts.ts frontend/src/stores/review.ts frontend/src/stores/review.spec.ts frontend/src/components/AgentOperationsGraph.vue frontend/src/components/AgentOperationsGraph.spec.ts frontend/src/components/OperationFeed.vue frontend/src/components/OperationFeed.spec.ts frontend/src/components/Timeline.vue frontend/src/pages/ReviewPage.vue frontend/src/styles.css
git commit -m "功能：展示并行代理与证据裁决过程"
```

### Task 5: 报告返回路径与可调倍速 Replay

**Files:**
- Create: `frontend/src/components/ReplayControls.vue`
- Create: `frontend/src/components/ReplayControls.spec.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.spec.ts`
- Modify: `frontend/src/pages/ReviewPage.vue`
- Modify: `frontend/src/pages/ResultPage.vue`
- Modify: `frontend/src/pages/HistoryPage.vue`
- Modify: `reviewcrew/server/replay.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `ReplayController` with `play()`、`pause()`、`restart()`、`setSpeed(speed)`、`skipIdle`
- Supported speeds: `0.5 | 1 | 2 | 4 | 8`

- [ ] **Step 1: 写运行中报告页可返回过程的失败测试**

断言 ResultPage 在 pending、partial、failed 和 completed 状态都存在 `/review/{runId}` 链接。

- [ ] **Step 2: 写播放中切换倍速不重复事件的失败测试**

```ts
it('播放中从 1 倍切到 8 倍仍只应用每个序号一次', async () => {
  const applied: number[] = []
  const controller = createReplayController(events, (event) => applied.push(event.sequence))
  controller.play()
  controller.setSpeed(8)
  await controller.finished
  expect(applied).toEqual([1, 2, 3, 4])
})
```

- [ ] **Step 3: 实现 Replay 控制器和组件**

支持 0.5×、1×、2×、4×、8×、暂停、继续、重新开始和跳到下一关键事件；`skipIdle` 把超过 1 秒的无事件间隔压缩到 1 秒。

- [ ] **Step 4: 统一服务端和本地 Replay 倍速校验**

服务端只接受有限、正数倍速；前端本地 Demo 使用相同倍速集合。显示原始运行耗时和当前回放耗时。

- [ ] **Step 5: 运行 Replay 回归**

Run: `python -m pytest tests/test_server.py -q`
Run: `pnpm test -- --run src/api/client.spec.ts src/components/ReplayControls.spec.ts`

- [ ] **Step 6: 中文提交**

```powershell
git add reviewcrew/server/replay.py tests/test_server.py frontend/src/api/client.ts frontend/src/api/client.spec.ts frontend/src/components/ReplayControls.vue frontend/src/components/ReplayControls.spec.ts frontend/src/pages/ReviewPage.vue frontend/src/pages/ResultPage.vue frontend/src/pages/HistoryPage.vue
git commit -m "功能：支持返回审查过程与倍速回放"
```

### Task 6: 提供逐仓 Benchmark API 与真实五仓矩阵

**Files:**
- Modify: `benchmark/models.py`
- Modify: `benchmark/report.py`
- Modify: `benchmark/runner.py`
- Modify: `reviewcrew/server/app.py`
- Test: `tests/test_benchmark_runner.py`
- Test: `tests/test_server.py`
- Modify: `frontend/src/contracts.ts`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/components/RepositoryBenchmarkMatrix.vue`
- Create: `frontend/src/components/RepositoryBenchmarkMatrix.spec.ts`
- Modify: `frontend/src/pages/HistoryPage.vue`

**Interfaces:**
- Produces: `RepositoryBenchmarkSummary`
- Extends `BenchmarkSummary.repositories: RepositoryBenchmarkSummary[]`
- Repository states: `needs_data | pending | running | completed | partial | failed`

- [ ] **Step 1: 写逐仓聚合失败测试**

```python
def test_summary_groups_cases_by_repository_without_inventing_zero_rates() -> None:
    summary = summarize_reports([sentry_partial_report()], all_repositories=FIVE_REPOSITORIES)
    sentry = next(item for item in summary.repositories if item.repository == "sentry")
    calcom = next(item for item in summary.repositories if item.repository == "calcom")
    assert sentry.target_caught == 0
    assert sentry.other_findings == 4
    assert calcom.status == "pending"
    assert calcom.catch_rate is None
```

- [ ] **Step 2: 扩展后端模型和报告持久化**

逐仓字段包含仓库、语言、案例总数、已核验数、已运行数、目标命中、其他 Finding、拒绝数、耗时、状态、最近 run_id 和 cases。

- [ ] **Step 3: 扩展 `/api/benchmarks/latest`**

API 返回后端持久化的逐仓数据；旧 summary 缺少字段时补为空数组，不扫描任意路径。

- [ ] **Step 4: 写五仓矩阵空态失败测试**

未运行仓库必须显示“待评测”，`catch_rate=null` 时不得显示 `0%`；Fake 数据显示“离线链路验证”。

- [ ] **Step 5: 实现可点击五仓矩阵**

每行提供“查看案例”“查看运行”“回放过程”；Sentry 关联 `run-20260730-012450-d90a1b5b` 时显示部分完成、目标未命中、其他 Finding 4、拒绝 2、约 319.87 秒。

- [ ] **Step 6: 运行后端和前端定向测试**

Run: `python -m pytest tests/test_benchmark_runner.py tests/test_server.py -q`
Run: `pnpm test -- --run src/components/RepositoryBenchmarkMatrix.spec.ts src/api/client.spec.ts`

- [ ] **Step 7: 中文提交**

```powershell
git add benchmark/models.py benchmark/report.py benchmark/runner.py reviewcrew/server/app.py tests/test_benchmark_runner.py tests/test_server.py frontend/src/contracts.ts frontend/src/api/client.ts frontend/src/components/RepositoryBenchmarkMatrix.vue frontend/src/components/RepositoryBenchmarkMatrix.spec.ts frontend/src/pages/HistoryPage.vue
git commit -m "功能：提供真实逐仓评测矩阵"
```

### Task 7: 全链路集成、中文文案和演示回放

**Files:**
- Modify: `frontend/src/fixtures/demo-events.jsonl`
- Modify: `frontend/src/fixtures/demo-replay.spec.ts`
- Modify: `frontend/src/full-stack-contract.spec.ts`
- Modify: `tests/test_full_stack.py`
- Modify: `README.md`
- Modify: `docs/早间交接.md`
- Modify: `benchmark/results/VERSION_REGISTRY.md`
- Modify: `benchmark/results/ITERATION_LOG.md`

**Interfaces:**
- Consumes all tasks above.
- Produces a reproducible live and replay demonstration contract.

- [ ] **Step 1: 扩展离线演示事件**

fixture 必须包含 PR 拉取、Diff 解析、TeamLead 分片、六个专家实例、系统工具、Agent 工具、候选、补证、接受、拒绝、报告生成和终态。

- [ ] **Step 2: 更新前后端全栈契约测试**

断言 live SSE、持久化事件和 Replay 归约为相同 UI 状态；路由切换后序号连续；工具和协作动作不混算。

- [ ] **Step 3: 运行全量后端验证**

Run: `python -m pytest -q`
Run: `python -m compileall -q reviewcrew benchmark`

- [ ] **Step 4: 运行全量前端验证和构建**

Run: `pnpm test -- --run`
Run: `pnpm build`

- [ ] **Step 5: 运行 Fake Benchmark quick**

Run: `python -m benchmark.runner --mode quick --runner fake`
Expected: 五仓链路完成，报告明确标注 offline，不进入真实命中率。

- [ ] **Step 6: 运行真实 smoke 和一个真实 PR**

使用运行时密钥，不输出或提交；确认总耗时不超过 600 秒，页面可切换、返回、倍速回放并展示真实工具活动。若未命中目标漏洞，按事实记录。

- [ ] **Step 7: 更新版本登记和交接文档**

只有后端、前端、构建、Fake、真实模型和真实 PR 全部通过才登记 `stable`；否则登记 `candidate` 并写明缺口。

- [ ] **Step 8: 中文提交**

```powershell
git add frontend/src/fixtures/demo-events.jsonl frontend/src/fixtures/demo-replay.spec.ts frontend/src/full-stack-contract.spec.ts tests/test_full_stack.py README.md docs/早间交接.md benchmark/results/VERSION_REGISTRY.md benchmark/results/ITERATION_LOG.md
git commit -m "验证：完成前端作战室全链路验收"
```

## Parallel Execution Waves

### Wave 1

- Task 1：运行时预算与空 Token。
- Task 3：应用级 SSE 与全局任务条。
- Task 6 后端部分：逐仓 Benchmark 模型和 API。

三项修改文件基本独立，可并行；Task 6 前端部分等待 API 契约确定。

### Wave 2

- Task 2：工具、计划和协作事件。
- Task 5：报告返回与 Replay 控制。
- Task 6 前端部分：五仓矩阵。

Task 2 在 Task 1 的 Orchestrator 修改完成后开始，避免冲突。

### Wave 3

- Task 4：作战室消费稳定的新事件契约。
- Task 7：全链路集成与验收。

