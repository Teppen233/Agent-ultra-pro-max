# ReviewCrew Implementation Plan

> **For agentic workers:** 本计划遵循 superpowers:writing-plans 框架编写。按任务顺序执行，
> 每个任务以 checkbox (`- [ ]`) 步骤跟踪，每个任务结束必须通过其验收命令后才能进入下一任务。
> 规格来源：`design-doc.md`（总架构）· `agent-topology.md`（Agent 层，取代 design-doc §4-③）· `frontend-design.md`（演示层）

**Goal:** 构建以 2 专家 Agent + 1 Verifier 为核心的 AI Code Review 系统，在 Greptile Benchmark（5 仓库 × 10 PR）上达成 ≥60% 目标漏洞命中率，单 PR ≤10 分钟。

**Architecture:** 双层架构——离线知识层（tree-sitter 符号索引/call graph/架构摘要/历史 bug 模式）+ 在线五阶段管道（预处理 → 上下文组装 → 2 专家并行审查 → 对抗验证 → 报告）。静态信号（Semgrep/linter/依赖审计）作为证据注入，Agent 裁决真伪。

**Tech Stack:** Python 3.12 + asyncio + httpx + tree-sitter + SQLite + FastAPI(SSE) · Vue 3 + Vite + TS + Pinia + Tailwind + Naive UI + @vue-flow/core + @git-diff-view/vue + shiki + echarts · pytest + Vitest

## Global Constraints

- 单 PR 在线管道总耗时 ≤ 10min（watchdog 硬截断，内部预算 8.5min）
- LLM 仅走 GLM API，temperature=0.2，结构化输出走 JSON mode
- 在线 Agent 只有 3 种：DefectAgent / IntentAgent / VerifierAgent；Orchestrator、Context Builder、报告生成不得实现为 Agent
- 单 PR 最终输出 ≤ 8 条 findings；confidence < 0.6 一律丢弃
- 不引入 LangChain/LangGraph；Agent loop 自研（base.py ≤ 300 行）
- 不使用 CodeQL
- 所有 LLM 交互（prompt/response/tool calls）落盘 `runs/<run_id>/events.jsonl`（供 replay 与 debug）
- Python 代码全部带类型注解，pytest 覆盖核心逻辑；每个任务结束 commit 一次

---

## Phase 0 — 地基

### Task 1: 项目脚手架 + GLM Client

**Files:**
- Create: `pyproject.toml`, `reviewcrew/__init__.py`, `reviewcrew/config.py`, `reviewcrew/llm/glm.py`, `reviewcrew/events.py`
- Test: `tests/test_glm.py`, `tests/test_events.py`

**Interfaces:**
- Provides: `GLMClient.chat(messages: list[Message], tools: list[ToolSpec] | None, json_schema: dict | None) -> LLMResponse`（内置：429/5xx 指数退避重试×3、JSON 解析失败带错误反馈重试×2、每次调用写 events.jsonl）
- Provides: `EventLogger.emit(event: PipelineEvent) -> None`；`PipelineEvent` 为 tagged union：`stage|agent|thought|tool|finding|verdict|report`（字段对齐 frontend-design.md §4，这是前后端唯一契约）
- Provides: `Config.from_env()`（GLM_API_KEY、并发信号量上限、时间预算常量）

**Steps:**
- [ ] 写 `tests/test_events.py`：PipelineEvent 序列化/反序列化 round-trip；跑测试确认失败
- [ ] 实现 `events.py`（pydantic tagged union）+ `config.py`；测试转绿
- [ ] 写 `tests/test_glm.py`：mock httpx，覆盖重试、JSON mode 解析失败反馈重试；跑测试确认失败
- [ ] 实现 `glm.py`；测试转绿
- [ ] 用真实 API key 跑一次冒烟脚本 `python -m reviewcrew.llm.glm --smoke`
- [ ] Commit

### Task 2: 评测 Harness（最高优先级，先于一切管道代码）

**Files:**
- Create: `benchmark/dataset.yaml`, `benchmark/collect.py`, `benchmark/run_eval.py`, `benchmark/judge.py`, `benchmark/report.py`
- Test: `tests/test_judge.py`

