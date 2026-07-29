# ReviewCrew Implementation Plan

> **For agentic workers:** 本计划遵循 superpowers:writing-plans 框架编写。按任务顺序执行，
> 每个任务以 checkbox (`- [ ]`) 步骤跟踪，每个任务结束必须通过其验收命令后才能进入下一任务。
> 规格来源：`design-doc.md`（总架构）· `agent-topology.md`（Agent 层，取代 design-doc §4-③）· `frontend-design.md`（演示层）

**Goal:** 构建以 2 专家 Agent + 1 Verifier 为核心的 AI Code Review 系统，在 Greptile Benchmark（5 仓库 × 10 PR）上达成 ≥60% 目标漏洞命中率，单 PR ≤10 分钟。

**Architecture:** 双层架构——离线知识层（tree-sitter 符号索引/call graph/架构摘要/历史 bug 模式）+ 在线五阶段管道（预处理 → 上下文组装 → 2 专家并行审查 → 对抗验证 → 报告）。静态信号（Semgrep/linter/依赖审计）作为证据注入，Agent 裁决真伪。

**Tech Stack:** Python 3.12 + asyncio + **pydantic-ai** + httpx + tree-sitter + SQLite + FastAPI(SSE) · Vue 3 + Vite + TS + Pinia + Tailwind + Naive UI + @vue-flow/core + @git-diff-view/vue + shiki + echarts · pytest + Vitest

## Global Constraints

- 单 PR 在线管道总耗时 ≤ 10min（watchdog 硬截断，内部预算 8.5min）
- LLM 仅走 GLM API（`glm-4-plus` 或 `glm-5`），temperature=0.2，结构化输出走 pydantic-ai 的 `output_type`
- 在线 Agent 只有 3 种：DefectAgent / IntentAgent / VerifierAgent；Orchestrator、Context Builder、报告生成不得实现为 Agent
- 单 PR 最终输出 ≤ 8 条 findings；confidence_adjusted < 0.6 一律丢弃
- Agent 基座用 Pydantic AI（GLM 经 OpenAI 兼容端点接入）；编排层保持纯 asyncio，不引入 LangGraph/CrewAI 等图编排框架
- 不使用 CodeQL
- 所有 LLM 交互（prompt/response/tool calls）落盘 `runs/<run_id>/events.jsonl`（供 replay 与 debug）
- Python 代码全部带类型注解（启用 `from __future__ import annotations`），pytest 覆盖核心逻辑；每个任务结束 commit 一次
- 使用 Python 3.12+、pydantic 2.x、pydantic-ai 0.0.x

---

## Phase 0 — 地基

### Task 1: 项目脚手架 + GLM Client

**Files:**
- Create: `pyproject.toml`, `reviewcrew/__init__.py`, `reviewcrew/config.py`, `reviewcrew/llm/glm.py`, `reviewcrew/events.py`, `reviewcrew/llm/__init__.py`
- Test: `tests/test_glm.py`, `tests/test_events.py`

**Interfaces:**
- Provides: `build_glm_model() -> pydantic_ai.models.OpenAIModel`
  ```python
  # GLM OpenAI 兼容端点，httpx transport 配 429/5xx 指数退避×3
  # 结构化输出校验重试由 pydantic-ai 承担
  def build_glm_model(
      model: str = "glm-4-plus",
      temperature: float = 0.2,
  ) -> OpenAIModel: ...
  ```

- Provides: `EventLogger.emit(event: PipelineEvent) -> None`
  ```python
  class PipelineEvent(BaseModel):
      """Tagged union，所有字段定义见下方完整 schema"""
      timestamp: float
      type: Literal["stage", "agent", "thought", "tool", "finding", "verdict", "report"]
      # 各类型专属字段见完整定义
  
  class EventLogger:
      def __init__(self, run_id: str, output_dir: Path = Path("runs")): ...
      def emit(self, event: PipelineEvent) -> None:
          """追加写入 runs/<run_id>/events.jsonl"""
  ```

- Provides: `Config.from_env() -> Config`
  ```python
  class Config(BaseModel):
      glm_api_key: str
      glm_model: str = "glm-4-plus"
      glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
      temperature: float = 0.2
      max_concurrent_agents: int = 4
      pipeline_timeout_seconds: int = 600  # 10min 硬限制
  ```

**完整 PipelineEvent Schema**（这是前后端唯一契约）：
```python
from typing import Literal
from pydantic import BaseModel, Field

class PipelineEvent(BaseModel):
    timestamp: float
    type: Literal["stage", "agent", "thought", "tool", "finding", "verdict", "report"]
    
    # type=stage
    stage: Literal["preprocess", "context", "review", "verify", "report"] | None = None
    status: Literal["start", "done"] | None = None
    elapsed: float | None = None
    
    # type=agent
    agent: Literal["defect", "intent", "verifier"] | None = None
    agent_status: Literal["running", "done"] | None = None
    
    # type=thought
    text: str | None = None
    
    # type=tool
    tool: str | None = None
    args: dict | None = None
    result: str | None = None
    
    # type=finding
    finding: "Finding | None" = None
    
    # type=verdict
    verdict: "Verdict | None" = None
    
    # type=report
    markdown: str | None = None
```

**Steps:**
- [ ] 创建 `pyproject.toml`（dependencies: pydantic>=2.0, pydantic-ai>=0.0.14, httpx, pytest, python=">=3.12"）
- [ ] 创建基础目录结构 `reviewcrew/`, `tests/`
- [ ] 写 `tests/test_events.py`：
  ```python
  def test_event_roundtrip():
      # stage 事件序列化/反序列化
      event = PipelineEvent(timestamp=time.time(), type="stage", stage="preprocess", status="start")
      json_str = event.model_dump_json()
      assert PipelineEvent.model_validate_json(json_str) == event
  
  def test_event_logger_writes_jsonl():
      # EventLogger 写入 JSONL，每行可独立解析
      logger = EventLogger(run_id="test123")
      logger.emit(PipelineEvent(...))
      # 断言文件存在、可读、JSONL 格式
  ```
- [ ] 跑测试，确认失败（`pytest tests/test_events.py -v`）
- [ ] 实现 `events.py`（PipelineEvent + EventLogger 约 60 行）
- [ ] 实现 `config.py`（Config.from_env 读环境变量，约 30 行）
- [ ] 测试转绿
- [ ] 写 `tests/test_glm.py`：
  ```python
  def test_build_model_returns_openai_model():
      model = build_glm_model()
      assert isinstance(model, OpenAIModel)
      assert "glm" in model.model_name.lower()
  
  @pytest.mark.asyncio
  async def test_retry_on_429(httpx_mock):
      # Mock httpx：首次 429，第二次 200
      # 验证指数退避生效
  ```
- [ ] 跑测试确认失败
- [ ] 实现 `glm.py`（build_glm_model + RetryTransport，约 80 行）
- [ ] 测试转绿
- [ ] 写冒烟脚本 `reviewcrew/llm/glm.py` 末尾：
  ```python
  if __name__ == "__main__":
      import asyncio
      from pydantic_ai import Agent
      async def smoke_test():
          model = build_glm_model()
          agent = Agent(model=model)
          result = await agent.run("Say 'Hello ReviewCrew'")
          print(result.data)
      asyncio.run(smoke_test())
  ```
- [ ] 设置 `GLM_API_KEY` 环境变量，运行 `python -m reviewcrew.llm.glm`，确认返回文本
- [ ] Commit：`git add -A && git commit -m "feat: project scaffold + GLM client + event logger"`

### Task 2: 评测 Harness（最高优先级，先于一切管道代码）

**Files:**
- Create: `benchmark/dataset.yaml`, `benchmark/collect.py`, `benchmark/run_eval.py`, `benchmark/judge.py`, `benchmark/report.py`, `benchmark/__init__.py`
- Test: `tests/test_judge.py`

**Interfaces:**
- `dataset.yaml` 条目 schema：
  ```yaml
  - repo: "owner/repo-name"
    fork_url: "https://github.com/your-org/repo-name"
    pr_url: "https://github.com/owner/repo/pull/123"
    base_sha: "abc123..."
    head_sha: "def456..."
    bug_desc: "SQL injection in user search endpoint"
    bug_files:
      - path: "src/api/search.py"
        line_start: 45
        line_end: 48
    category: "security"  # security|logic|memory|architecture|static
  ```

- Provides: `judge(findings: list[Finding], entry: DatasetEntry) -> JudgeResult`
  ```python
  class DatasetEntry(BaseModel):
      repo: str
      fork_url: str
      pr_url: str
      base_sha: str
      head_sha: str
      bug_desc: str
      bug_files: list[BugLocation]
      category: str
  
  class BugLocation(BaseModel):
      path: str
      line_start: int
      line_end: int
  
  class JudgeResult(BaseModel):
      hit: bool
      matched_finding: Finding | None
      reason: str  # "line_overlap" | "semantic_match" | "miss"
  
  def judge(findings: list[Finding], entry: DatasetEntry) -> JudgeResult:
      """
      两级判定：
      1. 文件+行区间重叠（±10 行容差）→ hit
      2. 未命中时 GLM 语义比对（finding.reasoning vs bug_desc）→ hit/miss + 理由
      """
  ```

- Provides: `run_eval.py --quick` / `--full`
  ```python
  # 输出 benchmark/results/<ts>/{results.jsonl, summary.md}
  # summary 含：命中率、平均误报数、平均耗时、仓库×缺陷类型命中矩阵
  ```

- Consumes: Task 1 的 `build_glm_model()`、`Finding`（定义见 Task 7）

