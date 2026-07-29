# Dynamic Multi-Agent Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed five-stage review pipeline with a Coordinator-planned, event-driven Multi-Agent task graph whose real scheduling activity is visible in a Chinese animated dashboard.

**Architecture:** A CoordinatorAgent produces typed review missions from ContextPacks. A pure-async scheduler executes ready missions under dependency, concurrency, task-count, and time budgets, emits workflow node/edge events, dynamically creates verifier tasks, and hands the verified result to the existing deterministic report layer. Vue derives its graph and dispatch board entirely from those events.

**Tech Stack:** Python 3.12, asyncio, Pydantic 2, Pydantic AI, FastAPI/SSE, Vue 3, TypeScript strict, Pinia, Vue Flow, Naive UI, Tailwind CSS, Vitest, pytest.

## Global Constraints

- User-facing task goals, reasoning, findings, verdicts, status labels, and reports use Simplified Chinese.
- The backend does not use LangGraph, CrewAI, or another graph orchestration framework.
- Only Agent work consumes LLM calls; scheduling state, budgets, filtering, reporting, and event persistence stay deterministic.
- `REVIEWCREW_MAX_AGENTS` defaults to 4, hard timeout defaults to 600 seconds, task count is bounded, and handoff depth is at most one.
- Findings with adjusted confidence below 0.6 are dropped and at most 8 findings are retained.
- The graph starts empty and grows only in response to real workflow events.
- TypeScript remains strict with no `any`; Python remains fully typed and passes Mypy strict.

---

### Task 1: Workflow Event Contract and Chinese Output

**Files:**
- Modify: `reviewcrew/models.py`
- Modify: `reviewcrew/agents/base.py`
- Modify: `reviewcrew/agents/prompts/defect.md`
- Modify: `reviewcrew/agents/prompts/intent.md`
- Modify: `reviewcrew/agents/prompts/verifier.md`
- Modify: `reviewcrew/agents/verifier.py`
- Modify: `reviewcrew/pipeline/report.py`
- Modify: `tests/test_events.py`
- Modify: `tests/test_report.py`
- Modify: `tests/test_verifier.py`

**Interfaces:**
- Produces: `WorkflowNode`, `WorkflowEdge`, `WorkflowNodeStatus`, `WorkflowRelation`.
- Extends: `PipelineEvent.type` with `run`, `workflow_node`, and `workflow_edge` while retaining `stage` for old replay compatibility.
- Produces: `PipelineEvent.workflow_node` and `PipelineEvent.workflow_edge` optional payloads.

- [ ] **Step 1: Add failing workflow event round-trip and Chinese report assertions**

```python
node = WorkflowNode(id="task-1", kind="agent_task", label="检查认证边界", agent="defect", status="queued")
event = PipelineEvent(timestamp=1, type="workflow_node", workflow_node=node)
assert PipelineEvent.model_validate_json(event.model_dump_json()) == event
assert "审查摘要" in generate_report([])[0]
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_events.py tests/test_report.py tests/test_verifier.py -q`

- [ ] **Step 3: Implement workflow models and Chinese prompts/report strings**

```python
class WorkflowNode(BaseModel):
    id: str
    kind: Literal["input", "coordinator", "agent_task", "tool", "finding", "verifier", "report"]
    label: str
    agent: Literal["coordinator", "defect", "intent", "verifier"] | None = None
    status: Literal["queued", "running", "waiting", "completed", "failed", "cancelled"]
    detail: str | None = None
    task_id: str | None = None
```

Prompts must state that all natural-language output fields are Simplified Chinese while code symbols and paths remain unchanged. Deterministic verifier fallback and Markdown headings become Chinese.