**Interfaces:**
- `dataset.yaml` 条目 schema：`{repo, fork_url, pr_url, base_sha, head_sha, bug_desc, bug_files: [{path, line_start, line_end}], category}`
- Provides: `judge(findings: list[Finding], entry: DatasetEntry) -> JudgeResult`——两级判定：① 文件+行区间重叠（±10 行容差）② 未命中时 GLM 语义比对（finding.reasoning vs bug_desc，输出 hit/miss + 理由）
- Provides: `run_eval.py --quick`（抽样 10 PR）/ `--full`（50 PR），输出 `benchmark/results/<ts>/{results.jsonl, summary.md}`；summary 含命中率、平均误报数、平均耗时、仓库×缺陷类型命中矩阵
- Consumes: Task 1 的 `GLMClient`、`Finding`

**Steps:**
- [ ] 运行 `collect.py`：从 greptile.com/benchmarks 抓 5 仓库 50 PR 元数据，人工核对后填 `dataset.yaml`（bug_files 行号从 fix PR 反推）
- [ ] Fork 5 个仓库到自有 org，`git clone --bare` 缓存到 `repos/`；dataset 中 fork_url 全部可 clone 验证通过
- [ ] 写 `tests/test_judge.py`：行区间重叠命中/未命中/语义兜底三个用例（语义级 mock GLM）；确认失败
- [ ] 实现 `judge.py`；测试转绿
- [ ] 实现 `run_eval.py` + `report.py`，被测系统以 `ReviewRunner` Protocol 注入（此时用 FakeRunner 假实现打通全链路）
- [ ] `python benchmark/run_eval.py --quick --runner fake` 出报表验证格式
- [ ] Commit

## Phase 1 — 离线知识层

### Task 3: Diff 解析 + 符号索引 + Call Graph

**Files:**
- Create: `reviewcrew/pipeline/diff_parser.py`, `reviewcrew/profile/indexer.py`
- Test: `tests/test_diff_parser.py`, `tests/test_indexer.py`, `tests/fixtures/sample.diff`, `tests/fixtures/mini_repo/`

**Interfaces:**
- Provides: `parse_diff(raw: str) -> list[FileDiff]`；`FileDiff{path, hunks: list[Hunk{old_range, new_range, lines}], change_type}`；噪音过滤规则：lockfile 名单、`# generated` 标头、纯空白变更
- Provides: `RepoIndex.build(repo_path: Path, langs: list[str]) -> None`（tree-sitter 解析 → SQLite `profile/symbols.db`）
- Provides: `RepoIndex.definition(symbol) -> Location`、`.references(symbol) -> list[Location]`、`.callers(func, hops=1) -> list[FuncNode]`、`.callees(func, hops=1) -> list[FuncNode]`、`.update_incremental(changed_files) -> None`
- 语言覆盖：benchmark 5 仓库实际语言（Task 2 收集后确定），tree-sitter grammar 逐语言注册

**Steps:**
- [ ] 写 diff parser 测试（含 rename/delete/lockfile 过滤用例）；确认失败 → 实现 → 转绿
- [ ] 构造 `mini_repo` fixture（两文件互相调用）；写 indexer 测试：definition/references/callers 断言；确认失败
- [ ] 实现 indexer（tree-sitter query 抽 def/call 边 → SQLite）；测试转绿
- [ ] 对 5 个真实仓库跑 `python -m reviewcrew.profile.indexer repos/<name>`，记录建库耗时（必须离线可接受，单仓 <30min）
- [ ] Commit

### Task 4: 架构摘要 + 历史 Bug 模式挖掘 + Profile 更新入口

**Files:**
- Create: `reviewcrew/profile/summarizer.py`, `reviewcrew/profile/bug_miner.py`, `reviewcrew/profile/builder.py`
- Test: `tests/test_bug_miner.py`

**Interfaces:**
- Provides: `build_profile(repo_path) -> RepoProfile`，产出 `profile/{architecture.md, bug_patterns.md, symbols.db}`
- Provides: `RepoProfile.arch_slice(paths: list[str]) -> str`（按变更文件检索相关模块摘要片段，≤2K tokens）
- summarizer 策略：目录树 + 各模块头部代码采样 → GLM 分模块生成，再汇总；bug_miner：`git log --grep` 拉 fix commits → GLM 归纳 ≤10 条仓库专属缺陷模式
- Provides: `builder.py update --repo <path> --changed <files>`（增量入口，知识库维护方案的落地命令）