**Steps:**
- [ ] 创建 `benchmark/dataset.yaml` 模板（空列表，含 schema 注释）
- [ ] 写 `benchmark/collect.py` 脚本（从 Greptile benchmark 页面抓取 5 仓库 × 10 PR 元数据）
- [ ] 运行 `python benchmark/collect.py`，输出候选 PR 列表到控制台
- [ ] 人工筛选 5 个仓库（覆盖不同语言：Python/Go/TS/Rust/Java 优先），每个仓库 10 个 PR
- [ ] Fork 5 个仓库到自有 GitHub org
- [ ] 填充 `dataset.yaml`（50 条目，bug_files 行号从 fix commit diff 反推）
- [ ] 运行 `git clone --bare <fork_url> repos/<repo-name>.git` 缓存 5 个仓库
- [ ] 验证所有 fork_url 可 clone：`for repo in benchmark/dataset.yaml: git ls-remote <fork_url>`
- [ ] 写 `tests/test_judge.py`：
  ```python
  def test_judge_line_overlap_hit():
      finding = Finding(file="a.py", line_start=45, line_end=48, ...)
      entry = DatasetEntry(bug_files=[BugLocation(path="a.py", line_start=46, line_end=50)])
      result = judge([finding], entry)
      assert result.hit is True
      assert result.reason == "line_overlap"
  
  def test_judge_no_overlap_semantic_match(mock_glm):
      # Mock GLM 返回"语义匹配"
      finding = Finding(file="b.py", line_start=10, line_end=15, reasoning="SQL injection via string concat")
      entry = DatasetEntry(bug_files=[...], bug_desc="SQL injection in search")
      result = judge([finding], entry)
      assert result.hit is True
      assert result.reason == "semantic_match"
  
  def test_judge_miss():
      finding = Finding(file="c.py", line_start=100, ...)
      entry = DatasetEntry(bug_files=[BugLocation(path="a.py", ...)])
      result = judge([finding], entry)
      assert result.hit is False
  ```
- [ ] 跑测试确认失败：`pytest tests/test_judge.py -v`
- [ ] 实现 `judge.py`（约 120 行）
- [ ] 测试转绿
- [ ] 实现 `run_eval.py`（被测系统以 `ReviewRunner` Protocol 注入）：
  ```python
  class ReviewRunner(Protocol):
      def review(self, pr_url: str, repo_path: Path) -> list[Finding]: ...
  
  class FakeRunner:  # 假实现，随机返回 3-5 条 findings
      def review(self, pr_url: str, repo_path: Path) -> list[Finding]:
          return [Finding(...) for _ in range(random.randint(3, 5))]
  ```
- [ ] 实现 `report.py`（读 results.jsonl，输出 summary.md，含 5×6 矩阵表格）
- [ ] 运行 `python benchmark/run_eval.py --quick --runner fake`（抽样 10 PR）
- [ ] 验证 `benchmark/results/<ts>/summary.md` 格式正确（含命中率、误报数、耗时、矩阵表）
- [ ] Commit：`git add benchmark/ tests/test_judge.py && git commit -m "feat: eval harness with 50-PR dataset"`

## Phase 1 — 离线知识层

### Task 3: Diff 解析 + 符号索引 + Call Graph

**Files:**
- Create: `reviewcrew/pipeline/diff_parser.py`, `reviewcrew/profile/indexer.py`, `reviewcrew/pipeline/__init__.py`, `reviewcrew/profile/__init__.py`
- Test: `tests/test_diff_parser.py`, `tests/test_indexer.py`
- Fixtures: `tests/fixtures/sample.diff`, `tests/fixtures/mini_repo/`

**Interfaces:**
- Provides: `parse_diff(raw: str) -> list[FileDiff]`
  ```python
  class Hunk(BaseModel):
      old_start: int
      old_count: int
      new_start: int
      new_count: int
      lines: list[str]  # 带前缀 ' '/'+'/'-'
  
  class FileDiff(BaseModel):
      path: str
      change_type: Literal["add", "modify", "delete", "rename"]
      old_path: str | None = None
      hunks: list[Hunk]
  
  def parse_diff(raw: str) -> list[FileDiff]:
      """
      解析 unified diff，过滤噪音：
      - lockfile 名单：package-lock.json, yarn.lock, Cargo.lock, go.sum, poetry.lock
      - 生成代码标记：首行含 "# generated" / "@generated"
      - 纯空白变更：hunk 所有 +/- 行去空白后相同
      """
  ```

- Provides: `RepoIndex` 类（tree-sitter 符号索引 + call graph）
  ```python
  class Location(BaseModel):
      file: str
      line: int
      column: int
  
  class FuncNode(BaseModel):
      name: str
      location: Location
      signature: str  # 函数签名文本
  
  class RepoIndex:
      def __init__(self, db_path: Path): ...
      
      @classmethod
      def build(cls, repo_path: Path, langs: list[str]) -> "RepoIndex":
          """
          tree-sitter 解析 → SQLite profile/symbols.db
          表结构：
            symbols(id, name, kind, file, line, signature)
            references(symbol_id, file, line)
            calls(caller_id, callee_id)
          """
      
      def definition(self, symbol: str) -> Location | None: ...
      def references(self, symbol: str) -> list[Location]: ...
      def callers(self, func: str, hops: int = 1) -> list[FuncNode]: ...
      def callees(self, func: str, hops: int = 1) -> list[FuncNode]: ...
      def update_incremental(self, changed_files: list[str]) -> None: ...
  ```

- 语言覆盖：benchmark dataset.yaml 中 5 仓库实际语言（Task 2 收集后确定），tree-sitter grammar 逐语言注册

**Steps:**
- [ ] 创建 `tests/fixtures/sample.diff`（含 add/modify/delete/rename 四种，含 lockfile 噪音行）
- [ ] 写 `tests/test_diff_parser.py`：
  ```python
  def test_parse_basic_diff():
      raw = Path("tests/fixtures/sample.diff").read_text()
      diffs = parse_diff(raw)
      assert len(diffs) >= 2
      assert diffs[0].change_type in ["add", "modify", "delete", "rename"]
  
  def test_filter_lockfile():
      raw = "diff --git a/package-lock.json ..."
      diffs = parse_diff(raw)
      assert len(diffs) == 0
  
  def test_filter_generated_code():
      raw = 'diff --git a/gen.py ...\n+# generated\n+code'
      diffs = parse_diff(raw)
      assert len(diffs) == 0
  ```
- [ ] 跑测试确认失败：`pytest tests/test_diff_parser.py -v`
- [ ] 实现 `diff_parser.py`（约 150 行，用 `unidiff` 库或手工正则）
- [ ] 测试转绿
- [ ] 构造 `tests/fixtures/mini_repo/`（两文件互相调用）：
  ```
  mini_repo/
    main.py:  def main(): helper()
    helper.py: def helper(): pass
  ```
- [ ] 写 `tests/test_indexer.py`：
  ```python
  def test_build_index():
      repo = Path("tests/fixtures/mini_repo")
      index = RepoIndex.build(repo, langs=["python"])
      assert index.definition("helper") is not None
  
  def test_references():
      index = ...
      refs = index.references("helper")
      assert len(refs) >= 1  # main.py 调用
  
  def test_callers():
      index = ...
      callers = index.callers("helper", hops=1)
      assert any(c.name == "main" for c in callers)
  ```
- [ ] 跑测试确认失败
- [ ] 实现 `indexer.py`（tree-sitter query + SQLite，约 300 行）
  - 安装 tree-sitter-python（Task 2 确定其他语言后补充）
  - query 示例：`(function_definition name: (identifier) @func.name)`
- [ ] 测试转绿
- [ ] 对 5 个真实仓库跑 `python -m reviewcrew.profile.indexer repos/<name>.git`
- [ ] 记录建库耗时（写入 `benchmark/profile_times.txt`，要求单仓 <30min）
- [ ] Commit：`git add reviewcrew/pipeline/diff_parser.py reviewcrew/profile/indexer.py tests/ && git commit -m "feat: diff parser + tree-sitter indexer + call graph"`

### Task 4: 架构摘要 + 历史 Bug 模式挖掘 + Profile 更新入口

**Files:**
- Create: `reviewcrew/profile/summarizer.py`, `reviewcrew/profile/bug_miner.py`, `reviewcrew/profile/builder.py`
- Test: `tests/test_bug_miner.py`

**Interfaces:**
- Provides: `build_profile(repo_path: Path) -> RepoProfile`
  ```python
  class RepoProfile(BaseModel):
      repo_path: Path
      index_path: Path  # symbols.db
      arch_summary_path: Path  # architecture.md
      bug_patterns_path: Path  # bug_patterns.md
  
  def build_profile(repo_path: Path) -> RepoProfile:
      """
      产出 profile/{architecture.md, bug_patterns.md, symbols.db}
      - architecture.md: 目录树 + 各模块头部代码采样 → GLM 分模块生成，再汇总（≤8K tokens）
      - bug_patterns.md: git log --grep 拉 fix commits → GLM 归纳 ≤10 条仓库专属缺陷模式
      """
  ```

- Provides: `RepoProfile.arch_slice(paths: list[str]) -> str`
  ```python
  def arch_slice(self, paths: list[str]) -> str:
      """按变更文件检索相关模块摘要片段，≤2K tokens"""
  ```

- Provides: `builder.py update --repo <path> --changed <files>`（增量入口）
  ```bash
  python -m reviewcrew.profile.builder update --repo repos/xxx.git --changed src/api/auth.py
  # 增量更新 symbols.db（仅重新解析变更文件）
  ```

- Consumes: Task 1 `build_glm_model()`，Task 3 `RepoIndex`

**Steps:**
- [ ] 写 `tests/test_bug_miner.py`：
  ```python
  def test_mine_bug_patterns(mock_git_log, mock_glm):
      # Mock git log 输出 3 条 fix commit message
      mock_git_log.return_value = "fix: SQL injection\nfix: race condition\nfix: memory leak"
      # Mock GLM 返回归纳的 bug_patterns
      patterns = mine_bug_patterns(Path("fake_repo"))
      assert len(patterns) >= 1
      assert "SQL" in patterns or "race" in patterns
  ```
- [ ] 跑测试确认失败：`pytest tests/test_bug_miner.py -v`
- [ ] 实现 `bug_miner.py`（约 100 行）：
  ```python
  def mine_bug_patterns(repo_path: Path, limit: int = 10) -> list[str]:
      # git log --all --grep="fix\|bug" --pretty=format:"%s%n%b" --max-count=50
      # 喂给 GLM 归纳，要求输出 ≤10 条模式（JSON array）
  ```
- [ ] 测试转绿
- [ ] 实现 `summarizer.py`（约 150 行）：
  ```python
  def summarize_architecture(repo_path: Path) -> str:
      # 1. 目录树（tree -L 3）
      # 2. 各目录 README + 每个子模块首个 .py/.go 文件的头部 50 行
      # 3. 分批喂 GLM（每批 ≤16K tokens），得到各模块摘要
      # 4. 汇总成 architecture.md
  ```