- [ ] **Step 4: Run focused tests, Ruff, and Mypy**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_events.py tests/test_report.py tests/test_verifier.py -q`

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m ruff check reviewcrew/models.py reviewcrew/agents reviewcrew/pipeline/report.py tests/test_events.py tests/test_report.py tests/test_verifier.py`

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m mypy reviewcrew tests/test_events.py tests/test_report.py tests/test_verifier.py`

- [ ] **Step 5: Commit**

```bash
git add reviewcrew/models.py reviewcrew/agents reviewcrew/pipeline/report.py tests/test_events.py tests/test_report.py tests/test_verifier.py
git commit -m "feat: add workflow events and Chinese review output"
```

### Task 2: CoordinatorAgent and Typed Review Plan

**Files:**
- Create: `reviewcrew/agents/coordinator.py`
- Create: `reviewcrew/agents/prompts/coordinator.md`
- Modify: `reviewcrew/agents/__init__.py`
- Create: `tests/test_coordinator.py`

**Interfaces:**
- Produces: `ReviewMission(id, agent, objective, rationale, context_pack_ids, focus_files, priority, depends_on)`.
- Produces: `ReviewPlan(summary, missions)`.
- Produces: `CoordinatorAgent.run(packs, timeout_seconds=45) -> ReviewPlan`.
- Produces: `fallback_plan(packs) -> ReviewPlan`.

- [ ] **Step 1: Write tests for typed plan validation and deterministic fallback**

```python
plan = fallback_plan([ContextPack(pack_id="auth", diff_hunks=[])])
assert {mission.agent for mission in plan.missions} == {"defect", "intent"}
assert all(mission.objective for mission in plan.missions)
```

- [ ] **Step 2: Run the coordinator test and confirm failure**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_coordinator.py -q`

- [ ] **Step 3: Implement CoordinatorAgent with structured Pydantic AI output**

The model receives compact pack metadata, static signals, intent, and file lists rather than duplicate full source. Invalid, empty, timed-out, or unavailable model output returns `fallback_plan` and exposes the fallback reason in `ReviewPlan.summary`.

- [ ] **Step 4: Run coordinator tests and static checks**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_coordinator.py -q`

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m ruff check reviewcrew/agents/coordinator.py tests/test_coordinator.py`

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m mypy reviewcrew/agents/coordinator.py tests/test_coordinator.py`

- [ ] **Step 5: Commit**

```bash
git add reviewcrew/agents/coordinator.py reviewcrew/agents/prompts/coordinator.md reviewcrew/agents/__init__.py tests/test_coordinator.py
git commit -m "feat: add coordinator review planning"
```

### Task 3: Async Mission Scheduler and Orchestrator Integration

**Files:**
- Create: `reviewcrew/pipeline/scheduler.py`
- Modify: `reviewcrew/pipeline/orchestrator.py`
- Modify: `reviewcrew/agents/base.py`
- Modify: `reviewcrew/agents/verifier.py`
- Create: `tests/test_scheduler.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Produces: `MissionTask`, `TaskResult`, `SchedulerSummary`.
- Produces: `MissionScheduler.run(plan, packs, toolbox, experts, verifier) -> SchedulerSummary`.
- Consumes: Coordinator `ReviewPlan`, expert `ReviewAgent.run`, verifier `VerifierAgent.run`.
- Emits: input, coordinator, agent task, tool, finding, verifier, and report nodes plus dispatch, depends_on, tool_call, evidence, candidate, challenge, and result edges.

- [ ] **Step 1: Write scheduler tests for dependency order, concurrency, workflow events, and verifier fan-out**

```python
summary = await scheduler.run(plan, packs, toolbox, experts, verifier)
assert summary.max_concurrency == 2
assert any(event.type == "workflow_node" and event.workflow_node.kind == "verifier" for event in captured)
assert all(task.status in {"completed", "failed", "cancelled"} for task in summary.tasks)
```