**Steps:**
- [ ] 写 bug_miner 测试（mock git log 输出 + mock GLM）；确认失败 → 实现 → 转绿
- [ ] 实现 summarizer + builder；对 5 仓库全量构建 profile，人工抽查 architecture.md 质量
- [ ] README 草记知识库更新方案（merge hook 调 `builder.py update`）
- [ ] Commit

## Phase 2 — 在线管道

### Task 5: 静态信号层

**Files:**
- Create: `reviewcrew/signals/base.py`, `reviewcrew/signals/semgrep.py`, `reviewcrew/signals/linters.py`, `reviewcrew/signals/deps.py`
- Test: `tests/test_signals.py`

**Interfaces:**
- Provides: `SignalProvider` Protocol：`async scan(repo_path, files: list[str]) -> list[Signal]`；`Signal{provider, rule_id, file, line, message, severity}`
- semgrep：`semgrep --config auto --json` 定向扫 diff 文件；linters 按语言路由（go vet/eslint/ruff/clippy）；deps：lockfile diff → osv.dev batch API
- 失败语义：单 provider 异常/超时(60s) → 返回空列表 + 日志，绝不抛出阻塞管道

**Steps:**
- [ ] 写测试：mock 子进程输出解析 + provider 超时降级用例；确认失败 → 实现 → 转绿
- [ ] 真实仓库冒烟：对一个 benchmark PR 的 diff 文件跑三个 provider，确认 30s 内返回
- [ ] Commit

### Task 6: ContextPack 组装器