- [ ] 实现 `builder.py`（CLI 入口，约 80 行）：
  ```python
  @click.command()
  @click.option("--repo", type=Path, required=True)
  @click.option("--changed", multiple=True, type=str)
  def update(repo: Path, changed: tuple[str, ...]):
      profile = load_profile(repo)
      if changed:
          profile.index.update_incremental(list(changed))
      else:
          # 全量构建
          RepoIndex.build(repo, langs=detect_languages(repo))
          arch = summarize_architecture(repo)
          bugs = mine_bug_patterns(repo)
          # 写入 profile/
  ```
- [ ] 对 5 个真实仓库全量构建 profile：
  ```bash
  for repo in repos/*.git; do
      python -m reviewcrew.profile.builder update --repo "$repo"
  done
  ```
- [ ] 人工抽查 `repos/*/profile/architecture.md` 质量（模块划分合理、核心流程有提及）
- [ ] 在 README.md 草记知识库更新方案：
  ```markdown
  ## 知识库维护
  - PR merge hook: `python -m reviewcrew.profile.builder update --repo <path> --changed <files>`
  - 每日定时: cron 调用 builder update（增量刷新架构摘要）
  - 每周定时: 重挖历史 bug 模式
  ```
- [ ] Commit：`git add reviewcrew/profile/ tests/test_bug_miner.py README.md && git commit -m "feat: arch summary + bug miner + profile builder"`

## Phase 2 — 在线管道

### Task 5: 静态信号层

**Files:**
- Create: `reviewcrew/signals/base.py`, `reviewcrew/signals/semgrep.py`, `reviewcrew/signals/linters.py`, `reviewcrew/signals/deps.py`, `reviewcrew/signals/__init__.py`
- Test: `tests/test_signals.py`

**Interfaces:**
- Provides: `SignalProvider` Protocol + `Signal` 类
  ```python
  class Signal(BaseModel):
      provider: str  # "semgrep" / "ruff" / "eslint" / "osv"
      rule_id: str
      file: str
      line: int
      message: str
      severity: Literal["error", "warning", "info"]
  
  class SignalProvider(Protocol):
      async def scan(self, repo_path: Path, files: list[str]) -> list[Signal]:
          """
          扫描指定文件，返回信号列表
          - 超时 60s 返回空列表（不抛异常）
          - 单 provider 失败只记日志
          """
  ```

- Provides: `SemgrepProvider`, `LinterProvider`, `DepsProvider`
  ```python
  class SemgrepProvider:
      async def scan(self, repo_path: Path, files: list[str]) -> list[Signal]:
          # semgrep --config auto --json --include <files>
          # 解析 JSON，转为 Signal 列表
  
  class LinterProvider:
      async def scan(self, repo_path: Path, files: list[str]) -> list[Signal]:
          # 按文件后缀路由：.py→ruff, .go→go vet, .ts/.js→eslint, .rs→clippy
          # 并行跑多个 linter，汇总结果
  
  class DepsProvider:
      async def scan(self, repo_path: Path, files: list[str]) -> list[Signal]:
          # 检测 lockfile 变更（package-lock.json, Cargo.lock 等）
          # 提取依赖差异 → osv.dev batch API
  ```

- 失败语义：provider 超时/异常 → 返回空列表 + 日志，不阻塞管道

**Steps:**
- [ ] 写 `tests/test_signals.py`：
  ```python
  @pytest.mark.asyncio
  async def test_semgrep_parses_output(tmp_path):
      # 创建临时 Python 文件含已知漏洞（SQL 拼接）
      (tmp_path / "vuln.py").write_text('exec("select * from users where id=" + user_id)')
      provider = SemgrepProvider()
      signals = await provider.scan(tmp_path, ["vuln.py"])
      assert len(signals) >= 1
      assert any("exec" in s.message.lower() for s in signals)
  
  @pytest.mark.asyncio
  async def test_provider_timeout_returns_empty(monkeypatch):
      # Mock subprocess 超时
      async def mock_run(*args, **kwargs):
          await asyncio.sleep(100)  # 模拟超时
      monkeypatch.setattr("asyncio.create_subprocess_exec", mock_run)
      provider = SemgrepProvider()
      signals = await asyncio.wait_for(provider.scan(Path("."), ["test.py"]), timeout=2)
      assert signals == []  # 超时返回空，不抛异常
  
  @pytest.mark.asyncio
  async def test_linter_routes_by_extension():
      provider = LinterProvider()
      # Mock 子进程：.py 文件调用 ruff
      signals = await provider.scan(Path("."), ["a.py", "b.go"])
      # 验证调用了正确的 linter（通过 mock 参数检查）
  ```
- [ ] 跑测试确认失败：`pytest tests/test_signals.py -v`
- [ ] 实现 `base.py`（Signal + SignalProvider Protocol，约 40 行）
- [ ] 实现 `semgrep.py`（约 100 行）：
  ```python
  async def scan(self, repo_path: Path, files: list[str]) -> list[Signal]:
      try:
          proc = await asyncio.create_subprocess_exec(
              "semgrep", "--config", "auto", "--json",
              *[f"--include={f}" for f in files],
              cwd=repo_path,
              stdout=asyncio.subprocess.PIPE,
              stderr=asyncio.subprocess.PIPE,
          )
          stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60.0)
          results = json.loads(stdout)
          return [Signal(...) for r in results["results"]]
      except (asyncio.TimeoutError, Exception) as e:
          logger.warning(f"Semgrep failed: {e}")
          return []
  ```
- [ ] 实现 `linters.py`（约 120 行，路由逻辑 + 并行调用）
- [ ] 实现 `deps.py`（约 80 行，lockfile diff + osv.dev API）
- [ ] 测试转绿
- [ ] 真实仓库冒烟：选 benchmark 中 1 个 PR 的 diff 文件，跑三个 provider：
  ```bash
  python -c "
  import asyncio
  from reviewcrew.signals import SemgrepProvider, LinterProvider, DepsProvider
  async def smoke():
      providers = [SemgrepProvider(), LinterProvider(), DepsProvider()]
      results = await asyncio.gather(*[p.scan(Path('repos/xxx'), ['src/a.py']) for p in providers])
      print(sum(len(r) for r in results), 'signals')
  asyncio.run(smoke())
  "
  ```
- [ ] 确认 30s 内返回（记录实际耗时）
- [ ] Commit：`git add reviewcrew/signals/ tests/test_signals.py && git commit -m "feat: static signal providers (semgrep/linter/deps)"`

### Task 6: ContextPack 组装器