- [ ] **Step 2: Run scheduler and orchestrator tests and confirm failure**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_scheduler.py tests/test_orchestrator.py -q`

- [ ] **Step 3: Implement the bounded ready-queue scheduler**

Use an `asyncio.Semaphore`, stable priority ordering, dependency checks, task signature de-duplication, one handoff depth, and cancellation on deadline. Each state transition updates the same workflow node id. Verifier work is one task per candidate Finding so the graph reflects actual fan-out.

- [ ] **Step 4: Replace fixed expert-review/verify stages in Orchestrator**

The Orchestrator may retain internal timing metrics but must no longer emit fixed stage events for new runs. It emits an input node, context detail, coordinator events, delegates mission execution to the scheduler, then emits a report node and result edges.

- [ ] **Step 5: Run backend tests and strict checks**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_scheduler.py tests/test_orchestrator.py -q`

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m ruff check reviewcrew/pipeline reviewcrew/agents tests/test_scheduler.py tests/test_orchestrator.py`

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m mypy reviewcrew tests/test_scheduler.py tests/test_orchestrator.py`

- [ ] **Step 6: Commit**

```bash
git add reviewcrew/pipeline/scheduler.py reviewcrew/pipeline/orchestrator.py reviewcrew/agents tests/test_scheduler.py tests/test_orchestrator.py
git commit -m "feat: schedule dynamic multi-agent missions"
```

### Task 4: Frontend Workflow Store and From-Zero Replay

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/stores/review.ts`
- Modify: `web/src/stores/review.test.ts`
- Replace: `web/src/demo.ts`

**Interfaces:**
- Produces: `WorkflowNode`, `WorkflowEdge`, `WorkflowStatus`, `WorkflowRelation` TypeScript types.
- Produces store state: `workflowNodes`, `workflowEdges`, `selectedNodeId`, `dispatchLog`.
- Produces getters: `taskCounts`, `activeAgentCount`, `selectedWorkflowNode`.

- [ ] **Step 1: Replace store tests with workflow reducer expectations**

```typescript
expect(store.workflowNodes).toHaveLength(1)
store.consume(taskNodeEvent)
expect(store.taskCounts.running).toBe(1)
store.consume(edgeEvent)
expect(store.workflowEdges[0]?.relation).toBe('dispatch')
```

- [ ] **Step 2: Run Vitest and confirm failure**

Run: `cd web && npm run test`

- [ ] **Step 3: Implement event reducer and Chinese 6-second demo timeline**

The demo starts with no preloaded nodes. It emits input, coordinator, three review missions, tool satellites, one cross-check edge, two Finding nodes, two verifier nodes, one rejection, one keep, and a report node. Finding text and verdict reasons are Chinese.

- [ ] **Step 4: Run typecheck and tests**

Run: `cd web && npm run typecheck && npm run test`

- [ ] **Step 5: Commit**

```bash
git add web/src/types.ts web/src/stores/review.ts web/src/stores/review.test.ts web/src/demo.ts
git commit -m "feat: reduce dynamic workflow events in web store"
```

### Task 5: Dynamic Workflow Graph, Dispatch Board, and Animation

**Files:**
- Replace: `web/src/components/AgentFlow.vue`
- Create: `web/src/components/DispatchBoard.vue`
- Modify: `web/src/components/ThoughtStream.vue`
- Modify: `web/src/components/FindingCard.vue`
- Modify: `web/src/views/ReviewView.vue`
- Modify: `web/src/styles.css`
- Delete: `web/src/components/StageRail.vue`

**Interfaces:**
- `AgentFlow` consumes workflow nodes, edges, and selected node id; emits `select`.
- `DispatchBoard` consumes workflow nodes, elapsed seconds, and dispatch log.
- `FindingCard` emits `select-workflow` with `finding-<id>`.

- [ ] **Step 1: Build dynamic Vue Flow nodes and edges from store state**

Use stable rank-based positions by node kind and parent task. Do not create any node absent from the event store. Labels show Chinese node type, task objective, status, tool/finding count, and elapsed detail.

- [ ] **Step 2: Replace Pipeline rail with dispatch board**

Show countdown, active/max concurrency, queued/running/completed/failed counters, recent scheduling reasons, and concrete mission objectives. Empty state explains that Coordinator has not dispatched work yet.

- [ ] **Step 3: Add event-driven animations and reduced-motion fallback**

Use Vue Motion for node/card entry and CSS `stroke-dashoffset`, transform, and opacity for active edges, tool expansion, keep, and reject transitions. Keep fixed graph dimensions so event updates do not resize the layout.

- [ ] **Step 4: Translate remaining user-visible review strings**

Change `Findings`, retained/rejected counts, event stream labels, severity/category display, and report/Diff copy to Chinese while preserving code and paths.

- [ ] **Step 5: Run frontend gates**

Run: `cd web && npm run typecheck && npm run lint && npm run test && npm run build`

- [ ] **Step 6: Commit**

```bash
git add web/src/components web/src/views/ReviewView.vue web/src/styles.css
git commit -m "feat: visualize live multi-agent dispatch"
```

### Task 6: Public Greptile Single-Case Benchmark

**Files:**
- Modify: `benchmark/collect.py`
- Create: `benchmark/samples/metaflow-pr-3069.yaml`
- Modify: `benchmark/run_eval.py`
- Modify: `docs/评测报告.md`

**Interfaces:**
- `benchmark.collect --source https://www.greptile.com/benchmarks --limit 1 --output <path>` normalizes a selected public case.
- `benchmark.run_eval --dataset benchmark/samples/metaflow-pr-3069.yaml --full --runner real` evaluates only that case.