**Files:**
- Create: `reviewcrew/pipeline/context.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Provides: `build_context_packs(diffs, index: RepoIndex, profile: RepoProfile, signals, pr_meta: PRMeta) -> list[ContextPack]`
- `ContextPack` 字段对齐 design-doc §4-②：diff_hunks / enclosing_code / callers_callees(1-2 跳) / arch_summary / bug_patterns / intent(PR 描述+issue+测试变更单独标注) / static_signals(对齐行号)
- 裁剪策略：单 pack token 预算 32K（tiktoken 估算），超出按"离 diff 行距离"由远及近裁剪；文件语义聚类：同目录/同模块 hunks 归入同一 pack

**Steps:**
- [ ] 写测试：聚类正确性 + 超预算裁剪顺序 + 测试文件变更进 intent 字段；确认失败
- [ ] 实现；测试转绿
- [ ] Commit

### Task 7: Agent 基座 + 工具箱

**Files:**
- Create: `reviewcrew/agents/base.py`, `reviewcrew/tools/toolbox.py`
- Test: `tests/test_agent_loop.py`

**Interfaces:**
- Provides: `class BaseAgent: async run(pack: ContextPack, budget: Budget) -> list[Finding]`——循环 ≤12 轮；每轮 GLM 输出либо tool_call либо findings JSON；**每 4 轮强制输出中间 findings 快照**；超时/超轮次取最后快照（agent-topology §7）
- Provides: `Toolbox`：`read_file(path, start, end)` / `find_references(symbol)` / `get_callers(func)` / `get_callees(func)` / `git_blame(path, line_range)` / `run_semgrep_rule(rule_id, path)`——全部只读，路径白名单限制在 repo 内
- `Finding` schema 逐字段对齐 design-doc §4-③（category/severity/confidence/file/line/title/reasoning/trigger_path/suggestion）
- 每轮 emit `thought` 与 `tool` 事件到 EventLogger

**Steps:**
- [ ] 写测试：mock GLM 驱动 3 轮循环（tool→tool→findings）、快照兜底、非法 JSON 重试；确认失败
- [ ] 实现 base.py + toolbox.py；测试转绿
- [ ] Commit

### Task 8: DefectAgent + IntentAgent

**Files:**
- Create: `reviewcrew/agents/defect.py`, `reviewcrew/agents/intent.py`, `reviewcrew/agents/prompts/defect.md`, `reviewcrew/agents/prompts/intent.md`
- Test: `tests/test_expert_agents.py`

**Interfaces:**
- 均继承 BaseAgent，仅差 system prompt 与上下文侧重（agent-topology §2）
- defect.md：分节 checklist（安全→内存→静态），节间显式角色切换指令；含 taint 追踪与资源生命周期方法论
- intent.md：固定三步（意图总结→变更语义总结→diff 找偏差），再过边界/状态机/依赖方向清单
- Provides: `shard_packs(packs, max_shards=3) -> list[list[ContextPack]]`（大 PR 按聚类分片，同模块不拆）

**Steps:**
- [ ] 写分片测试 + prompt 加载测试；确认失败 → 实现 → 转绿
- [ ] 挑 benchmark 中 1 个已知逻辑类 bug 的 PR 手动跑 IntentAgent，人工检查推理质量（不进 CI，作为 prompt 调试基线）
- [ ] 同法跑 DefectAgent（挑安全类 bug PR）
- [ ] Commit

### Task 9: VerifierAgent + 输出控制

**Files:**
- Create: `reviewcrew/agents/verifier.py`, `reviewcrew/agents/prompts/verifier.md`, `reviewcrew/pipeline/dedupe.py`
- Test: `tests/test_verifier.py`, `tests/test_dedupe.py`

**Interfaces:**
- Provides: `dedupe(findings) -> list[Finding]`（同文件行区间重叠→合并取高置信；跨 agent 语义近似→embedding 余弦 >0.85 合并）
- Provides: `VerifierAgent.run(findings, toolbox) -> list[Verdict]`；四问质疑（可达性/防御兜底/测试代码/严重度虚高），干净上下文（不含专家推理原文，只给 finding + 代码证据）
- 门限：confidence<0.6 丢弃 → severity×confidence 排序 → 截断 8 条；每条 emit `verdict` 事件（keep/reject + reason，前端淘汰动画数据源）

**Steps:**
- [ ] 写 dedupe 测试（行重叠合并/语义合并/不误合并）；确认失败 → 实现 → 转绿
- [ ] 写 verifier 测试（mock GLM：一条 keep 一条 reject，断言门限与截断）；确认失败 → 实现 → 转绿
- [ ] Commit

### Task 10: Orchestrator + 报告 + CLI —— 管道合龙

**Files:**
- Create: `reviewcrew/pipeline/orchestrator.py`, `reviewcrew/pipeline/report.py`, `reviewcrew/cli.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Provides: `Orchestrator.review(pr_url: str) -> ReviewResult`——五阶段串联；DefectAgent 与 IntentAgent `asyncio.gather` 并行；全局 watchdog：阶段预算 {preprocess:10s, context:60s, review:300s, verify:120s, report:30s}，超时取快照强制收敛；每阶段 emit `stage` 事件
- Provides: `report.py`：Markdown 报告 + GitHub Review Comment JSON（行级锚定）双格式
- Provides: `reviewcrew review --pr <url> [--repo-path <cached>]`；实现 Task 2 的 `ReviewRunner` Protocol → 接入 run_eval
- Consumes: Tasks 3-9 全部接口

**Steps:**
- [ ] 写 orchestrator 测试：全 mock 下五阶段事件序列正确、review 阶段超时快照收敛；确认失败 → 实现 → 转绿
- [ ] 实现 report.py + cli.py
- [ ] 端到端冒烟：真实跑 1 个 benchmark PR，`runs/<id>/events.jsonl` 完整，耗时 <10min
- [ ] `python benchmark/run_eval.py --quick --runner real` → **记录 baseline 分数到 benchmark/results/BASELINE.md**
- [ ] Commit

## Phase 3 — 演示层

### Task 11: FastAPI 服务 + SSE + Replay

**Files:**
- Create: `reviewcrew/server/app.py`, `reviewcrew/server/replay.py`
- Test: `tests/test_server.py`

**Interfaces:**
- `POST /api/review {pr_url}` → `{run_id}`（后台任务启动管道）
- `GET /api/stream/{run_id}` → SSE，事件即 PipelineEvent JSON（Task 1 契约，零转换透传）
- `GET /api/replay/{run_id}?speed=2` → 读 events.jsonl 按原时间戳/speed 重放（frontend-design §4 保命功能）
- `GET /api/runs` / `GET /api/benchmark/latest`（仪表盘数据源，读 results 目录）