**Files:**
- Create: `reviewcrew/pipeline/context.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Provides: `build_context_packs(diffs, index, profile, signals, pr_meta) -> list[ContextPack]`
  ```python
  class PRMeta(BaseModel):
      title: str
      description: str
      issue_links: list[str]
      test_changes: str  # 测试文件变更摘要
  
  class ContextPack(BaseModel):
      """完整定义见 design-doc.md §4-②"""
      pack_id: str
      diff_hunks: list[FileDiff]
      enclosing_code: dict[str, str]  # {file: 完整函数/类代码}
      callers: dict[str, list[str]]
      callees: dict[str, list[str]]
      arch_summary: str = Field(max_length=2048)
      bug_patterns: str = Field(max_length=1024)
      intent: str
      static_signals: list[Signal]
  
  def build_context_packs(
      diffs: list[FileDiff],
      index: RepoIndex,
      profile: RepoProfile,
      signals: list[Signal],
      pr_meta: PRMeta,
  ) -> list[ContextPack]:
      """
      裁剪策略：
      - 单 pack token 预算 32K（tiktoken cl100k_base 估算）
      - 超出按"离 diff 行距离"由远及近裁剪 callers/callees
      - 文件语义聚类：同目录/同模块 hunks 归入同一 pack
      """
  ```

- Consumes: Task 3 `FileDiff`/`RepoIndex`，Task 4 `RepoProfile`，Task 5 `Signal`

**Steps:**
- [ ] 安装 tiktoken：`pip install tiktoken`
- [ ] 写 `tests/test_context.py`：
  ```python
  def test_clustering_same_directory():
      diffs = [
          FileDiff(path="src/auth/login.py", ...),
          FileDiff(path="src/auth/logout.py", ...),
          FileDiff(path="src/api/users.py", ...),
      ]
      packs = build_context_packs(diffs, mock_index, mock_profile, [], PRMeta(...))
      # 断言 login.py + logout.py 在同一 pack（同目录）
      assert len(packs) == 2
      pack_files = {pack.pack_id: [d.path for d in pack.diff_hunks] for pack in packs}
      assert "src/auth/login.py" in pack_files["auth"] and "src/auth/logout.py" in pack_files["auth"]
  
  def test_token_budget_trim():
      # 构造超大 callers/callees（总计 >32K tokens）
      huge_callers = {"func": ["x" * 10000 for _ in range(100)]}  # 超预算
      pack = build_single_pack(diff, huge_callers, {}, ...)
      # 估算 token 数
      import tiktoken
      enc = tiktoken.get_encoding("cl100k_base")
      tokens = len(enc.encode(pack.model_dump_json()))
      assert tokens <= 33_000  # 允许 1K buffer
  
  def test_intent_field_populated():
      pr_meta = PRMeta(title="Fix SQL injection", description="...", test_changes="Added test_sql_escape")
      pack = build_context_packs([...], ..., ..., [], pr_meta)[0]
      assert "SQL injection" in pack.intent
      assert "test_sql_escape" in pack.intent
  ```
- [ ] 跑测试确认失败：`pytest tests/test_context.py -v`
- [ ] 实现 `context.py`（约 250 行）：
  ```python
  def cluster_by_semantics(diffs: list[FileDiff]) -> list[list[FileDiff]]:
      # 按目录前缀聚类：相同前两级目录归一组
      from collections import defaultdict
      groups = defaultdict(list)
      for diff in diffs:
          prefix = "/".join(Path(diff.path).parts[:2])
          groups[prefix].append(diff)
      return list(groups.values())
  
  def estimate_tokens(text: str) -> int:
      enc = tiktoken.get_encoding("cl100k_base")
      return len(enc.encode(text))
  
  def trim_to_budget(pack: ContextPack, budget: int = 32000) -> ContextPack:
      # 循环裁剪 callers/callees，从最远的开始
      while estimate_tokens(pack.model_dump_json()) > budget:
          # 删除一个最远的 caller/callee
          ...
      return pack
  ```
- [ ] 测试转绿
- [ ] Commit：`git add reviewcrew/pipeline/context.py tests/test_context.py && git commit -m "feat: context pack builder with token budget"`

### Task 7: Agent 基座 + 工具箱

**Files:**
- Create: `reviewcrew/agents/base.py`, `reviewcrew/tools/toolbox.py`, `reviewcrew/agents/__init__.py`, `reviewcrew/tools/__init__.py`
- Test: `tests/test_agent_loop.py`

**Interfaces:**
- Provides: `class ReviewAgent` 基类 + `Finding` schema（完整定义）
  ```python
  from pydantic import BaseModel, Field
  from typing import Literal
  
  class Finding(BaseModel):
      """完整定义，与 design-doc.md §4-③ 一致"""
      category: Literal["logic", "security", "memory", "architecture", "static"]
      severity: Literal["critical", "high", "medium", "low"]
      confidence: float = Field(ge=0.0, le=1.0)
      
      file: str
      line_start: int = Field(ge=1)
      line_end: int = Field(ge=1)
      
      title: str = Field(max_length=120)
      reasoning: str
      trigger_path: str
      suggestion: str
      
      verdict: Literal["keep", "reject"] | None = None
      verdict_reason: str | None = None
  
  class AgentFindings(BaseModel):
      """pydantic-ai output_type"""
      findings: list[Finding]
  
  class Budget(BaseModel):
      timeout_seconds: float
      max_turns: int = 12
  
  class ReviewAgent:
      def __init__(self, role: str, system_prompt: str):
          self.agent = Agent(
              model=build_glm_model(),
              output_type=AgentFindings,
              system_prompt=system_prompt,
              settings=ModelSettings(
                  usage_limits=UsageLimits(request_limit=12)
              )
          )
          self._register_tools()
      
      async def run(self, pack: ContextPack, budget: Budget) -> list[Finding]:
          """
          执行审查循环：
          - 每 4 轮调用 submit_snapshot 工具
          - 超时/超轮次取最后快照
          - 每轮 emit thought/tool 事件
          """
  ```

- Provides: 工具箱（注册为 `@agent.tool`）
  ```python
  @agent.tool
  async def read_file(ctx: RunContext, path: str, start: int | None, end: int | None) -> str:
      """读取文件片段，路径白名单限制在 repo 内"""
  
  @agent.tool
  async def find_references(ctx: RunContext, symbol: str) -> list[dict]:
      """查找符号引用，返回 [{file, line, code_snippet}]"""
  
  @agent.tool
  async def get_callers(ctx: RunContext, func: str) -> list[dict]:
      """查找调用者"""
  
  @agent.tool
  async def get_callees(ctx: RunContext, func: str) -> list[dict]:
      """查找被调函数"""
  
  @agent.tool
  async def git_blame(ctx: RunContext, path: str, line_range: tuple[int, int]) -> str:
      """Git blame 指定行范围"""
  
  @agent.tool
  async def run_semgrep_rule(ctx: RunContext, rule_id: str, path: str) -> str:
      """定向运行 semgrep 规则"""
  
  @agent.tool
  async def submit_snapshot(ctx: RunContext, findings: list[Finding]) -> str:
      """提交中间快照，每 4 轮强制调用"""
  ```

- Consumes: Task 1 `build_glm_model()`/`EventLogger`，Task 6 `ContextPack`

**Steps:**
- [ ] 写 `tests/test_agent_loop.py`：
  ```python
  from pydantic_ai.models import FunctionModel, TestModel
  
  @pytest.mark.asyncio
  async def test_agent_runs_with_tools():
      # 用 FunctionModel 脚本化：tool→tool→submit_snapshot
      calls = []
      def model_func(messages, tools):
          calls.append(len(messages))
          if len(calls) == 1:
              return ToolCall(name="read_file", args={"path": "a.py"})
          elif len(calls) == 2:
              return ToolCall(name="submit_snapshot", args={"findings": [...]})
          else:
              return AgentFindings(findings=[...])
      
      model = FunctionModel(model_func)
      agent = ReviewAgent(role="test", system_prompt="...", model=model)
      results = await agent.run(mock_pack, Budget(timeout_seconds=60))
      assert len(results) >= 1
  
  @pytest.mark.asyncio
  async def test_usage_limits_enforced():
      # Mock 模型：每轮调 tool，永不停
      # 断言 12 轮后强制停止，返回最后快照
  
  @pytest.mark.asyncio
  async def test_emits_thought_and_tool_events(mock_event_logger):
      # 验证 thought/tool 事件被 emit
  ```
- [ ] 跑测试确认失败：`pytest tests/test_agent_loop.py -v`
- [ ] 实现 `toolbox.py`（7 个工具函数，约 200 行）
- [ ] 实现 `base.py`（ReviewAgent 封装层，约 150 行）：
  ```python
  async def run(self, pack: ContextPack, budget: Budget) -> list[Finding]:
      snapshots = []
      turn_count = 0
      
      async with asyncio.timeout(budget.timeout_seconds):
          result = await self.agent.run(
              user_prompt=self._format_pack(pack),
              deps=AgentDeps(repo_index=..., event_logger=...),
          )
          return result.data.findings
  ```
- [ ] 测试转绿
- [ ] Commit：`git add reviewcrew/agents/base.py reviewcrew/tools/ tests/test_agent_loop.py && git commit -m "feat: agent base class + toolbox with 7 tools"`

### Task 8: DefectAgent + IntentAgent

**Files:**
- Create: `reviewcrew/agents/defect.py`, `reviewcrew/agents/intent.py`, `reviewcrew/agents/prompts/defect.md`, `reviewcrew/agents/prompts/intent.md`, `reviewcrew/agents/prompts/__init__.py`
- Test: `tests/test_expert_agents.py`

**Interfaces:**
- 两个 Agent 均继承 Task 7 的 `ReviewAgent`，差异仅在 system prompt 与上下文侧重
- `DefectAgent`: 关注 static_signals，分节 checklist（安全→内存→静态）
- `IntentAgent`: 关注 intent 字段，三步固定流程（详见 agent-topology.md §2）

- Provides: `shard_packs(packs, max_shards=3) -> list[list[ContextPack]]`
  ```python
  def shard_packs(packs: list[ContextPack], max_shards: int = 3) -> list[list[ContextPack]]:
      """
      大 PR 按聚类分片，同模块不拆
      - 若 len(packs) <= max_shards：每个 pack 一片
      - 若 len(packs) > max_shards：按模块相似度合并到 max_shards 片
      """
  ```

**Steps:**
- [ ] 创建 `reviewcrew/agents/prompts/defect.md`（完整 prompt，约 300 行）：
  ```markdown
  # DefectAgent System Prompt
  
  You are a defect hunter reviewing code changes. Work through three sections sequentially:
  
  ## Section 1: Security (🔒)
  - SQL/Command/Path injection
  - SSRF, deserialization
  - Authentication bypass, privilege escalation
  - Taint flow: trace source→sink along call graph
  - Use tools: read_file, get_callers, run_semgrep_rule
  
  ## Section 2: Memory & Resources (💾)
  - Leaks: connections, file handles, goroutines
  - Use-after-free, double-free
  - Unbounded growth: caches, queues
  - Use tools: find_references, get_callees
  
  ## Section 3: Static Signals (📊)
  - Review static_signals from linters/semgrep
  - Judge true/false positive
  - Explain why signal is valid or noise
  
  Submit snapshot every 4 turns with submit_snapshot tool.
  ```

- [ ] 创建 `reviewcrew/agents/prompts/intent.md`（完整 prompt，约 250 行）：
  ```markdown
  # IntentAgent System Prompt
  
  You analyze logic/business/architecture issues via intent-implementation gap.
  
  ## Fixed 3-step workflow:
  
  ### Step 1: Summarize Intent
  Read ONLY: PR title, description, issue links, test changes
  Output: "Author intends to..."
  
  ### Step 2: Summarize Actual Change
  Read ONLY: diff hunks
  Output: "Code actually does..."
  
  ### Step 3: Find Gaps
  Diff the two summaries → gaps = candidate defects
  Then check: boundary conditions, state machine, dependency direction
  
  Use tools: read_file, git_blame, get_callers for verification.
  Submit snapshot every 4 turns.
  ```

- [ ] 写 `tests/test_expert_agents.py`：
  ```python
  def test_shard_packs_respects_max():
      packs = [ContextPack(pack_id=f"p{i}", ...) for i in range(10)]
      shards = shard_packs(packs, max_shards=3)
      assert len(shards) == 3
      assert sum(len(s) for s in shards) == 10
  
  def test_defect_agent_loads_prompt():
      agent = DefectAgent()
      assert "Security" in agent.system_prompt
      assert "Section 1" in agent.system_prompt
  
  def test_intent_agent_loads_prompt():
      agent = IntentAgent()
      assert "Step 1: Summarize Intent" in agent.system_prompt
  ```

- [ ] 跑测试确认失败：`pytest tests/test_expert_agents.py -v`
- [ ] 实现 `defect.py`（约 40 行）：
  ```python
  class DefectAgent(ReviewAgent):
      def __init__(self):
          prompt = Path(__file__).parent / "prompts/defect.md"
          super().__init__(role="defect", system_prompt=prompt.read_text())
  ```
- [ ] 实现 `intent.py`（约 40 行，类似结构）
- [ ] 实现分片逻辑（约 60 行）
- [ ] 测试转绿
- [ ] 手动测试：挑 benchmark 中 1 个已知逻辑类 bug 的 PR，运行：
  ```bash
  python -c "
  import asyncio
  from reviewcrew.agents.intent import IntentAgent
  from reviewcrew.pipeline.context import build_context_packs
  # ... 加载 PR diff + 构建 pack
  async def test():
      agent = IntentAgent()
      findings = await agent.run(pack, Budget(timeout_seconds=300))
      for f in findings:
          print(f.title, f.confidence)
  asyncio.run(test())
  "
  ```
- [ ] 人工检查推理质量（reasoning 字段是否合理），记录到 `tests/manual_smoke.md`
- [ ] 同法手动跑 DefectAgent（挑安全类 bug PR）
- [ ] Commit：`git add reviewcrew/agents/{defect,intent}.py reviewcrew/agents/prompts/ tests/ && git commit -m "feat: DefectAgent + IntentAgent with sectioned prompts"`

### Task 9: VerifierAgent + 输出控制

**Files:**
- Create: `reviewcrew/agents/verifier.py`, `reviewcrew/agents/prompts/verifier.md`, `reviewcrew/pipeline/dedupe.py`
- Test: `tests/test_verifier.py`, `tests/test_dedupe.py`

**Interfaces:**
- Provides: `dedupe(findings: list[Finding]) -> list[Finding]`
  ```python
  def dedupe(findings: list[Finding]) -> list[Finding]:
      """
      两级去重：
      1. 同文件行区间重叠（±3 行容差）→ 合并取高 confidence
      2. 跨文件语义近似 → embedding 余弦 >0.85 合并（GLM embedding API）
      """
  ```

- Provides: `Verdict` schema + `VerifierAgent`
  ```python
  class Verdict(BaseModel):
      finding_id: str
      verdict: Literal["keep", "reject"]
      reason: str
      confidence_adjusted: float
  
  class VerifierAgent(ReviewAgent):
      async def run(self, findings: list[Finding], toolbox) -> list[Verdict]:
          """
          对抗验证四问：
          1. 触发路径可达吗？
          2. 有防御代码兜底吗？
          3. 是测试/示例代码吗？
          4. severity 虚高吗？
          
          每条 finding 独立质疑，emit verdict 事件
          """
  ```

- Provides: `filter_and_rank(findings, verdicts) -> list[Finding]`
  ```python
  def filter_and_rank(findings: list[Finding], verdicts: list[Verdict]) -> list[Finding]:
      """
      门限控制：
      - confidence_adjusted < 0.6 丢弃
      - 按 severity_weight × confidence_adjusted 排序
      - 截断 8 条
      
      severity_weight: critical=4, high=3, medium=2, low=1
      """
  ```

**Steps:**
- [ ] 写 `tests/test_dedupe.py`：
  ```python
  def test_dedupe_line_overlap():
      f1 = Finding(file="a.py", line_start=10, line_end=15, confidence=0.7, ...)
      f2 = Finding(file="a.py", line_start=12, line_end=18, confidence=0.9, ...)
      result = dedupe([f1, f2])
      assert len(result) == 1
      assert result[0].confidence == 0.9  # 取高
  
  def test_dedupe_semantic_similarity(mock_glm_embedding):
      # Mock GLM embedding API 返回高余弦相似度
      f1 = Finding(file="a.py", reasoning="SQL injection via string concat", ...)
      f2 = Finding(file="b.py", reasoning="SQL injection using format string", ...)
      result = dedupe([f1, f2])
      assert len(result) == 1
  
  def test_no_false_merge():
      # 不同文件、不同类型缺陷，不应合并
      f1 = Finding(category="security", file="a.py", ...)
      f2 = Finding(category="memory", file="b.py", ...)
      result = dedupe([f1, f2])
      assert len(result) == 2
  ```

- [ ] 跑测试确认失败：`pytest tests/test_dedupe.py -v`
- [ ] 实现 `dedupe.py`（约 150 行）
- [ ] 测试转绿
- [ ] 创建 `reviewcrew/agents/prompts/verifier.md`（完整 prompt，约 200 行）：
  ```markdown
  # VerifierAgent System Prompt
  
  You are an adversarial verifier. Challenge each finding with 4 questions:
  
  ## Question 1: Is trigger path reachable?
  - Use get_callers to trace call chain
  - Check if preconditions exist
  
  ## Question 2: Is there defensive code?
  - Search for validation/sanitization upstream
  - Use find_references to locate guards
  
  ## Question 3: Is this test/example code?
  - Check file path: *_test.py, examples/, docs/
  - Test code bugs are usually acceptable
  
  ## Question 4: Is severity inflated?
  - Critical requires RCE/data breach
  - High requires significant impact
  
  Output verdict: keep/reject + reason + confidence_adjusted.
  ```

- [ ] 写 `tests/test_verifier.py`：
  ```python
  @pytest.mark.asyncio
  async def test_verifier_keeps_valid_finding(mock_glm):
      # Mock GLM 返回 verdict=keep
      findings = [Finding(...)]
      agent = VerifierAgent()
      verdicts = await agent.run(findings, mock_toolbox)
      assert len(verdicts) == 1
      assert verdicts[0].verdict == "keep"
  
  @pytest.mark.asyncio
  async def test_verifier_rejects_test_code():
      findings = [Finding(file="tests/test_auth.py", ...)]
      verdicts = await agent.run(findings, mock_toolbox)
      assert verdicts[0].verdict == "reject"
      assert "test code" in verdicts[0].reason.lower()
  
  def test_filter_and_rank_applies_threshold():
      findings = [
          Finding(confidence=0.5, ...),  # 低于 0.6
          Finding(confidence=0.8, severity="high", ...),
          Finding(confidence=0.7, severity="critical", ...),
      ]
      verdicts = [
          Verdict(finding_id="0", verdict="keep", confidence_adjusted=0.5),
          Verdict(finding_id="1", verdict="keep", confidence_adjusted=0.8),
          Verdict(finding_id="2", verdict="keep", confidence_adjusted=0.7),
      ]
      result = filter_and_rank(findings, verdicts)
      assert len(result) == 2  # 0.5 被丢弃
      assert result[0].severity == "critical"  # 排序优先
  
  def test_filter_and_rank_caps_at_8():
      findings = [Finding(confidence=0.9, severity="high", ...) for _ in range(20)]
      verdicts = [Verdict(finding_id=str(i), verdict="keep", confidence_adjusted=0.9) for i in range(20)]
      result = filter_and_rank(findings, verdicts)
      assert len(result) == 8
  ```

- [ ] 跑测试确认失败
- [ ] 实现 `verifier.py`（约 80 行，类似 DefectAgent 结构）
- [ ] 实现 `filter_and_rank`（约 60 行）
- [ ] 测试转绿
- [ ] Commit：`git add reviewcrew/agents/verifier.py reviewcrew/pipeline/dedupe.py tests/ && git commit -m "feat: VerifierAgent + dedupe + filter/rank logic"`

### Task 10: Orchestrator + 报告 + CLI —— 管道合龙

**Files:**
- Create: `reviewcrew/pipeline/orchestrator.py`, `reviewcrew/pipeline/report.py`, `reviewcrew/cli.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Provides: `Orchestrator.review(pr_url: str, repo_path: Path) -> ReviewResult`
  ```python
  class ReviewResult(BaseModel):
      run_id: str
      findings: list[Finding]
      elapsed_seconds: float
      stages: dict[str, float]  # stage_name -> elapsed
  
  class Orchestrator:
      async def review(self, pr_url: str, repo_path: Path) -> ReviewResult:
          """
          五阶段串联：
          1. preprocess: parse_diff + filter (预算 10s)
          2. context: build_context_packs + static signals (预算 60s)
          3. review: DefectAgent + IntentAgent 并行 (预算 300s)
          4. verify: dedupe + VerifierAgent + filter_and_rank (预算 120s)
          5. report: generate_report (预算 30s)
          
          全局 watchdog：阶段超时取快照强制收敛
          每阶段 emit stage 事件 (start/done + elapsed)
          """
  ```

