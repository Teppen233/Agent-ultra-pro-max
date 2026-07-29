# ReviewCrew Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 2026-07-30 12:00 前实现可运行、可测试、可演示的 ReviewCrew，以 GLM 5.2 和三个 Subagent 审查 Git PR diff，并完成 Greptile Benchmark 快速评测、Vue 3 前端和中文交付文档。

**Architecture:** 系统使用 FastAPI 和纯 `asyncio` Orchestrator 串联 PR 加载、Diff 解析、上下文构建、两个并行专家 Agent、确定性去重、独立 Verifier 和报告生成。前端只消费冻结的 REST/SSE `PipelineEvent`，并支持从同一事件格式回放历史运行。

**Tech Stack:** Python 3.12、Pydantic 2、Pydantic AI、httpx、FastAPI、Uvicorn、PyYAML、pytest、pytest-asyncio、Vue 3、TypeScript、Vite、Pinia、Vitest。

## Global Constraints

- 设计规范：`docs/superpowers/specs/2026-07-29-reviewcrew-competition-design.md`，实现前必须完整阅读。
- 最终只有 `DefectAgent`、`IntentAgent`、`VerifierAgent` 三个 Subagent。
- 模型能力对齐 GLM 5.2，通过 OpenAI 兼容端点接入。
- 单 PR 全局 watchdog 固定为 600 秒。
- 分阶段上限：PR/Diff 30 秒、Context 90 秒、专家审查 300 秒、Verifier 120 秒、报告 30 秒。
- 只围绕 PR diff 和直接相关上下文审查，不进行无目标的全仓 LLM 扫描。
- Finding 必须定位修改行、包含触发条件、实际影响和代码证据。
- 不保存或展示模型隐藏思维链，只保存公开推理摘要和工具调用摘要。
- Python/TypeScript/Vue 的解释性注释、docstring、TSDoc、运行日志、错误提示和报告正文使用中文。
- 标识符、类名、字段名、协议枚举和 HTTP 路径使用英文。
- 日志不得包含 API Key、Authorization Header、完整 Prompt 或敏感仓库全文。
- 所有外部能力均可降级；单个 Agent、Semgrep、Git 历史或前端断连不得无故摧毁整个运行。
- 所有测试默认不依赖网络和真实 API Key；真实调用只存在于显式 smoke 命令。
- 每完成一个可独立验收的任务立即提交，不把多个大能力堆进一个提交。
- 不提交 `.env`、API Key、`runs/`、Benchmark 仓库副本、构建产物、IDE 文件或模型缓存。
- 2026-07-30 12:00 停止新增功能；12:00 至 14:00 只允许修复阻断交付的问题。

---

## Goal 运行契约

本节用于长时间 Goal 自动续跑。每次续跑都必须遵循，不得依赖此前对话记忆。

### 启动时必须执行

1. 读取本计划和设计规范。
2. 运行 `git status --short`，保留不属于本任务的现有改动。
3. 运行 `git log -5 --oneline`，确认最近完成的任务。
4. 搜索本计划中第一个未勾选步骤，从该处继续。
5. 检查是否存在失败的测试、未提交的本任务改动或半完成模块；优先收敛它们。
6. 不重复已经通过测试并提交的任务。

### 每轮工作规则

- 一次只推进一个 Task 的一个红—绿—重构循环。
- 修改代码前先写或确认失败测试。
- 每 30 至 60 分钟至少形成一个可恢复检查点；如果能力已独立可验收，立即提交。
- 每次提交后更新本计划对应 checkbox。
- 运行超过 60 秒的命令时，定期读取输出，不进行长时间无反馈等待。
- 外部网络、GLM 或 GitHub 不稳定时，继续完成 Fake、fixture、Replay 和离线测试，不得原地停滞。
- 若实现路线失败，先保留测试和接口，回退到更小的可工作实现，并用中文日志声明降级。
- 不以“代码已写完”作为完成依据，只以验证命令成功作为完成依据。

### 允许标记 Goal 完成的条件

只有全部满足以下条件，才能调用 Goal 完成操作：

1. `pytest -q` 通过。
2. `npm test -- --run` 通过。
3. `npm run build` 通过。
4. CLI 能在 Fake 模式完成端到端审查。
5. FastAPI 的启动、状态、SSE 和 Replay 测试通过。
6. 至少一次 GLM 5.2 smoke 成功，或明确记录因缺少 API Key 无法执行；缺少 Key 时不得声称真实调用成功。
7. 至少一个真实 PR 或本地 base/head 审查完成。
8. Benchmark 快速模式能够运行并生成报告；实际运行案例和未准备案例区分清楚。
9. README 包含安装、配置、CLI、服务端、前端、评测和故障排查方法。
10. Git 工作区只剩用户原有改动或明确记录的交付产物。

### 阻塞与时间裁切