**Steps:**
- [ ] 写测试：replay 时序（3 事件按 ts 间隔吐出，speed=2 减半）+ SSE 格式；确认失败 → 实现 → 转绿
- [ ] 用 Task 10 的真实 run 验证 replay 全程可放
- [ ] Commit

### Task 12: Vue3 驾驶舱

**Files:**
- Create: `web/`（Vite 脚手架）、`web/src/stores/pipeline.ts`、`web/src/composables/useEventStream.ts`、`web/src/pages/{Review.vue, DiffView.vue, Benchmark.vue}`、`web/src/components/{AgentFlow.vue, ThoughtStream.vue, FindingCard.vue, StageProgress.vue}`
- Test: `web/src/stores/__tests__/pipeline.spec.ts`（Vitest）

**Interfaces:**
- Consumes: Task 11 的 SSE/replay API；`pipeline.ts` store 消费 PipelineEvent 更新状态树（类型从后端 schema 生成，勿手写两份）
- AgentFlow：@vue-flow/core 渲染 agent-topology §6 拓扑（3 agent 节点 + 调度器），状态色：灰→蓝脉冲→绿→橙徽标
- ThoughtStream：打字机 composable（~30 行自研）+ 工具调用气泡；FindingCard：severity 色条 + 置信度环 + 展开推理/触发路径；verdict=reject → 划掉动画（@vueuse/motion）
- DiffView：@git-diff-view/vue + shiki，命中行装饰，点击侧滑抽屉；Benchmark：echarts 大数字卡 + 5×6 热力图 + 50 PR 结果表
- 布局/交互细节全部以 frontend-design.md §3 为准；深色主题 only

**Steps:**
- [ ] Vite 脚手架 + Tailwind + Naive UI + 依赖安装；`npm run build` 通过
- [ ] 写 pipeline store 测试（喂事件序列断言状态）；确认失败 → 实现 store + useEventStream；转绿
- [ ] 实现 Review 页（AgentFlow + ThoughtStream + FindingCard + StageProgress），**用 replay 假数据开发，不依赖后端进度**
- [ ] 实现 DiffView 页 + Benchmark 页
- [ ] 联调：真实 replay 一个 run，三页全部工作；录一段 30s 试录检查动画帧率
- [ ] Commit

## Phase 4 — 冲分与交付

### Task 13: 评测迭代循环（时间盒：剩余工期的大头）

**Files:**
- Modify: `reviewcrew/agents/prompts/*.md`、`reviewcrew/pipeline/context.py`（按归因结论）
- Create: `benchmark/results/ITERATION_LOG.md`

**Steps:**
- [ ] `run_eval --full` 全量跑 50 PR，出分类命中矩阵
- [ ] 对每个 miss 归因（上下文没给够 / prompt 盲区 / verifier 误杀 / 判定误判），写进 ITERATION_LOG
- [ ] 按归因改 prompt/上下文/门限 → `--quick` 验证 → 有效则 `--full` 确认，循环；**每轮迭代必须记录分数，只保留涨分的改动**
- [ ] 若某缺陷类命中率持续塌陷，评估拆分该类为独立 agent（agent-topology §7 预留的后门），用分数决策
- [ ] 达标线：命中率 ≥60%、平均误报 ≤8 条、平均耗时 ≤8min → 冻结
- [ ] Commit（每轮迭代单独 commit）

### Task 14: 交付三件套

**Files:**
- Create: `README.md`、`docs/评测报告.md`、`docs/演示脚本.md`

**Steps:**
- [ ] README：安装/配置/使用 + 架构图 + 知识库维护方案（builder.py update + hook 配置）+ SonarQube 差异化表（design-doc §9）
- [ ] 评测报告：5 个 fork 仓库链接 + 每个命中 PR 的提交链接与 finding 截图 + 最终指标表
- [ ] 演示视频：按 frontend-design §5 分镜表，用 replay 模式挑最佳 run 录制，≤3 分钟
- [ ] 终检：三份交付物对照题目"交付内容"清单逐项打勾
- [ ] Commit + tag `v1.0`

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