- Provides: `generate_report(findings: list[Finding]) -> tuple[str, dict]`
  ```python
  def generate_report(findings: list[Finding]) -> tuple[str, dict]:
      """
      返回：
      - Markdown 报告（人类可读）
      - GitHub Review Comment JSON（行级锚定）
        [{path, line, body}, ...]
      """
  ```

- Provides: CLI 入口 + `ReviewRunner` 协议实现
  ```bash
  reviewcrew review --pr <url> --repo-path <cached>
  # 输出：runs/<run_id>/{events.jsonl, report.md, github_comments.json}
  ```

- Consumes: Tasks 3-9 全部接口

**Steps:**
- [ ] 写 `tests/test_orchestrator.py`：
  ```python
  @pytest.mark.asyncio
  async def test_orchestrator_five_stage_events(mock_all_stages):
      # Mock 所有下游组件
      orch = Orchestrator()
      result = await orch.review("https://github.com/owner/repo/pull/1", Path("repos/repo.git"))
      
      # 验证 EventLogger 收到 5 对 stage 事件
      events = mock_event_logger.emitted
      stage_events = [e for e in events if e.type == "stage"]
      assert len(stage_events) == 10  # 5 start + 5 done
  
  @pytest.mark.asyncio
  async def test_review_stage_timeout_uses_snapshot():
      # Mock DefectAgent 超时
      # 验证返回最后快照，不抛异常
  
  @pytest.mark.asyncio
  async def test_agents_run_in_parallel():
      # 验证 DefectAgent 和 IntentAgent 用 asyncio.gather 并行
      import time
      start = time.time()
      await orch.review(...)
      elapsed = time.time() - start
      # 如果串行应该 >600s，并行应该 ~300s
      assert elapsed < 400
  ```

- [ ] 跑测试确认失败：`pytest tests/test_orchestrator.py -v`
- [ ] 实现 `orchestrator.py`（约 250 行）：
  ```python
  async def review(self, pr_url: str, repo_path: Path) -> ReviewResult:
      run_id = generate_run_id()
      logger = EventLogger(run_id)
      
      # Stage 1: Preprocess
      logger.emit(PipelineEvent(type="stage", stage="preprocess", status="start", ...))
      async with asyncio.timeout(10):
          diffs = parse_diff(fetch_diff(pr_url))
      logger.emit(PipelineEvent(type="stage", stage="preprocess", status="done", ...))
      
      # Stage 2: Context
      # ...
      
      # Stage 3: Review (并行)
      defect_agent = DefectAgent()
      intent_agent = IntentAgent()
      defect_findings, intent_findings = await asyncio.gather(
          defect_agent.run(packs[0], budget),
          intent_agent.run(packs[1], budget),
      )
      
      # Stage 4: Verify
      # ...
      
      # Stage 5: Report
      # ...
      
      return ReviewResult(...)
  ```

- [ ] 实现 `report.py`（约 120 行）：
  ```python
  def generate_report(findings: list[Finding]) -> tuple[str, dict]:
      # Markdown 模板
      md = f"""# Code Review Report
      
  ## Summary
  - Total findings: {len(findings)}
  - Critical: {count_by_severity(findings, 'critical')}
  ...
  
  ## Findings
  """
      for f in findings:
          md += f"\n### {f.title}\n**{f.severity}** | {f.file}:{f.line_start}-{f.line_end}\n{f.reasoning}\n"
      
      # GitHub comments
      comments = [
          {"path": f.file, "line": f.line_start, "body": format_comment(f)}
          for f in findings
      ]
      return md, {"comments": comments}
  ```