- [ ] **Step 1: Fetch and verify public PR metadata through the configured proxy**

Use GitHub API and PR diff to record exact base/head SHA, file, line 70/84, security description, and public discussion URL. Do not invent a fork URL; use the public repository URL only when clone access is verified.

- [ ] **Step 2: Add the single-case YAML and collection normalization**

Validate it with `load_dataset` and `git ls-remote`. Clone only the required repository using a shallow/filter strategy where compatible with the PR refs.

- [ ] **Step 3: Run the single case**

Run with proxy variables and `LLM_API_KEY` from the process environment. If the key is absent, run all non-LLM preparation and report the exact blocked command without persisting a secret.

- [ ] **Step 4: Record evidence without claiming a 50-PR score**

Add the case result directory, elapsed time, findings, hit reason, and any blocker to `docs/评测报告.md`.

- [ ] **Step 5: Commit**

```bash
git add benchmark/collect.py benchmark/samples/metaflow-pr-3069.yaml benchmark/run_eval.py docs/评测报告.md
git commit -m "eval: add public Greptile single-case sample"
```

### Task 7: Full Verification and Browser Acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/演示脚本.md`
- Modify: `benchmark/results/ITERATION_LOG.md`

**Interfaces:**
- Documents dynamic scheduling, Chinese output, from-zero Replay, and one-case benchmark command.

- [ ] **Step 1: Run all backend gates**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest -q`

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m ruff check .`

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m mypy reviewcrew benchmark tests`

- [ ] **Step 2: Run all frontend gates**

Run: `cd web && npm run typecheck && npm run lint && npm run test && npm run build`

- [ ] **Step 3: Browser-test desktop and mobile Replay**

Verify node counts grow from 0, Coordinator visibly dispatches three missions, at least two tasks run concurrently, tool nodes appear, a cross-check edge appears, two Verifier nodes fan out, one Finding is rejected, one is retained, and no console error or horizontal overflow exists at desktop and 390x844.

- [ ] **Step 4: Browser-test Diff and Benchmark routes**

Verify Chinese copy, line markers, demo-data disclosure, responsive layout, and no toolbar overlap.

- [ ] **Step 5: Update documentation and commit**

```bash
git add README.md docs/演示脚本.md benchmark/results/ITERATION_LOG.md
git commit -m "docs: document dynamic multi-agent workflow"
```