- API Key 缺失不阻塞离线实现；完成全部 Fake 和 Replay 能力后记录真实 smoke 待执行。
- GitHub 限流时支持公开 PR 的无 Token 请求，并提供本地 base/head 模式。
- Semgrep 未安装时自动跳过，不允许让审查失败。
- 若距离 12:00 少于 90 分钟，停止新增 Provider、动画和非必要抽象，优先完成测试、README、Benchmark 报告和稳定 Replay。
- 若距离 12:00 少于 30 分钟，只处理阻断启动、构建、审查或报告生成的问题。
- 只有同一阻塞条件连续出现至少三轮且无法通过离线替代继续时，才允许将 Goal 标为 blocked。

---

## 文件结构与职责

```text
pyproject.toml                         Python 依赖、工具和测试配置
.env.example                           GLM、GitHub 和运行参数示例
.gitignore                             排除密钥、运行记录、仓库缓存和构建产物
README.md                              中文安装、使用、评测和演示说明
reviewcrew/config.py                   环境配置和时间预算
reviewcrew/schemas.py                  全局唯一领域模型
reviewcrew/events.py                   事件写入、订阅和回放
reviewcrew/cli.py                      CLI 入口
reviewcrew/llm/glm.py                  GLM 5.2 模型构建和 smoke
reviewcrew/github/pr_loader.py          GitHub PR 与本地 Git 加载
reviewcrew/diff/parser.py              Unified Diff 解析
reviewcrew/context/builder.py          Diff 中心上下文组装与裁剪
reviewcrew/tools/files.py              安全文件读取
reviewcrew/tools/search.py             代码、测试和文档搜索
reviewcrew/tools/git.py                Git log/show/blame
reviewcrew/tools/semgrep.py            可选静态信号 Provider
reviewcrew/agents/base.py              Pydantic AI 公共运行时
reviewcrew/agents/defect.py            DefectAgent
reviewcrew/agents/intent.py            IntentAgent
reviewcrew/agents/verifier.py          VerifierAgent
reviewcrew/agents/prompts/*.md          中文系统提示词
reviewcrew/pipeline/dedupe.py          确定性去重
reviewcrew/pipeline/orchestrator.py     阶段编排、预算和降级
reviewcrew/pipeline/report.py           JSON 与 Markdown 报告
reviewcrew/server/app.py                FastAPI REST/SSE
reviewcrew/server/replay.py             历史事件回放
benchmark/dataset.yaml                 Greptile 案例清单
benchmark/models.py                    DatasetEntry 与 JudgeResult
benchmark/runner.py                    quick/case/full 运行入口
benchmark/judge.py                     文件、位置、语义命中判定
benchmark/report.py                    评测摘要
tests/                                 后端自动测试
web/src/contracts.ts                   与后端一致的前端协议
web/src/stores/review.ts               事件归约状态
web/src/api/client.ts                  REST/SSE/Replay 客户端
web/src/pages/*.vue                    启动、实时、结果、评测页面
web/src/components/*.vue               Agent、阶段、Finding 组件
web/src/fixtures/demo-events.jsonl     稳定演示事件
```

---