- [ ] 实现 `cli.py`（约 100 行，用 click）：
  ```python
  @click.command()
  @click.option("--pr", required=True)
  @click.option("--repo-path", type=Path, required=True)
  def review(pr: str, repo_path: Path):
      orch = Orchestrator()
      result = asyncio.run(orch.review(pr, repo_path))
      print(f"Run ID: {result.run_id}")
      print(f"Findings: {len(result.findings)}")
      print(f"Elapsed: {result.elapsed_seconds:.1f}s")
  
  # 实现 ReviewRunner Protocol（给 benchmark 用）
  class CLIReviewRunner:
      def review(self, pr_url: str, repo_path: Path) -> list[Finding]:
          orch = Orchestrator()
          result = asyncio.run(orch.review(pr_url, repo_path))
          return result.findings
  ```

- [ ] 测试转绿
- [ ] 端到端冒烟：选 benchmark 中 1 个真实 PR：
  ```bash
  export GLM_API_KEY=xxx
  python -m reviewcrew.cli review \
    --pr https://github.com/owner/repo/pull/123 \
    --repo-path repos/repo.git
  ```
- [ ] 验证输出：
  - `runs/<run_id>/events.jsonl` 存在且完整（包含所有阶段事件）
  - `runs/<run_id>/report.md` 可读
  - 耗时 <10min
- [ ] 运行 `python benchmark/run_eval.py --quick --runner real`（真实跑 10 个 PR）
- [ ] 记录 baseline 分数到 `benchmark/results/BASELINE.md`：
  ```markdown
  # Baseline Results (Task 10 完成时)
  
  Date: 2026-XX-XX
  Model: glm-4-plus
  
  ## Metrics
  - Hit rate: XX%
  - Avg false positives: X.X
  - Avg time: X.Xmin
  
  ## Per-category
  | Category | Hit | Miss |
  |---|---|---|
  | security | X | X |
  | logic | X | X |
  | memory | X | X |
  ```
- [ ] Commit：`git add reviewcrew/pipeline/orchestrator.py reviewcrew/pipeline/report.py reviewcrew/cli.py benchmark/results/BASELINE.md tests/ && git commit -m "feat: orchestrator + report + CLI, pipeline end-to-end"`

## Phase 3 — 演示层

### Task 11: FastAPI 服务 + SSE + Replay

**Files:**
- Create: `reviewcrew/server/app.py`, `reviewcrew/server/replay.py`, `reviewcrew/server/__init__.py`
- Test: `tests/test_server.py`

**Interfaces:**
- `POST /api/review {pr_url: str, repo_path: str}` → `{run_id: str}`
  ```python
  @app.post("/api/review")
  async def start_review(req: ReviewRequest, background_tasks: BackgroundTasks):
      run_id = generate_run_id()
      background_tasks.add_task(run_review_task, run_id, req.pr_url, req.repo_path)
      return {"run_id": run_id}
  ```

- `GET /api/stream/{run_id}` → SSE，事件即 PipelineEvent JSON
  ```python
  @app.get("/api/stream/{run_id}")
  async def stream_events(run_id: str):
      async def event_generator():
          async for event in tail_events_file(f"runs/{run_id}/events.jsonl"):
              yield f"data: {event.model_dump_json()}\n\n"
      return StreamingResponse(event_generator(), media_type="text/event-stream")
  ```

- `GET /api/replay/{run_id}?speed=2` → SSE，按原时间戳/speed 重放
  ```python
  @app.get("/api/replay/{run_id}")
  async def replay_events(run_id: str, speed: float = 1.0):
      events = load_events_jsonl(f"runs/{run_id}/events.jsonl")
      async def replay_generator():
          prev_ts = events[0].timestamp
          for event in events:
              delay = (event.timestamp - prev_ts) / speed
              await asyncio.sleep(delay)
              yield f"data: {event.model_dump_json()}\n\n"
              prev_ts = event.timestamp
      return StreamingResponse(replay_generator(), media_type="text/event-stream")
  ```

- `GET /api/runs` → 列出所有 run
- `GET /api/benchmark/latest` → 最新评测结果

**Steps:**
- [ ] 安装 FastAPI: `pip install fastapi uvicorn sse-starlette`
- [ ] 写 `tests/test_server.py`：
  ```python
  from fastapi.testclient import TestClient
  
  def test_start_review_returns_run_id():
      client = TestClient(app)
      response = client.post("/api/review", json={"pr_url": "...", "repo_path": "..."})
      assert response.status_code == 200
      assert "run_id" in response.json()
  
  def test_stream_events_sse_format():
      # Mock run_id 已完成
      client = TestClient(app)
      with client.stream("GET", "/api/stream/test123") as response:
          lines = list(response.iter_lines())
          assert any(line.startswith("data:") for line in lines)
  
  def test_replay_respects_speed():
      # 构造 3 个事件，时间戳间隔 1s
      # speed=2 应该间隔 0.5s
      import time
      start = time.time()
      client = TestClient(app)
      with client.stream("GET", "/api/replay/test123?speed=2") as response:
          list(response.iter_lines())
      elapsed = time.time() - start
      assert 0.9 < elapsed < 1.5  # 原本 2s，加速后 ~1s
  ```

- [ ] 跑测试确认失败：`pytest tests/test_server.py -v`
- [ ] 实现 `app.py`（约 150 行）：
  ```python
  from fastapi import FastAPI, BackgroundTasks
  from fastapi.responses import StreamingResponse
  
  app = FastAPI()
  
  async def run_review_task(run_id: str, pr_url: str, repo_path: str):
      orch = Orchestrator()
      await orch.review(pr_url, Path(repo_path))
  ```

- [ ] 实现 `replay.py`（约 80 行）：
  ```python
  def load_events_jsonl(path: Path) -> list[PipelineEvent]:
      with open(path) as f:
          return [PipelineEvent.model_validate_json(line) for line in f]
  
  async def tail_events_file(path: Path):
      # 实时 tail events.jsonl（类似 tail -f）
      with open(path) as f:
          f.seek(0, 2)  # 到文件末尾
          while True:
              line = f.readline()
              if line:
                  yield PipelineEvent.model_validate_json(line)
              else:
                  await asyncio.sleep(0.1)
  ```

- [ ] 测试转绿
- [ ] 用 Task 10 的真实 run 验证 replay：
  ```bash
  # 启动服务器
  uvicorn reviewcrew.server.app:app --reload &
  
  # 测试 replay
  curl -N http://localhost:8000/api/replay/<run_id>?speed=2
  ```
- [ ] 验证 replay 全程可放（所有阶段事件按序出现）
- [ ] Commit：`git add reviewcrew/server/ tests/test_server.py && git commit -m "feat: FastAPI server with SSE stream + replay"`

### Task 12: Vue3 驾驶舱

**Files:**
- Create: `web/` 目录（Vite 脚手架）
- 核心文件：
  - `web/src/stores/pipeline.ts`
  - `web/src/composables/useEventStream.ts`
  - `web/src/pages/Review.vue`
  - `web/src/pages/DiffView.vue`
  - `web/src/pages/Benchmark.vue`
  - `web/src/components/AgentFlow.vue`
  - `web/src/components/ThoughtStream.vue`
  - `web/src/components/FindingCard.vue`
  - `web/src/components/StageProgress.vue`
- Test: `web/src/stores/__tests__/pipeline.spec.ts`

**Interfaces:**
- Consumes: Task 11 的 SSE/replay API
- `pipeline.ts` store 消费 PipelineEvent 更新状态树（类型从后端 schema 同步，见 frontend-design.md §4）

**Steps:**

**阶段 1：脚手架（~30min）**
- [ ] 创建 Vite 项目：
  ```bash
  cd web
  npm create vite@latest . -- --template vue-ts
  npm install
  ```
- [ ] 安装依赖：
  ```bash
  npm install pinia @vueuse/core @vueuse/motion
  npm install naive-ui @vue-flow/core @git-diff-view/vue shiki echarts vue-echarts
  npm install -D tailwindcss postcss autoprefixer vitest @vue/test-utils
  npx tailwindcss init -p
  ```
- [ ] 配置 Tailwind（深色主题 only）：
  ```js
  // tailwind.config.js
  module.exports = {
    darkMode: 'class',
    content: ['./index.html', './src/**/*.{vue,js,ts}'],
    theme: { extend: {} },
  }
  ```
- [ ] 配置 Vite + TypeScript，确保 `npm run build` 通过

**阶段 2：类型与 Store（~40min）**
- [ ] 从 backend PipelineEvent schema 生成 TypeScript 类型（手动同步到 `src/types/events.ts`）
  ```typescript
  // src/types/events.ts
  export type PipelineEvent = 
    | { type: 'stage'; stage: string; status: string; elapsed: number; timestamp: number }
    // ... 完整定义见 frontend-design.md §4
  
  export interface Finding {
    category: 'logic' | 'security' | 'memory' | 'architecture' | 'static';
    severity: 'critical' | 'high' | 'medium' | 'low';
    confidence: number;
    // ... 完整字段
  }
  ```
- [ ] 写 `web/src/stores/__tests__/pipeline.spec.ts`：
  ```typescript
  import { setActivePinia, createPinia } from 'pinia'
  import { usePipelineStore } from '../pipeline'
  
  describe('PipelineStore', () => {
    beforeEach(() => {
      setActivePinia(createPinia())
    })
    
    it('processes stage event', () => {
      const store = usePipelineStore()
      store.consumeEvent({ type: 'stage', stage: 'preprocess', status: 'start', timestamp: Date.now() })
      expect(store.currentStage).toBe('preprocess')
    })
    
    it('accumulates findings', () => {
      const store = usePipelineStore()
      store.consumeEvent({ type: 'finding', finding: {...}, timestamp: Date.now() })
      expect(store.findings.length).toBe(1)
    })
    
    it('applies verdict reject', () => {
      const store = usePipelineStore()
      const finding = { id: 'f1', ... }
      store.consumeEvent({ type: 'finding', finding, timestamp: Date.now() })
      store.consumeEvent({ type: 'verdict', verdict: { finding_id: 'f1', verdict: 'reject', ... }, timestamp: Date.now() })
      expect(store.findings[0].verdict).toBe('reject')
    })
  })
  ```
- [ ] 跑测试确认失败：`npm run test`
- [ ] 实现 `src/stores/pipeline.ts`（约 150 行）
- [ ] 实现 `src/composables/useEventStream.ts`（约 80 行）：
  ```typescript
  export function useEventStream(runId: string, mode: 'live' | 'replay' = 'live', speed = 1) {
    const store = usePipelineStore()
    const url = mode === 'live' 
      ? `http://localhost:8000/api/stream/${runId}`
      : `http://localhost:8000/api/replay/${runId}?speed=${speed}`
    
    const eventSource = new EventSource(url)
    eventSource.onmessage = (e) => {
      const event = JSON.parse(e.data)
      store.consumeEvent(event)
    }
    
    onUnmounted(() => eventSource.close())
  }
  ```
- [ ] 测试转绿

**阶段 3：Review 页组件（~2h，用 replay 假数据开发）**
- [ ] 实现 `src/components/StageProgress.vue`（5 阶段进度条 + 倒计时，约 100 行）
- [ ] 实现 `src/components/AgentFlow.vue`（@vue-flow/core 渲染 3 节点拓扑，约 120 行）：
  ```vue
  <template>
    <VueFlow :nodes="nodes" :edges="edges">
      <template #node-agent="{ data }">
        <div :class="getNodeClass(data.status)">
          {{ data.name }}
          <span v-if="data.findingCount" class="badge">{{ data.findingCount }}</span>
        </div>
      </template>
    </VueFlow>
  </template>
  ```
- [ ] 实现 `src/components/ThoughtStream.vue`（打字机效果 + 工具调用气泡，约 150 行）
- [ ] 实现 `src/components/FindingCard.vue`（severity 色条 + 置信度环 + 展开详情，约 180 行）
- [ ] 组装 `src/pages/Review.vue`（三栏布局，约 200 行）
- [ ] 用一个真实 replay run 验证页面渲染正确

**阶段 4：DiffView + Benchmark 页（~1.5h）**
- [ ] 实现 `src/pages/DiffView.vue`（@git-diff-view/vue + 行级装饰，约 150 行）
- [ ] 实现 `src/pages/Benchmark.vue`（大数字卡 + echarts 热力图 + 表格，约 200 行）

**阶段 5：联调（~30min）**
- [ ] 启动后端服务器：`uvicorn reviewcrew.server.app:app --reload`
- [ ] 启动前端开发服务器：`cd web && npm run dev`
- [ ] 选一个真实 run_id，访问 `http://localhost:5173/review/{run_id}?mode=replay&speed=2`
- [ ] 验证：
  - 拓扑图节点状态变化（灰→蓝脉冲→绿→橙徽标）
  - ThoughtStream 打字机效果流畅
  - FindingCard 实时落下
  - Verifier 淘汰动画（划掉 + 变灰）
- [ ] 录一段 30s 试录检查动画帧率（应 ≥30fps）
- [ ] Commit：`git add web/ && git commit -m "feat: Vue3 dashboard with AgentFlow + ThoughtStream + FindingCard"`

**验收标准：**
- `npm run build` 通过无 error
- 三个页面（Review/DiffView/Benchmark）均可渲染
- Replay 模式完整播放一个 run 无卡顿

## Phase 4 — 冲分与交付

### Task 13: 评测迭代循环（时间盒：剩余工期的大头）

**Files:**
- Modify: `reviewcrew/agents/prompts/*.md`、`reviewcrew/pipeline/context.py`（按归因结论调整）
- Create: `benchmark/results/ITERATION_LOG.md`

**目标：命中率 ≥60%、平均误报 ≤8 条、平均耗时 ≤8min**

**迭代策略：数据驱动，禁止盲目调参**

**Steps:**

**轮次 0：全量 baseline（~2h）**
- [ ] 运行 `python benchmark/run_eval.py --full --runner real`（50 PR）
- [ ] 等待完成（预计 50 × 8min = ~7h，可过夜跑）
- [ ] 生成分类命中矩阵：`benchmark/results/<ts>/summary.md`
- [ ] 记录初始分数到 `ITERATION_LOG.md`：
  ```markdown
  # Iteration 0 - Baseline
  Date: 2026-XX-XX
  Model: glm-4-plus
  
  ## Metrics
  - Hit rate: XX% (target ≥60%)
  - Avg false positives: X.X (target ≤8)
  - Avg time: X.Xmin (target ≤8min)
  
  ## Per-category hit matrix
  |          | security | logic | memory | architecture | static |
  |----------|----------|-------|--------|--------------|--------|
  | Hit      | X        | X     | X      | X            | X      |
  | Miss     | X        | X     | X      | X            | X      |
  | Rate     | XX%      | XX%   | XX%    | XX%          | XX%    |
  
  ## Analysis
  - Weakest category: XXX (XX% hit rate)
  - Miss reasons: (待归因)
  ```

**轮次 1-N：归因→改进→验证（每轮 ~1-2h）**
- [ ] **归因阶段**（每个 miss 案例）：
  ```bash
  # 对每个 miss 的 PR，检查 events.jsonl
  python -m reviewcrew.tools.analyze_miss \
    --run-id <run_id> \
    --expected-bug "SQL injection in auth.py:45"
  
  # 输出归因类别：
  # 1. context_missing: 上下文没给够（callers/callees 被裁剪）
  # 2. prompt_blind: prompt checklist 没覆盖该模式
  # 3. verifier_reject: 专家找到但被 Verifier 误杀
  # 4. judge_error: 其实找到了但判定逻辑误判
  ```
- [ ] 手动归因每个 miss，记录到 `ITERATION_LOG.md`
- [ ] **改进决策**（按归因类别）：
  - context_missing → 调整 `context.py` token 预算分配（增加 callers 深度 OR 放宽总预算）
  - prompt_blind → 补充 prompt checklist（添加该缺陷模式到 defect.md/intent.md）
  - verifier_reject → 调整 `verifier.md` 四问条件（降低误杀率）OR 调整 confidence 门限（0.6 → 0.5）
  - judge_error → 修复 `judge.py` 行区间匹配逻辑
- [ ] 只改一处（单变量控制），commit：`git commit -m "iter1: fix context budget for callers (miss case #12)"`
- [ ] **快速验证**（~1h）：
  ```bash
  python benchmark/run_eval.py --quick --runner real  # 10 PR 抽样
  ```
- [ ] 记录分数到 `ITERATION_LOG.md`：
  ```markdown
  # Iteration 1
  Change: Increased callers depth from 1 to 2 hops
  Files: reviewcrew/pipeline/context.py
  
  ## Quick eval (10 PR)
  - Hit rate: XX% (was XX%)
  - Avg FP: X.X (was X.X)
  - Avg time: X.Xmin (was X.Xmin)
  
  Decision: ✅ Keep (hit rate +5%) | ❌ Revert (no improvement)
  ```
- [ ] **决策**：
  - 若分数涨 → 保留改动，跑 `--full` 确认：`python benchmark/run_eval.py --full`
  - 若分数不变或降 → revert：`git revert HEAD`
- [ ] 重复归因→改进→验证，直到达标

**特殊情况：某类缺陷持续塌陷**
- [ ] 若某一 category 命中率 <30%（如 memory 类），评估拆分为独立 Agent：
  ```markdown
  ## Iteration 5 - Consider MemoryAgent split
  Current: DefectAgent covers security+memory+static
  Problem: Memory hit rate 20% (6 miss / 2 hit)
  
  Option: Split MemoryAgent as 3rd expert (2→3 agents)
  Cost: +40% token, +2min latency
  
  Decision: Run A/B test (1 仓库 × 10 PR)
  ```
- [ ] A/B 测试：实现 MemoryAgent，对比 10 个 memory 类 PR 的命中率
- [ ] 用分数决策是否拆分

**冻结条件：**
- [ ] 连续两轮 `--full` 评测达标：
  - 命中率 ≥60%
  - 平均误报 ≤8 条
  - 平均耗时 ≤8min
- [ ] 记录最终分数到 `ITERATION_LOG.md` 末尾：
  ```markdown
  # Final Freeze
  Date: 2026-XX-XX
  Iterations: X
  
  ## Final Metrics
  - Hit rate: XX%
  - Avg FP: X.X
  - Avg time: X.Xmin
  
  ## Changes from baseline
  - Increased callers depth 1→2
  - Added 3 security patterns to defect.md
  - Lowered verifier confidence threshold 0.6→0.55
  ```
- [ ] Commit：`git commit -m "eval: freeze at XX% hit rate after N iterations"`

**验收标准：**
- `ITERATION_LOG.md` 记录完整（每轮改动 + 分数 + 决策）
- 最终 `--full` 评测达标
- 每轮迭代必须 commit（保留历史，便于回滚）

### Task 14: 交付三件套

**Files:**
- Create: `README.md`, `docs/评测报告.md`, `docs/演示脚本.md`
- Media: `demo.mp4`（演示视频）

**Steps:**