### Task 1: 公共协议与工程地基

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `reviewcrew/__init__.py`
- Create: `reviewcrew/config.py`
- Create: `reviewcrew/schemas.py`
- Test: `tests/test_config.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Produces: `Config.from_env() -> Config`
- Produces: `ReviewRequest`, `PRData`, `ChangedFile`, `DiffHunk`, `CodeEvidence`, `TextEvidence`, `StaticSignal`, `ContextPack`, `Finding`, `Verdict`, `ReviewResult`
- Constraint: 字段必须与设计规范第 5 节一致。

- [ ] **Step 1: 创建最小 Python 工程配置**

在 `pyproject.toml` 声明 Python `>=3.12`，运行依赖包括 `pydantic>=2.8`、`pydantic-settings`、`pydantic-ai`、`httpx`、`fastapi`、`uvicorn`、`pyyaml`，开发依赖包括 `pytest`、`pytest-asyncio`、`respx`。

- [ ] **Step 2: 写配置失败测试**

```python
def test_config_rejects_invalid_global_timeout(monkeypatch):
    monkeypatch.setenv("REVIEWCREW_GLOBAL_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValidationError):
        Config.from_env()
```

- [ ] **Step 3: 写 Schema 失败测试**

```python
def test_finding_requires_confidence_in_range():
    with pytest.raises(ValidationError):
        make_finding(confidence=1.1)


def test_review_request_requires_exactly_one_mode():
    with pytest.raises(ValidationError):
        ReviewRequest(pr_url="https://example/pr/1", replay_run_id="run-1")
```

- [ ] **Step 4: 运行测试并确认失败**

Run: `pytest tests/test_config.py tests/test_schemas.py -v`

Expected: FAIL，因为模块或校验尚不存在。

- [ ] **Step 5: 实现配置和完整领域模型**

所有公开类和复杂校验器写中文 docstring。默认预算为 `30/90/300/120/30/600` 秒；`Config` 从环境读取 GLM base URL、模型名、API Key、GitHub Token、并发数和运行目录。

- [ ] **Step 6: 运行测试并确认通过**

Run: `pytest tests/test_config.py tests/test_schemas.py -v`

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add pyproject.toml .env.example .gitignore reviewcrew tests/test_config.py tests/test_schemas.py
git commit -m "feat: 定义审查领域模型与工程配置"
```

### Task 2: PipelineEvent、事件持久化与 Replay 基础

**Files:**
- Create: `reviewcrew/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: `Config.runs_dir`
- Produces: `EventStore.create_run() -> str`
- Produces: `EventStore.emit(run_id: str, event_type: EventType, data: dict[str, Any]) -> PipelineEvent`
- Produces: `EventStore.subscribe(run_id: str) -> AsyncIterator[PipelineEvent]`
- Produces: `EventStore.read(run_id: str) -> list[PipelineEvent]`

- [ ] **Step 1: 写事件顺序和持久化测试**

```python
def test_events_receive_monotonic_sequence(tmp_path):
    store = EventStore(tmp_path)
    run_id = store.create_run()
    first = store.emit(run_id, "review.started", {})
    second = store.emit(run_id, "stage.started", {"stage": "loading_pr"})
    assert [first.sequence, second.sequence] == [1, 2]
    assert store.read(run_id) == [first, second]
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest tests/test_events.py -v`

Expected: FAIL，因为 `EventStore` 不存在。

- [ ] **Step 3: 实现 JSONL 事件存储和异步订阅**

每条事件立即刷新到 `runs/{run_id}/events.jsonl`，其中 `{run_id}` 由 `EventStore.create_run()` 生成。日志使用中文，但事件枚举保持英文。订阅者断开时不终止生产者。

- [ ] **Step 4: 运行测试并确认通过**

Run: `pytest tests/test_events.py -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add reviewcrew/events.py tests/test_events.py
git commit -m "feat: 实现审查事件存储与订阅"
```

### Task 3: Unified Diff 解析

**Files:**
- Create: `reviewcrew/diff/__init__.py`
- Create: `reviewcrew/diff/parser.py`
- Create: `tests/fixtures/sample.diff`
- Test: `tests/test_diff_parser.py`

**Interfaces:**
- Produces: `parse_unified_diff(raw_diff: str) -> list[ChangedFile]`
- Produces: `changed_line_set(files: list[ChangedFile]) -> dict[str, set[int]]`

- [ ] **Step 1: 创建包含新增、删除、重命名和多 hunk 的 fixture**

Fixture 必须包含新增行 `+`, 删除行 `-`、上下文行、`/dev/null` 和 rename header。

- [ ] **Step 2: 写解析失败测试**

```python
def test_parse_diff_tracks_only_new_changed_lines(sample_diff):
    files = parse_unified_diff(sample_diff)
    assert files[0].hunks[0].changed_lines == [12, 13]


def test_parse_diff_supports_renamed_file(sample_diff):
    renamed = next(item for item in parse_unified_diff(sample_diff) if item.status == "renamed")
    assert renamed.old_path is not None
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `pytest tests/test_diff_parser.py -v`

- [ ] **Step 4: 实现逐行状态机解析器**

不得依赖 GitHub 特定 HTML。过滤二进制文件；lockfile 和生成文件只记录为 skipped warning，不交给 Agent。

- [ ] **Step 5: 运行测试并确认通过**

Run: `pytest tests/test_diff_parser.py -v`

- [ ] **Step 6: 提交**

```powershell
git add reviewcrew/diff tests/fixtures/sample.diff tests/test_diff_parser.py
git commit -m "feat: 解析拉取请求差异与修改行"
```

### Task 4: GitHub PR 和本地 Git 加载

**Files:**
- Create: `reviewcrew/github/__init__.py`
- Create: `reviewcrew/github/pr_loader.py`
- Test: `tests/test_pr_loader.py`

**Interfaces:**
- Consumes: `ReviewRequest`
- Produces: `async load_pr(request: ReviewRequest, config: Config) -> PRData`
- Uses: GitHub REST `GET /repos/{owner}/{repo}/pulls/{number}` with diff media type.

- [ ] **Step 1: 写 GitHub URL 解析和 HTTP Mock 测试**

```python
@pytest.mark.asyncio
async def test_load_github_pr_returns_pr_data(respx_mock):
    respx_mock.get("https://api.github.com/repos/acme/demo/pulls/7").mock(
        return_value=httpx.Response(200, json=github_pr_fixture)
    )
    result = await load_pr(ReviewRequest(pr_url="https://github.com/acme/demo/pull/7"), config)
    assert result.head_sha == "head123"
```

- [ ] **Step 2: 写本地仓库错误测试**

验证路径不存在、ref 不存在和 diff 命令失败时返回中文可操作错误。

- [ ] **Step 3: 运行测试并确认失败**

Run: `pytest tests/test_pr_loader.py -v`

- [ ] **Step 4: 实现 GitHub 和本地两种 Loader**

GitHub Token 可选；不得记录 Token。本地模式使用参数化的 `git diff $baseRef...$headRef` 获取 diff，`$baseRef` 和 `$headRef` 必须先通过 `git rev-parse --verify` 校验，命令工作目录必须固定为指定仓库路径。

- [ ] **Step 5: 运行测试并确认通过**

Run: `pytest tests/test_pr_loader.py -v`

- [ ] **Step 6: 提交**

```powershell
git add reviewcrew/github tests/test_pr_loader.py
git commit -m "feat: 加载 GitHub 与本地拉取请求"
```

### Task 5: 只读工具箱和 Context Builder

**Files:**
- Create: `reviewcrew/tools/__init__.py`
- Create: `reviewcrew/tools/files.py`
- Create: `reviewcrew/tools/search.py`
- Create: `reviewcrew/tools/git.py`
- Create: `reviewcrew/tools/semgrep.py`
- Create: `reviewcrew/context/__init__.py`
- Create: `reviewcrew/context/builder.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_context_builder.py`

**Interfaces:**
- Produces: `safe_read(repo: Path, relative_path: str, start: int, end: int) -> CodeEvidence`
- Produces: `search_code(repo: Path, query: str, limit: int = 20) -> list[CodeEvidence]`
- Produces: `find_related_tests(repo: Path, changed_path: str) -> list[CodeEvidence]`
- Produces: `git_history(repo: Path, relative_path: str, limit: int = 10) -> list[TextEvidence]`
- Produces: `git_blame(repo: Path, relative_path: str, start: int, end: int) -> list[TextEvidence]`
- Produces: `async run_semgrep(repo: Path, files: list[str], timeout: float) -> list[StaticSignal]`
- Produces: `async build_context(pr: PRData, repo: Path, config: Config) -> list[ContextPack]`

- [ ] **Step 1: 写路径穿越和范围读取失败测试**

```python
def test_safe_read_rejects_path_escape(tmp_path):
    with pytest.raises(ToolAccessError, match="仓库范围"):
        safe_read(tmp_path, "../secret.txt", 1, 10)
```

- [ ] **Step 2: 写 Context 构建测试**

断言修改函数周边代码、同名测试、README 片段和检索说明进入 ContextPack；超预算时 `truncated=True`。

- [ ] **Step 3: 运行测试并确认失败**

Run: `pytest tests/test_tools.py tests/test_context_builder.py -v`

- [ ] **Step 4: 实现只读工具**

优先使用 `rg`，不可用时使用 Python 受限文本搜索。所有返回限制条数和字符数。Semgrep 不存在或超时返回空列表并写中文 warning。

- [ ] **Step 5: 实现 Context Builder**

按同目录和修改符号聚类 hunk。顺序优先级：diff、完整函数、直接相关代码、测试、项目文档、Git 历史、静态信号。默认单 Pack 字符预算配置化。

- [ ] **Step 6: 运行测试并确认通过**

Run: `pytest tests/test_tools.py tests/test_context_builder.py -v`

- [ ] **Step 7: 提交**

```powershell
git add reviewcrew/tools reviewcrew/context tests/test_tools.py tests/test_context_builder.py
git commit -m "feat: 构建差异中心上下文与只读工具"
```

### Task 6: GLM 5.2 与 Agent 公共运行时

**Files:**
- Create: `reviewcrew/llm/__init__.py`
- Create: `reviewcrew/llm/glm.py`
- Create: `reviewcrew/agents/__init__.py`
- Create: `reviewcrew/agents/base.py`
- Test: `tests/test_glm.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Produces: `build_glm_model(config: Config) -> Model`
- Produces: `class ReviewAgentProtocol(Protocol): async run(context: ContextPack) -> list[Finding]`
- Produces: `class VerifierProtocol(Protocol): async run(findings: list[Finding], context: list[ContextPack]) -> list[Verdict]`
- Produces: `AgentRuntime.run_expert(...)` and `AgentRuntime.run_verifier(...)`

- [ ] **Step 1: 写模型构建测试**

验证模型名和 base URL 来自 Config，API Key 不出现在 `repr` 和日志中。

- [ ] **Step 2: 使用 Pydantic AI TestModel 写结构化输出测试**

测试工具调用事件、合法 Finding、校验失败重试和请求数限制。

- [ ] **Step 3: 运行测试并确认失败**

Run: `pytest tests/test_glm.py tests/test_agent_runtime.py -v`

- [ ] **Step 4: 实现 GLM 模型和 AgentRuntime**

通过 OpenAI 兼容 Provider 接入；temperature 使用模型支持的最低稳定值。公开日志使用中文，禁止记录完整 Prompt 和响应原文。

- [ ] **Step 5: 实现显式 smoke 命令**

Run: `python -m reviewcrew.llm.glm --smoke`

无 `GLM_API_KEY` 时输出中文说明并以非零状态退出；有 Key 时要求模型返回固定 Pydantic 对象。

- [ ] **Step 6: 运行离线测试并确认通过**

Run: `pytest tests/test_glm.py tests/test_agent_runtime.py -v`

- [ ] **Step 7: 提交**

```powershell
git add reviewcrew/llm reviewcrew/agents/base.py tests/test_glm.py tests/test_agent_runtime.py
git commit -m "feat: 接入 GLM 5.2 与 Agent 运行时"
```

### Task 7: DefectAgent 与 IntentAgent

**Files:**
- Create: `reviewcrew/agents/defect.py`
- Create: `reviewcrew/agents/intent.py`
- Create: `reviewcrew/agents/prompts/defect.md`
- Create: `reviewcrew/agents/prompts/intent.md`
- Test: `tests/test_expert_agents.py`

**Interfaces:**
- Produces: `DefectAgent.run(context: ContextPack) -> list[Finding]`
- Produces: `IntentAgent.run(context: ContextPack) -> list[Finding]`
- Both implement: `ReviewAgentProtocol`

- [ ] **Step 1: 写 Prompt 合同测试**

断言 Defect Prompt 明确包含静态、安全、内存/资源三个分节；Intent Prompt 明确包含意图总结、行为总结、偏差比较、边界与架构检查。

- [ ] **Step 2: 写 Fake Model 输出测试**

构造一个 SQL 拼接 Context 和一个 `sample_rate=0.0` 被 falsy 跳过的 Context，断言两个 Agent 分别输出正确类别和修改行。

- [ ] **Step 3: 运行测试并确认失败**

Run: `pytest tests/test_expert_agents.py -v`

- [ ] **Step 4: 实现两个 Agent**

DefectAgent 可访问 Semgrep 信号和只读代码工具；IntentAgent 优先读取 PR 描述、测试、项目文档和相关代码。禁止输出纯风格建议。

- [ ] **Step 5: 运行测试并确认通过**

Run: `pytest tests/test_expert_agents.py -v`

- [ ] **Step 6: 提交**

```powershell
git add reviewcrew/agents/defect.py reviewcrew/agents/intent.py reviewcrew/agents/prompts tests/test_expert_agents.py
git commit -m "feat: 实现缺陷与意图审查 Agent"
```

### Task 8: 去重与 VerifierAgent

**Files:**
- Create: `reviewcrew/pipeline/__init__.py`
- Create: `reviewcrew/pipeline/dedupe.py`
- Create: `reviewcrew/agents/verifier.py`
- Create: `reviewcrew/agents/prompts/verifier.md`
- Test: `tests/test_dedupe.py`
- Test: `tests/test_verifier.py`

**Interfaces:**
- Produces: `deduplicate_findings(findings: list[Finding]) -> list[Finding]`
- Produces: `VerifierAgent.run(findings: list[Finding], context: list[ContextPack]) -> list[Verdict]`

- [ ] **Step 1: 写确定性去重测试**

同文件重叠行且同类别合并；不同触发机制不得误合并；合并结果保留更高置信度和全部去重证据。

- [ ] **Step 2: 写 Verifier Fake Model 测试**

一条存在上游校验的候选应拒绝为 `false_positive`；一条真实可达候选应接受为 `confirmed`。

- [ ] **Step 3: 运行测试并确认失败**

Run: `pytest tests/test_dedupe.py tests/test_verifier.py -v`

- [ ] **Step 4: 实现去重和 Verifier**

Verifier 使用干净上下文，只接收候选结论、代码证据和必要上下文。默认拒绝低于 0.6 的最终置信度，最终最多保留 8 条。

- [ ] **Step 5: 运行测试并确认通过**

Run: `pytest tests/test_dedupe.py tests/test_verifier.py -v`

- [ ] **Step 6: 提交**

```powershell
git add reviewcrew/pipeline/dedupe.py reviewcrew/agents/verifier.py reviewcrew/agents/prompts/verifier.md tests/test_dedupe.py tests/test_verifier.py
git commit -m "feat: 验证并去重候选问题"
```

### Task 9: Orchestrator、报告与 CLI

**Files:**
- Create: `reviewcrew/pipeline/orchestrator.py`
- Create: `reviewcrew/pipeline/report.py`
- Create: `reviewcrew/cli.py`
- Test: `tests/test_orchestrator.py`
- Test: `tests/test_report.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `Orchestrator.review(request: ReviewRequest) -> ReviewResult`
- Produces: `render_markdown(result: ReviewResult) -> str`
- Produces: CLI `python -m reviewcrew.cli review ...`

- [ ] **Step 1: 写 Fake 端到端状态机测试**

断言完整事件顺序、两个专家通过 `asyncio.gather` 并行、Verifier 在去重后运行、报告事件最后发出。

- [ ] **Step 2: 写降级测试**

覆盖一个专家异常、Verifier 异常、阶段超时和全局超时；断言状态为 `partial` 且中文 warning 可见。

- [ ] **Step 3: 写报告测试**

Markdown 必须包含严重度、类别、文件行号、触发条件、影响、证据、建议、Verifier 状态和总耗时。

- [ ] **Step 4: 运行测试并确认失败**

Run: `pytest tests/test_orchestrator.py tests/test_report.py tests/test_cli.py -v`

- [ ] **Step 5: 实现 Orchestrator 和报告**

阶段预算使用 `asyncio.timeout`。每个阶段发 `stage.started/completed/failed`。所有结果写入 `runs/{run_id}/result.json` 和 `runs/{run_id}/report.md`。

- [ ] **Step 6: 实现 CLI**

```text
python -m reviewcrew.cli review --pr https://github.com/ai-code-review-evaluation/sentry-greptile/pull/1
python -m reviewcrew.cli review --repo $env:REVIEWCREW_SMOKE_REPO --base $env:REVIEWCREW_SMOKE_BASE --head $env:REVIEWCREW_SMOKE_HEAD
python -m reviewcrew.cli replay --run-id $env:REVIEWCREW_REPLAY_RUN_ID
```

- [ ] **Step 7: 运行测试并确认通过**

Run: `pytest tests/test_orchestrator.py tests/test_report.py tests/test_cli.py -v`

- [ ] **Step 8: 提交**

```powershell
git add reviewcrew/pipeline reviewcrew/cli.py tests/test_orchestrator.py tests/test_report.py tests/test_cli.py
git commit -m "feat: 编排审查流程并生成报告"
```

### Task 10: FastAPI、SSE 与 Replay

**Files:**
- Create: `reviewcrew/server/__init__.py`
- Create: `reviewcrew/server/app.py`
- Create: `reviewcrew/server/replay.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `POST /api/reviews`
- Produces: `GET /api/reviews/{run_id}`
- Produces: `GET /api/reviews/{run_id}/events`
- Produces: `GET /api/reviews/{run_id}/report`
- Produces: `GET /api/runs`
- Produces: `GET /api/replays/{run_id}/events?speed=2`
- Produces: `GET /api/benchmarks/latest`

- [ ] **Step 1: 写 API 和 SSE 测试**

使用 FastAPI TestClient 验证启动响应、404 中文错误、SSE `data:` 格式、完成事件后流结束。

- [ ] **Step 2: 写 Replay 时序测试**

给定三条带时间戳事件，`speed=2` 应保持顺序并缩短间隔；测试中注入虚拟时钟，禁止真实 sleep。

- [ ] **Step 3: 运行测试并确认失败**

Run: `pytest tests/test_server.py -v`

- [ ] **Step 4: 实现后台审查任务、SSE 和 Replay**

接口返回错误使用中文 `detail`。后台任务失败必须发 `review.failed`，不得让 SSE 永久悬挂。

- [ ] **Step 5: 运行测试并确认通过**

Run: `pytest tests/test_server.py -v`

- [ ] **Step 6: 提交**

```powershell
git add reviewcrew/server tests/test_server.py
git commit -m "feat: 提供审查接口与事件回放"
```

### Task 11: Greptile Benchmark 数据、Judge 与报告

**Files:**
- Create: `benchmark/__init__.py`
- Create: `benchmark/models.py`
- Create: `benchmark/dataset.yaml`
- Create: `benchmark/runner.py`
- Create: `benchmark/judge.py`
- Create: `benchmark/report.py`
- Test: `tests/test_benchmark_models.py`
- Test: `tests/test_benchmark_judge.py`
- Test: `tests/test_benchmark_runner.py`

**Interfaces:**
- Produces: `load_dataset(path: Path, ready_only: bool = True) -> list[DatasetEntry]`
- Produces: `judge_case(entry: DatasetEntry, result: ReviewResult) -> JudgeResult`
- Produces: commands `--mode quick`, `--mode full`, `--case sentry-01`

- [ ] **Step 1: 填入 5 个仓库的最小数据集骨架**

每个仓库至少一个案例记录，未核对案例使用 `needs_review`，禁止使用伪 SHA 或伪成功链接冒充 `ready`。

- [ ] **Step 2: 写 Dataset 校验测试**

`ready` 案例必须具有 fork、test PR、base/head、introducing/fixing commit、目标位置和漏洞描述。

- [ ] **Step 3: 写三层 Judge 测试**

覆盖文件不匹配、行区间直接命中、正负 10 行容差、语义不匹配和 Verifier 已拒绝。

- [ ] **Step 4: 写 Fake Runner 测试**

`quick` 每仓库最多选择一个 ready 案例，输出 `cases.jsonl`、`summary.json` 和 `summary.md`。

- [ ] **Step 5: 运行测试并确认失败**

Run: `pytest tests/test_benchmark_models.py tests/test_benchmark_judge.py tests/test_benchmark_runner.py -v`

- [ ] **Step 6: 实现数据模型、Judge、Runner 和报告**

主命中率只使用实际完成运行的 ready 案例。报告同时统计非目标 Finding、耗时、超时、Verifier 接受/拒绝和需要人工复核数。

- [ ] **Step 7: 运行 Fake 快速评测**

Run: `python -m benchmark.runner --mode quick --runner fake`

Expected: 生成结果目录，不访问网络。

- [ ] **Step 8: 提交**

```powershell
git add benchmark tests/test_benchmark_models.py tests/test_benchmark_judge.py tests/test_benchmark_runner.py
git commit -m "feat: 实现 Greptile Benchmark 评测流程"
```

### Task 12: Vue 3 前端协议和 Replay 驱动页面

**Files:**
- Create: `web/package.json`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig.json`
- Create: `web/src/main.ts`
- Create: `web/src/App.vue`
- Create: `web/src/contracts.ts`
- Create: `web/src/stores/review.ts`
- Create: `web/src/api/client.ts`
- Create: `web/src/fixtures/demo-events.jsonl`
- Create: `web/src/pages/StartPage.vue`
- Create: `web/src/pages/ReviewPage.vue`
- Create: `web/src/pages/ResultPage.vue`
- Create: `web/src/pages/BenchmarkPage.vue`
- Create: `web/src/components/StageProgress.vue`
- Create: `web/src/components/AgentCard.vue`
- Create: `web/src/components/FindingCard.vue`
- Test: `web/src/stores/review.spec.ts`

**Interfaces:**
- Consumes: 设计规范第 6 节全部 PipelineEvent。
- Consumes: Task 10 REST/SSE 路径。
- Produces: `applyEvent(event: PipelineEvent): void`。

- [ ] **Step 1: 初始化 Vue 3、TypeScript、Vite、Pinia 和 Vitest**

依赖保持最少；第一版不引入复杂图编辑器，三 Agent 拓扑使用 CSS Grid 和连线实现。

- [ ] **Step 2: 写 Store 事件归约失败测试**

输入 `review.started → agent.started → agent.candidate → verifier.rejected → review.completed`，断言阶段、Agent、候选和最终状态正确。

- [ ] **Step 3: 运行测试并确认失败**

Run: `npm test -- --run`

Workdir: `web`

- [ ] **Step 4: 实现 contracts、Store 和 API Client**

注释和用户文案使用中文。真实 SSE 和 Replay 都调用同一个 `applyEvent`。

- [ ] **Step 5: 创建完整 Demo Replay**

Fixture 必须包含两个专家并行、至少两个候选、一个 Verifier 接受、一个拒绝和最终报告事件。

- [ ] **Step 6: 实现四个页面和三个核心组件**

必须展示 PR 输入、阶段进度、600 秒预算、三 Agent 状态、工具摘要、Finding 证据、Verifier 结论、Benchmark 链接和 Replay 按钮。

- [ ] **Step 7: 运行测试与生产构建**

Run: `npm test -- --run`

Run: `npm run build`

Workdir: `web`

Expected: 全部成功。

- [ ] **Step 8: 提交**

```powershell
git add web
git commit -m "feat: 实现 Vue 审查与评测控制台"
```

### Task 13: 全栈契约集成与真实冒烟

**Files:**
- Create: `tests/test_end_to_end.py`
- Modify: `web/src/api/client.ts`
- Modify: `reviewcrew/server/app.py`

**Interfaces:**
- Verifies: `ContextPack → Finding → Verdict → ReviewResult → PipelineEvent → Vue Store`

- [ ] **Step 1: 写 Fake 全链路测试**

使用临时 Git 仓库构造 base/head，运行 Orchestrator，断言报告、事件、结果文件和最终 Finding 都存在。

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest tests/test_end_to_end.py -v`

- [ ] **Step 3: 修复跨模块协议差异**

只能修复契约适配和真实缺陷，不在此任务中重新设计 Schema。

- [ ] **Step 4: 运行全部后端和前端验证**

Run: `pytest -q`

Run: `npm test -- --run`

Run: `npm run build`

Workdir for npm: `web`

- [ ] **Step 5: 执行真实 GLM smoke**

Run: `python -m reviewcrew.llm.glm --smoke`

Expected: 有 Key 时成功；无 Key 时记录为待用户提供，不伪造成功。

- [ ] **Step 6: 执行一个真实 PR 或本地提交审查**

先设置 `REVIEWCREW_SMOKE_REPO`、`REVIEWCREW_SMOKE_BASE`、`REVIEWCREW_SMOKE_HEAD`，然后运行：

`python -m reviewcrew.cli review --repo $env:REVIEWCREW_SMOKE_REPO --base $env:REVIEWCREW_SMOKE_BASE --head $env:REVIEWCREW_SMOKE_HEAD`

Expected: 600 秒内生成 `result.json`、`report.md` 和 `events.jsonl`。

- [ ] **Step 7: 提交**

```powershell
git add tests/test_end_to_end.py reviewcrew web/src/api/client.ts
git commit -m "test: 验证全栈审查工作流"
```

### Task 14: 中文 README、评测报告与演示材料

**Files:**
- Create: `README.md`
- Create: `docs/评测报告.md`
- Create: `docs/演示脚本.md`

**Interfaces:**
- Documents: 安装、配置、CLI、服务端、前端、Benchmark、Replay、降级和故障排查。

- [ ] **Step 1: 编写 README**

必须提供 PowerShell 命令：创建虚拟环境、安装 Python、安装前端、配置 `.env`、运行测试、运行 CLI、启动 FastAPI、启动 Vue、运行 Benchmark。

- [ ] **Step 2: 编写知识库维护方案**

明确第一版使用文档、测试、配置和 Git 历史；说明合并触发的增量索引方案属于维护设计，禁止宣称未实现能力已上线。

- [ ] **Step 3: 编写评测报告模板并填入真实结果**

每行包含仓库、语言、测试 PR、上游修复 PR、目标漏洞、是否命中、Finding 定位、耗时和 Replay 标识。未运行和失败必须明确。

- [ ] **Step 4: 编写三分钟演示脚本**

固定分镜：痛点 20 秒、启动 PR 20 秒、并行审查 50 秒、Verifier 35 秒、Finding 35 秒、Benchmark 30 秒、优势总结 20 秒。

- [ ] **Step 5: 验证 README 命令和链接**

在干净终端至少执行安装后的测试、CLI Fake 模式和前端构建。检查所有成功 PR 链接可访问。

- [ ] **Step 6: 提交**

```powershell
git add README.md docs/评测报告.md docs/演示脚本.md
git commit -m "docs: 补充安装评测与演示说明"
```

### Task 15: 次日上午三 Agent 与前端专项调优

**Files:**
- Modify: `reviewcrew/agents/prompts/defect.md`
- Modify: `reviewcrew/agents/prompts/intent.md`
- Modify: `reviewcrew/agents/prompts/verifier.md`
- Modify: `reviewcrew/context/builder.py`
- Modify: `web/src/**/*.vue`
- Create: `benchmark/results/ITERATION_LOG.md`

**Interfaces:**
- Preserves: 所有公共 Schema、HTTP 路径和 PipelineEvent 类型。

- [ ] **Step 1: 09:00 建立共同 baseline**

Run: `python -m benchmark.runner --mode quick`

记录 Git SHA、模型、案例、命中、误报和耗时。

- [ ] **Step 2: 开发者 1 调优 DefectAgent**

只修改 Defect Prompt、Semgrep 信号使用和对应测试。优先安全、静态、内存案例。每次有效变化单独提交。

- [ ] **Step 3: 开发者 2 调优 IntentAgent**

只修改 Intent Prompt、相关上下文选择和对应测试。优先业务逻辑、逻辑和架构案例。每次有效变化单独提交。

- [ ] **Step 4: 开发者 3 调优 VerifierAgent**

只修改 Verifier Prompt、阈值、去重和 Judge 人工复核记录。重点检查 Verifier 误杀。每次有效变化单独提交。

- [ ] **Step 5: 开发者 4 优化前端**

只优化真实 SSE、Replay、信息层级、Finding 展示、Benchmark 页面和录屏稳定性，不修改公共协议。

- [ ] **Step 6: 10:30 合并最佳调优并回归**

Run: `pytest -q`

Run: `npm test -- --run`

Run: `npm run build`

- [ ] **Step 7: 11:00 运行最终快速评测**

Run: `python -m benchmark.runner --mode quick`

只在有时间且 quick 稳定后运行更多 ready 案例。

- [ ] **Step 8: 11:30 冻结代码**

更新评测报告、选择最佳 Replay、检查敏感信息、提交最终代码。12:00 后停止功能开发。

---

## 最终验证清单

在宣称完成前逐项执行并保存输出：

- [ ] `pytest -q`
- [ ] `npm test -- --run`，工作目录 `web`
- [ ] `npm run build`，工作目录 `web`
- [ ] `python -m benchmark.runner --mode quick --runner fake`
- [ ] `python -m reviewcrew.llm.glm --smoke`，若缺 Key 则明确记录
- [ ] 一个真实 PR 或本地 base/head 审查
- [ ] `result.json`、`report.md`、`events.jsonl` 均生成
- [ ] 前端能够连接真实 SSE 或播放同一运行的 Replay
- [ ] README 命令可复制执行
- [ ] 评测报告不虚报完整 50 案例成绩
- [ ] `git status --short` 中没有误提交的密钥、缓存、Fork 仓库或 IDE 文件
- [ ] 所有本任务变更已按能力分批提交

## Goal 推荐目标文本

创建 Goal 时使用以下完整目标，避免只写“完成项目”导致范围漂移：

> 严格执行 `docs/superpowers/plans/2026-07-29-reviewcrew-implementation.md`，在 2026-07-30 12:00 前实现 ReviewCrew 的完整可运行版本。必须先阅读对应设计规范，按 Task 顺序使用测试驱动开发，频繁提交 Git，并在每次续跑时从第一个未完成 checkbox 继续。系统必须包含 GLM 5.2、DefectAgent、IntentAgent、VerifierAgent、PR diff 和上下文工具、600 秒 watchdog、JSON/Markdown 报告、FastAPI REST/SSE/Replay、Vue 3 前端和 Greptile Benchmark quick/case/full 流程。所有代码注释、docstring、TSDoc、运行日志、错误提示和报告正文使用中文；不得保存密钥、完整 Prompt 或隐藏思维链。外部服务失败时先完成 Fake、fixture、Replay 和离线测试并实现明确降级。只有后端测试、前端测试与构建、Fake 端到端、Benchmark Fake quick 和至少一个真实审查完成后才能标记 Goal 完成；若缺少 GLM API Key，必须明确记录真实 smoke 未执行，不得伪造成功。12:00 后不得新增功能，只允许修复阻断交付的问题。