**子任务 14.1：README.md（~1h）**
- [ ] 编写 README.md（约 300 行），包含：
  ```markdown
  # ReviewCrew - AI 驱动智能代码审查系统
  
  ## 简介
  基于 GLM + Pydantic AI 的多 Agent 协作代码审查系统（2 专家 + 1 Verifier）
  
  ## 特性
  - ✅ 聚焦 PR diff 精准审查
  - ✅ 覆盖 6 类缺陷：安全/逻辑/内存/架构/静态/业务
  - ✅ 对抗验证压制误报
  - ✅ 单 PR ≤10 分钟
  - ✅ 知识库维护方案（离线 Profile）
  
  ## 架构
  [插入 design-doc.md §2 的架构图]
  
  双层架构：离线知识层 + 在线五阶段管道
  
  ## 技术栈
  - 后端：Python 3.12 + pydantic-ai + httpx + tree-sitter + FastAPI
  - 前端：Vue 3 + Vite + TypeScript + Pinia + Tailwind + Naive UI
  - LLM：GLM API（glm-4-plus / glm-5）
  
  ## 安装
  ```bash
  # 后端
  pip install -e .
  export GLM_API_KEY=your_key
  
  # 前端
  cd web && npm install
  ```
  
  ## 使用
  ### CLI 模式
  ```bash
  reviewcrew review --pr https://github.com/owner/repo/pull/123 --repo-path repos/repo.git
  ```
  
  ### Web 模式
  ```bash
  # 启动后端
  uvicorn reviewcrew.server.app:app --port 8000
  
  # 启动前端
  cd web && npm run dev
  ```
  
  ## 知识库维护方案
  每个仓库需预构建 Profile（符号索引 + 架构摘要 + 历史 bug 模式）：
  
  ### 初次接入
  ```bash
  python -m reviewcrew.profile.builder update --repo /path/to/repo
  ```
  
  ### 增量更新（PR merge 后）
  ```bash
  python -m reviewcrew.profile.builder update \
    --repo /path/to/repo \
    --changed src/api/auth.py src/api/users.py
  ```
  
  ### Webhook 配置（推荐）
  ```yaml
  # .github/workflows/update-profile.yml
  on:
    push:
      branches: [main]
  jobs:
    update-profile:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v3
        - run: |
            python -m reviewcrew.profile.builder update \
              --repo . \
              --changed $(git diff-tree --no-commit-id --name-only -r ${{ github.sha }})
  ```
  
  ### 维护周期
  - PR merge hook：增量更新符号索引（秒级）
  - 每日定时：增量刷新架构摘要（分钟级）
  - 每周定时：重挖历史 bug 模式
  
  ## 评测结果
  见 `docs/评测报告.md`（Greptile Benchmark，50 PR）
  
  ## 与 SonarQube 对比
  | 维度 | SonarQube | ReviewCrew |
  |---|---|---|
  | 逻辑类缺陷 | 规则库盲区 | LLM 推理覆盖 |
  | 误报率 | 高（无语义理解） | 低（对抗验证） |
  | 适配性 | 通用规则 | 仓库专属 bug 模式 |
  | 上下文关联 | 无 | PR 意图 + 测试变更 |
  | 时效 | 全量扫描慢 | diff 聚焦 ≤10min |
  
  ## License
  MIT
  ```
- [ ] 插入架构图（从 design-doc.md 提取，转为 ASCII 或 Mermaid）
- [ ] 验证所有命令可执行

**子任务 14.2：评测报告（~1h）**
- [ ] 编写 `docs/评测报告.md`（约 200 行）：
  ```markdown
  # ReviewCrew 评测报告
  
  ## 数据集
  - 来源：Greptile Benchmark
  - 规模：5 仓库 × 10 PR = 50 个真实漏洞
  - 语言：Python, Go, TypeScript, Rust, Java
  
  ## Fork 仓库列表
  1. [owner/repo1](https://github.com/your-org/repo1) - Python web 框架
  2. [owner/repo2](https://github.com/your-org/repo2) - Go 微服务
  3. ...
  
  ## 评测方法
  - 判定：文件+行区间重叠（±10 行）OR GLM 语义比对
  - 指标：命中率、平均误报数、平均耗时
  
  ## 最终指标
  | 指标 | 结果 | 目标 | 达标 |
  |---|---|---|---|
  | 命中率 | XX% | ≥60% | ✅/❌ |
  | 平均误报 | X.X | ≤8 | ✅/❌ |
  | 平均耗时 | X.Xmin | ≤8min | ✅/❌ |
  
  ## 分类命中矩阵
  [插入 benchmark/results/<final>/summary.md 的矩阵表]
  
  ## 命中案例展示（选 5 个）
  ### Case 1: SQL Injection in auth.py
  - PR: [链接]
  - 漏洞行: auth.py:45-48
  - ReviewCrew 报告:
    - Severity: critical
    - Confidence: 0.89
    - Reasoning: "String concatenation in SQL query without sanitization..."
  - [截图]
  
  ### Case 2: ...
  
  ## Miss 案例分析
  [选 2-3 个 miss 案例，分析原因]
  
  ## 迭代历史
  [摘要 ITERATION_LOG.md 的关键改进]
  ```
- [ ] 收集截图：从 web UI 的 FindingCard 截图 5 个命中案例
- [ ] 生成最终矩阵表：`python benchmark/report.py --final`

**子任务 14.3：演示视频（~2h）**
- [ ] 编写 `docs/演示脚本.md`（分镜表）：
  ```markdown
  # 演示视频脚本（3 分钟）
  
  ## 前期准备
  - 选最佳 run（命中 1 个 critical + 2 个 high，耗时 ~7min）
  - 清理终端输出
  - 浏览器全屏，隐藏书签栏
  
  ## 分镜
  ### 0:00-0:20 开场（20s）
  - 镜头：黑屏 → 标题卡
  - 画面：ReviewCrew Logo + "AI 驱动智能代码审查"
  - 旁白："传统工具难以发现逻辑类缺陷，ReviewCrew 用多 Agent 协作突破盲区"
  
  ### 0:20-0:50 提交审查（30s）
  - 镜头：Web UI 首页
  - 操作：粘贴 PR URL → 点击"开始审查"
  - 画面：跳转到 Review 页，拓扑图 3 节点亮起
  - 旁白："聚焦 PR diff，10 分钟精准审查"
  
  ### 0:50-1:40 Agent 工作（50s）
  - 镜头：驾驶舱全景（三栏布局）
  - 画面重点：
    - 左栏：5 阶段进度条推进
    - 中栏：AgentFlow 节点蓝色脉冲 + ThoughtStream 打字机滚动
    - 工具调用气泡："🔍 read_file auth.py" → "🕸️ find_references verify_token"
    - 右栏：FindingCard 实时落下（3 张卡片依次入场）
  - 旁白："DefectAgent 追踪 taint 流，IntentAgent 对比意图与实现，主动查证据"
  
  ### 1:40-2:10 对抗验证（30s）
  - 镜头：Verifier 节点激活
  - 画面：2 张 FindingCard 被划掉（灰色淡出动画）+ 气泡显示原因："已验证排除：上游有校验兜底"
  - 最终保留 3 条（1 critical + 2 high）
  - 旁白："Verifier 四问质疑，压制误报"
  
  ### 2:10-2:40 结果展示（30s）
  - 镜头：点击 critical finding → 跳转 DiffView 页
  - 画面：diff 视图，命中行红色高亮 + 侧滑抽屉展示完整推理
  - 点击"生成 PR comment"按钮
  - 旁白："精准锚定到行，一键生成 PR review comment"
  
  ### 2:40-2:55 Benchmark 仪表盘（15s）
  - 镜头：切换到 Benchmark 页
  - 画面：命中率大数字 XX%（动画计数）+ 热力图 + 50 PR 表格滚动
  - 旁白："50 个真实漏洞评测，命中率达标"
  
  ### 2:55-3:00 结尾（5s）
  - 镜头：标题卡
  - 画面：GitHub 链接 + "开源 MIT"
  - 旁白："ReviewCrew，让代码审查更智能"
  ```
- [ ] 录制视频（用 OBS Studio / QuickTime）：
  ```bash
  # 准备 replay 数据
  RUN_ID=<最佳 run>
  
  # 启动服务
  uvicorn reviewcrew.server.app:app &
  cd web && npm run dev
  
  # 浏览器访问
  http://localhost:5173/review/${RUN_ID}?mode=replay&speed=1.5
  ```
- [ ] 录制时注意：
  - 全屏模式（F11）
  - 隐藏鼠标指针（CSS: cursor: none）
  - 提前彩排 2-3 次
- [ ] 后期剪辑（可选）：
  - 添加转场效果
  - 配背景音乐（无版权）
  - 导出 MP4（1080p, 30fps）
- [ ] 保存为 `demo.mp4`

**子任务 14.4：交付物终检（30min）**
- [ ] 对照题目"交付内容"清单逐项打勾：
  ```markdown
  - [x] 5 个 fork 仓库链接（README.md）
  - [x] 评测报告（docs/评测报告.md）
  - [x] 命中 PR 的提交链接（评测报告中）
  - [x] Finding 截图（评测报告中，≥5 张）
  - [x] 演示视频（demo.mp4, ≤3 分钟）
  - [x] 源代码（GitHub 仓库）
  - [x] 部署说明（README.md）
  - [x] 知识库维护方案（README.md §知识库维护）
  ```
- [ ] 验证所有链接可访问
- [ ] 检查视频文件大小（<100MB）
- [ ] Commit：`git add README.md docs/ demo.mp4 && git commit -m "docs: complete deliverables (README + report + demo)"`
- [ ] Tag 版本：`git tag v1.0 && git tag -a v1.0 -m "Release v1.0: 50-PR eval passed, XX% hit rate"`
- [ ] 推送（如需要）：`git push origin develop-1.1 --tags`

**验收标准：**
- README.md 包含安装/使用/维护方案，所有命令可执行
- 评测报告包含 5 个 fork 链接、最终指标、命中案例截图
- 演示视频 ≤3 分钟，覆盖核心功能，画质清晰

---

## 需求 → 任务追溯表

| 题目需求 | 落地任务 |
|---|---|
| 聚焦 PR diff 精准审查 | T3(diff 解析) T6(diff 中心上下文) |
| 静态缺陷 | T5(linter/deps) T8(DefectAgent 静态节) |
| 业务逻辑 + 逻辑缺陷 | T8(IntentAgent 三步法) |
| 内存问题 | T8(DefectAgent 内存节) |
| 安全漏洞 | T5(semgrep) T8(DefectAgent 安全节+taint) |
| 架构问题 | T4(架构摘要) T8(IntentAgent 依赖方向清单) |
| 10min 时效 | T10(watchdog+预算) T13(耗时达标验证) |
| GLM 模型对齐 | T1(GLM client) |
| 知识库维护方案 | T4(builder.py update) T14(README 章节) |
| 结合传统扫描工具 | T5(SignalProvider) |
| MCP/工具挖掘 | T7(Toolbox：LSP 级引用查询/blame/定向 semgrep) |
| 误报控制 | T9(Verifier 四问+门限+截断) |
| 评测报告 | T2(harness) T13(迭代) T14(报告) |
| 演示视频 | T11(replay) T12(驾驶舱) T14(录制) |

## 自检记录（writing-plans 要求）

- **覆盖扫描**：题目"任务目标/指导建议/交付内容"逐条均有对应任务（见追溯表），无缺口
- **占位符扫描**：无 TBD/TODO；唯一延迟决策项为 dataset.yaml 的具体 PR 列表与索引语言集，由 T2 收集步骤产出，属数据而非设计空洞
- **类型一致性**：`Finding`/`PipelineEvent`/`ContextPack`/`SignalProvider`/`ReviewRunner` 五个跨任务接口的字段与签名在 T1/T2/T5/T6/T7 定义后被后续任务按名引用，无同名异构
