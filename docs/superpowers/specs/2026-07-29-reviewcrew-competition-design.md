# ReviewCrew 竞赛交付设计

> 日期：2026-07-29
>
> 硬截止时间：2026-07-30 12:00（北京时间，Asia/Shanghai，UTC+8）
>
> 代码冻结时间：2026-07-30 11:30（北京时间）
>
> 实施方式：四名开发者基于同一份规范独立赛马，次日上午合并优势并专项调优。

## 1. 目标与验收范围

开发一套以 Agent 为核心的 AI Code Review 系统，围绕 Git Pull Request 的差异内容开展精准审查，并按需补充与修改代码直接相关的上下文。

截止北京时间 2026-07-30 12:00，系统必须完成代码、测试、文档和可提交材料，并具备以下能力：

 1. 输入 GitHub PR URL，或输入本地仓库、基准提交和目标提交。
 2. 只分析 PR diff、修改符号及相关上下文，不进行无目标的全仓 LLM 扫描。
 3. 使用 OpenAI 兼容端点的 LLM（默认智谱 GLM 系列）完成代码理解、缺陷发现和结果验证。通过 `LLM_BASE_URL`、`LLM_MODEL_NAME`、`LLM_API_KEY` 环境变量配置，不硬编码特定模型版本。
 4. 覆盖静态缺陷、业务逻辑、逻辑缺陷、内存与资源问题、安全漏洞和架构问题。
 5. 使用两个专家 Subagent 生成候选缺陷，使用一个独立 Verifier Subagent 过滤误报。
 6. 单个 PR 的全流程由 600 秒全局 watchdog 约束。
 7. 输出结构化 JSON、Markdown 报告和适合前端展示的事件流。
 8. 提供 Vue 3 前端，展示审查进度、Agent 状态、Finding、Verifier 结论和评测结果。
 9. 支持历史运行 Replay，保证演示不依赖现场模型和网络稳定性。
10. 提供可运行源码、README、评测报告、成功命中链接和不超过三分钟的演示视频。
11. 所有开发、测试和 Replay 以 Fake Model 为基线运行，不依赖网络或真实 API Key。真实 LLM 调用仅作为最终验证层，不阻塞功能实现。

本次只有一次交付，不设置“远期架构”或不落地的职责。文档中出现的组件都必须在最终代码中存在；无法在时限内可靠实现的能力，只能作为可选 Provider 或明确的降级路径，不得伪装成已经完成。

## 2. 核心设计原则

 1. **Diff 中心**：所有分析从修改文件、hunk 和修改行出发。
 2. **按需取上下文**：只检索修改符号、直接相关代码、测试、项目文档和 Git 历史。
 3. **高召回后验证**：专家 Agent 负责寻找候选问题，Verifier 负责寻找反证并决定是否发布。
 4. **确定性编排**：Orchestrator、Context Builder、去重和报告生成使用普通代码实现，不升格为 Agent。
 5. **最小只读权限**：Agent 工具默认只允许读取仓库、搜索代码和查询 Git 信息。
 6. **单点失败可降级**：Semgrep、Git 历史或某个专家失败时，其他阶段继续执行并记录警告。
 7. **事件驱动解耦**：前端只依赖冻结的 REST、SSE 和 PipelineEvent 协议。
 8. **证据优先**：Finding 必须包含触发条件、实际影响、修改行定位和代码证据。
 9. **真实评测**：不得虚报未运行或未命中的 Benchmark 结果。
10. **中文工程可读性**：代码注释、docstring、运行日志、错误说明和面向用户的报告默认使用中文。
11. **Fake Mode First**：所有 Agent、Orchestrator 和前端必须以 Fake Model 为基线开发和测试。Fake Model 返回符合 Schema 的预定义输出，使全链路可以不依赖网络和 API Key 运行。真实 LLM 调用作为最终验证层。

## 3. 最终 Subagent 拓扑

系统只有三个 Subagent。

### 3.1 DefectAgent

负责模式匹配和证据驱动的缺陷：

- 静态缺陷：语法、类型、导入、依赖和明显未完成实现。
- 安全漏洞：注入、SSRF、路径穿越、越权、敏感数据泄漏、不安全反序列化和危险 API。
- 内存与资源问题：资源泄漏、无界集合、未等待异步任务、错误的缓存生命周期、竞态和死锁。
- 传统工具信号裁决：Semgrep 等工具结果只作为证据，不直接成为最终 Finding。

DefectAgent 只能输出候选 Finding，不得绕过 Verifier 发布结论。

### 3.2 IntentAgent

负责语义理解和意图对齐型缺陷：

- 业务逻辑：需求、测试和实现行为不一致。
- 普通逻辑：边界条件、条件组合、错误变量、状态转换和调用契约。
- 架构问题：模块依赖方向、跨层调用、公共接口破坏和跨文件行为不一致。

IntentAgent 使用固定流程：先总结作者意图，再总结实际行为变化，最后比较两者并检查边界、状态机、测试和架构约束。

### 3.3 VerifierAgent

Verifier 不主动寻找新问题，只验证候选 Finding：

1. 是否由当前 PR 引入或扩大。
2. 是否定位到修改行。
3. 触发输入和代码路径是否可达。
4. 是否存在上游校验、异常分支或框架默认保护。
5. 是否仅存在于测试、示例或不可执行代码。
6. 是否与其他 Finding 重复。
7. 严重度和置信度是否合理。
8. 证据是否足以发布给开发者。

Verifier 输出接受或拒绝结论，并可修正严重度、置信度和定位。

### 3.4 TeamLead 主 Agent

系统另设一个面向团队协作的 `TeamLeadAgent`。它是主 Agent，不计入三个 Subagent 数量，也不直接判断具体代码缺陷。

TeamLeadAgent 负责：

- 根据 PR diff、文件类型、风险标签和时间预算生成 `ReviewPlan`。
- 决定 ContextPack 如何分片以及启动多少专家实例。
- 并行启动 DefectAgent 和 IntentAgent。
- 将静态信号、上下文和候选 Finding 发布到共享 Evidence Blackboard。
- 路由 Agent 间的定向移交、Verifier 补证请求和超时降级。
- 观察剩余预算，要求 Agent 保存快照或提前收敛。
- 汇总覆盖范围、未完成检查和降级原因。

TeamLeadAgent 不负责：

- 不直接生成最终 Finding。
- 不覆盖 Verifier 的接受或拒绝结论。
- 不读取或转发其他 Agent 的隐藏思维链。
- 不允许 Agent 进行无结构、无预算的自由聊天。

TeamLeadAgent 的 Prompt 必须强调：并行优先、证据优先、预算优先、结构化消息优先。确定性 Orchestrator 仍负责真正的任务调度、队列、超时和持久化；主 Agent 只产生计划和路由决策，避免把系统可靠性建立在一次模型调用上。

**TeamLeadAgent 与 Orchestrator 职责边界：**

| 职责 | TeamLeadAgent | Orchestrator |
| --- | --- | --- |
| 生成 ReviewPlan | ✅ | ❌ |
| 决定语义分片策略 | ✅ | ❌ |
| 路由风险到对应专家角色 | ✅ | ❌ |
| 创建 asyncio.Task 并管理生命周期 | ❌ | ✅ |
| 执行阶段超时与全局 watchdog | ❌ | ✅ |
| Mailbox 消息投递与路由 | ❌ | ✅ |
| 发布 stage/agent PipelineEvent | ❌ | ✅ |
| 预算预警转发与快照指令 | ✅（决策） | ✅（执行） |
| 死信、取消与队列关闭 | ❌ | ✅ |
| 降级决策（跳过失败 Agent） | ❌ | ✅ |

### 3.5 流式 Agent Team

Agent Team 不采用 `Defect → Intent → Verifier` 串行链路，而采用流式并行拓扑：

```text
                       TeamLeadAgent
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
        DefectAgent                  IntentAgent
              │                           │
              ├──── 候选 / 证据 / 移交 ───┤
              ▼                           ▼
                 Evidence Blackboard
                       │       ▲
              候选事件 │       │ 补证请求
                       ▼       │
                   VerifierAgent
                       │
                       ▼
                  Final Findings
```

执行要求：

1. 初始 ContextPack 可用后，DefectAgent、IntentAgent 和可选静态工具同时启动。
2. Verifier watcher 不随专家同时启动，而是在第一个 `candidate_finding` 消息到达 Mailbox 时由 Orchestrator 唤醒。Verifier 的 120 秒预算从第一个候选到达时开始计时。
3. 若专家阶段（300 秒）结束仍无候选 Finding 产出，Verifier 不启动，审查结果标记为无发现问题。
4. 专家每产生一个候选就立即发布，Verifier 不等待全部专家结束。
5. Verifier 可向原专家发起一次定向补证请求。
6. 专家可以向另一专家发起结构化跨领域移交，但每个 ContextPack 最多两次。
7. 大 PR 可以为同一角色启动多个分片实例，但每个角色最多 3 个分片，角色种类不增加。
8. 所有消息进入持久化 Mailbox，并同步转化为 PipelineEvent。

### 3.6 Mailbox 与 Evidence Blackboard

每个运行拥有独立的 Mailbox。第一版使用进程内 `asyncio.Queue`，同时将消息追加保存到 `runs/{run_id}/mailbox.jsonl`。接口保持可替换，后续可以切换 Redis Streams，而不修改 Agent 实现。

统一消息外壳：

```python
class TeamMessage(BaseModel):
    id: str
    run_id: str
    sequence: int
    timestamp: datetime
    sender: str
    recipient: str
    kind: MessageKind
    correlation_id: str | None
    expires_at: datetime | None
    payload: dict[str, Any]
```

`MessageKind` 固定包含：

- `review_plan`
- `context_available`
- `static_signal`
- `candidate_finding`
- `handoff_request`
- `handoff_response`
- `verification_request`
- `evidence_response`
- `verdict`
- `agent_snapshot`
- `agent_completed`
- `agent_failed`
- `budget_warning`
- `cancel`

关键载荷：

```python
class HandoffRequest(BaseModel):
    source_agent: str
    target_agent: Literal["defect", "intent"]
    hypothesis: str
    file: str
    lines: list[int]
    requested_check: str
    evidence: list[CodeEvidence]


class VerificationRequest(BaseModel):
    finding_id: str
    target_agent: Literal["defect", "intent"]
    question: str
    required_evidence: list[str]
    deadline_seconds: int = 30


class EvidenceResponse(BaseModel):
    finding_id: str
    conclusion: Literal["supported", "withdrawn", "uncertain"]
    evidence: list[CodeEvidence]
    summary: str
```

Mailbox 规则：

- 每个 Agent 只有自己的收件队列和共享广播订阅，不得读取无关私信。
- 消息必须有唯一 ID、单调 sequence 和可选 correlation ID。
- 重复消息按 ID 幂等处理。
- 过期补证请求不得继续消耗模型预算。
- Agent 退出前必须发送 `agent_completed` 或 `agent_failed`。
- Orchestrator 负责死信、超时、取消和最终队列关闭。
- Blackboard 只保存结构化事实、证据和状态，不保存隐藏思维链。

## 4. 系统组件与数据流

```text
Vue 3 前端
    │ REST + SSE / Replay
FastAPI 服务
    │
Orchestrator
    │
PR Loader → Diff Parser → Context Builder
    │                         │
    │                  只读工具与静态信号
    │                         │
    ├──────── DefectAgent ────┤
    └──────── IntentAgent ────┘
                 │
          确定性去重模块
                 │
          VerifierAgent
                 │
          Report Builder
                 │
       JSON / Markdown / SSE
```

完整状态流转：

```text
created
  → loading_pr
  → parsing_diff
  → building_context
  → reviewing
  → deduplicating
  → verifying
  → generating_report
  → completed | partial | failed
```

## 5. 公共数据协议

公共协议必须最先实现并冻结。四名开发者不得分别维护同名异构模型。

### 5.1 ReviewRequest

```python
class ReviewRequest(BaseModel):
    pr_url: str | None = None
    repo_path: str | None = None
    base_ref: str | None = None
    head_ref: str | None = None
    replay_run_id: str | None = None
```

`pr_url`、本地仓库参数和 `replay_run_id` 三种模式互斥。

### 5.2 PRData 与 Diff

```python
class PRData(BaseModel):
    provider: Literal["github", "local"]
    repository: str
    title: str
    description: str
    base_sha: str
    head_sha: str
    author: str | None
    files: list[ChangedFile]
    raw_diff: str


class ChangedFile(BaseModel):
    path: str
    old_path: str | None
    status: Literal["added", "modified", "deleted", "renamed"]
    additions: int
    deletions: int
    hunks: list[DiffHunk]


class DiffHunk(BaseModel):
    id: str
    file: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    changed_lines: list[int]
    content: str
```

### 5.3 ContextPack

```python
class ContextPack(BaseModel):
    id: str
    repository: str
    base_sha: str
    head_sha: str
    pr_title: str
    pr_description: str
    files: list[str]
    diff_hunks: list[DiffHunk]
    enclosing_code: list[CodeEvidence]
    related_code: list[CodeEvidence]
    related_tests: list[CodeEvidence]
    project_docs: list[TextEvidence]
    git_history: list[TextEvidence]
    static_signals: list[StaticSignal]
    retrieval_notes: list[str]
    truncated: bool = False
```

第一版不依赖完整 Call Graph。Context Builder 通过修改符号、import、同目录文件、测试命名、代码搜索和 Git 历史生成足够上下文。单个 ContextPack 默认字符预算为 8000 字符，可通过配置调整。tree-sitter 不可用时，回退为纯文本正则符号提取。

### 5.4 Finding

```python
class Finding(BaseModel):
    id: str
    producer: Literal["defect", "intent"]
    category: Literal[
        "static",
        "business_logic",
        "logic",
        "memory",
        "security",
        "architecture",
        "reliability",
    ]
    severity: Literal["critical", "high", "medium", "low"]
    confidence: float
    file: str
    line_start: int
    line_end: int
    title: str
    description: str
    trigger_condition: str
    impact: str
    reasoning_summary: str
    suggestion: str | None
    evidence: list[CodeEvidence]
```

Finding 约束：

- `confidence` 必须在 0 到 1 之间。
- 至少包含一条代码证据。
- 至少一条证据来自修改文件。
- 定位必须与新增或修改行相交。
- `reasoning_summary` 是可公开的结论摘要，不记录或展示模型隐藏思维链。
- 单个 PR 最终发布的 Finding 上限为 8 条，超出部分按置信度截断。

### 5.5 Verdict 与 ReviewResult

```python
class Verdict(BaseModel):
    finding_id: str
    accepted: bool
    verdict: Literal[
        "confirmed",
        "likely",
        "insufficient_evidence",
        "false_positive",
        "duplicate",
        "not_introduced_by_pr",
        "not_on_changed_line",
        "style_only",
    ]
    confidence: float
    severity: Literal["critical", "high", "medium", "low"] | None
    reason: str
    final_finding: Finding | None


class ReviewResult(BaseModel):
    run_id: str
    status: Literal["completed", "partial", "failed"]
    repository: str
    base_sha: str
    head_sha: str
    findings: list[Finding]
    rejected_count: int
    coverage: list[str]
    warnings: list[str]
    started_at: datetime
    completed_at: datetime
    elapsed_seconds: float
```

## 6. 前后端事件协议

```python
class PipelineEvent(BaseModel):
    id: str
    run_id: str
    sequence: int
    timestamp: datetime
    type: EventType
    data: dict[str, Any]
```

固定事件：

- `review.started`
- `review.completed`
- `review.failed`
- `stage.started`
- `stage.completed`
- `stage.failed`
- `agent.started`
- `agent.tool`
- `agent.candidate`
- `agent.completed`
- `agent.failed`
- `verifier.started`
- `verifier.accepted`
- `verifier.rejected`
- `verifier.completed`
- `report.generated`

事件中只展示阶段、工具调用摘要、公开证据和结论，不展示模型隐藏思维链。

## 7. HTTP 与 SSE 接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/reviews` | 启动真实审查或 Replay |
| `GET` | `/api/reviews/{run_id}` | 查询运行状态和结果 |
| `GET` | `/api/reviews/{run_id}/events` | 获取实时 SSE 事件 |
| `GET` | `/api/reviews/{run_id}/report` | 获取 Markdown 或 JSON 报告 |
| `GET` | `/api/runs` | 查询历史运行 |
| `GET` | `/api/replays/{run_id}/events` | 按指定速度回放历史事件 |
| `GET` | `/api/benchmarks/latest` | 获取最近一次评测摘要 |

SSE 与 Replay 必须输出相同的 PipelineEvent，前端不得为两种模式维护两套状态逻辑。

所有 API 错误使用统一结构返回：

```python
class ErrorResponse(BaseModel):
    error_code: str       # "PR_NOT_FOUND" | "TIMEOUT" | "VALIDATION_ERROR" | "REPLAY_NOT_FOUND" | "INTERNAL_ERROR"
    detail: str           # 中文可读描述
    run_id: str | None    # 关联运行 ID
```

HTTP 状态码约定：`400` 校验错误、`404` 资源不存在、`408` 超时、`500` 内部错误。

## 8. 工具与知识来源

### 8.1 必须实现

- GitHub PR 元数据和 diff 获取。
- 本地 Git base/head diff。
- 仓库内文件范围读取。
- 基于 `rg` 或等价能力的代码搜索。
- Git log、show 和 blame。
- 修改符号周边代码获取。
- 相关测试搜索。
- README、架构文档、规范和配置检索。

### 8.2 尽量实现

- Semgrep 定向扫描修改文件。
- Python AST 或 tree-sitter 的轻量符号提取。
- GitHub Review Comment JSON 生成。

### 8.3 明确降级

- 不建设完整向量数据库。
- 不建设多语言完整 Call Graph。
- 不要求接入所有 Linter。
- 不要求 embedding 语义去重。
- 不要求自动发布 GitHub 评论。

知识库方案以仓库现有文档、测试、配置和 Git 历史为第一版知识源。README 中必须说明后续可在 PR 合并时增量更新符号索引、架构摘要和历史缺陷模式，但不得宣称未实现的离线系统已经可用。

### 8.4 Tool Registry 与权限

所有 Agent 工具通过统一 `ToolRegistry` 注册，工具元数据至少包含名称、中文说明、允许角色、超时、单次输出上限、是否需要外部程序和失败降级方式。

| 工具 | 允许角色 | 主要用途 | 默认限制 |
| --- | --- | --- | --- |
| `read_file_range` | 全部 | 读取代码证据 | 单次最多 300 行 |
| `search_code` | 全部 | 搜索符号和文本 | 最多 20 个结果 |
| `find_related_tests` | Defect、Intent | 查找相关测试 | 最多 10 个文件 |
| `search_project_docs` | Intent、TeamLead | 查找 README、设计和规范 | 最多 10 个片段 |
| `git_show` | 全部 | 查看提交修改 | 只读 |
| `git_history` | 全部 | 获取相关历史 | 最多 10 个提交 |
| `git_blame` | 全部 | 获取修改原因线索 | 单次最多 100 行 |
| `run_semgrep` | Defect | 定向扫描修改文件 | 默认 60 秒 |
| `get_diff_context` | 全部 | 获取目标 hunk 周边 | 单次最多 200 行 |
| `request_handoff` | Defect、Intent | 跨领域移交 | 每 Pack 最多 2 次 |
| `request_evidence` | Verifier | 请求定向补证 | 每 Finding 最多 1 次 |
| `submit_snapshot` | 全部 Agent | 保存当前结果 | 每个 Agent 至少一次 |

工具调用必须经过以下校验：仓库路径白名单、角色权限、剩余预算、参数 Schema、输出裁剪和敏感信息过滤。

### 8.5 Hooks

框架提供确定性的生命周期 Hooks，支持日志、事件、指标、预算和后续调优，不允许 Hook 修改模型结论本身。

必须实现：

- `before_run`：创建 run、记录版本、加载配置和 Prompt 哈希。
- `after_run`：写结果、覆盖率、耗时和降级摘要。
- `before_stage` / `after_stage` / `on_stage_error`：阶段事件和耗时。
- `before_agent` / `after_agent` / `on_agent_error`：Agent 状态和快照。
- `before_model_request` / `after_model_response`：用量、延迟和响应 Schema 状态；不得记录完整 Prompt。
- `before_tool` / `after_tool` / `on_tool_error`：权限、超时、输出大小和中文日志。
- `before_publish_message` / `after_receive_message`：Mailbox 指标和消息追踪。
- `before_accept_finding`：执行修改行、证据、置信度和敏感信息确定性校验。
- `on_budget_warning`：剩余 120 秒和 30 秒时要求 Agent 保存快照并收敛。

Hook 失败只能记录告警，不得遮蔽原始异常或阻塞主管道；安全校验 Hook 除外，安全校验失败必须拒绝相应工具调用或 Finding。

### 8.6 Agent Skills

这里的 Skill 是 ReviewCrew 内部可组合的审查方法模块，不是无约束 Prompt 文本。每个 Skill 使用 Markdown 加 YAML front matter 保存：

```yaml
name: trace-untrusted-input
version: 1.0.0
roles: [defect]
categories: [security]
required_tools: [search_code, read_file_range]
max_tool_calls: 4
```

每个 Skill 正文必须定义：适用条件、检查步骤、需要收集的证据、停止条件、常见误报和输出要求。

第一版 Skill 清单（MVP，共 12 个）：

- 共享（4）：`diff-first-review`、`evidence-standard`、`changed-line-localization`、`stop-when-insufficient`。
- Defect（2）：`static-breakage`、`trace-untrusted-input`。
- Intent（2）：`intent-vs-implementation`、`boundary-conditions`。
- Verifier（2）：`reachability-challenge`、`pr-attribution`。
- TeamLead（2）：`risk-routing`、`budget-allocation`。

以下 Skill 作为可选扩展，时间允许时实现：Defect 的 `authorization-ownership`、`resource-lifecycle`、`async-concurrency`、`unbounded-growth`；Intent 的 `state-machine`、`api-contract`、`cross-file-consistency`、`architecture-boundary`；Verifier 的 `upstream-protection`、`severity-calibration`、`duplicate-check`；TeamLead 的 `semantic-sharding`、`coverage-summary`。

`SkillRegistry` 根据角色、风险标签、语言、修改类型和剩余预算选择 Skill。Prompt 中必须记录启用的 Skill 名称和版本，运行结果中保存 Skill 列表，便于赛马比较。

### 8.7 Prompt 结构

每个 Agent Prompt 由以下部分组合，禁止复制成一个难以比较的超长字符串：

1. `shared/system.md`：角色边界、中文输出、证据标准、禁止隐藏思维链。
2. `team_lead.md`、`defect.md`、`intent.md`、`verifier.md`：角色目标和消息协议。
3. 动态 Skill：按本次风险选择的方法模块。
4. 当前 ReviewPlan、ContextPack、Mailbox 消息和剩余预算。
5. 严格结构化输出 Schema。

主 Agent Prompt 的关键指令：

- 默认并行启动可以独立工作的任务。
- 不等待完整上下文才启动专家，允许增量补充。
- 不直接裁决缺陷。
- 优先把假设路由给最适合的专家。
- 每次路由都设置预算和截止时间。
- 剩余预算不足时停止扩展，要求保存快照。

专家 Prompt 的关键指令：先形成可证伪假设，再调用工具收集证据；证据不足时撤回或输出 uncertain，不得为了数量制造 Finding。

Verifier Prompt 的关键指令：默认尝试推翻候选；若缺少关键证据，优先发一次定向补证请求，而不是直接赞同专家。

## 9. 时间预算与降级策略

| 阶段 | 时间上限 |
| --- | --- |
| PR 加载和 Diff 解析 | 30 秒 |
| Context 构建 | 90 秒 |
| 两专家并行审查 | 300 秒 |
| Verifier | 120 秒 |
| 报告生成 | 30 秒 |
| 全局 watchdog | 600 秒 |

降级规则：

- Semgrep 缺失、失败或超时：返回空信号并记录中文警告。
- tree-sitter 或 Python AST 不可用：回退为基于正则的符号提取，精度下降但 Context Builder 继续工作。
- Git 历史不可用：跳过历史上下文并记录中文警告。
- 单个专家失败：继续另一个专家和后续验证。
- Verifier 失败：状态标记为 `partial`，只输出高置信候选，并明确标注未经完整验证。
- LLM 结构化输出失败：携带中文校验错误最多重试两次。
- 全局超时：保存当前快照、事件和部分报告。
- 前端断线：后台审查继续，可通过状态接口恢复。

## 10. 前端设计

前端使用 Vue 3、TypeScript 和 Vite。首先保证功能和 Replay 稳定，再优化视觉效果。

### 10.1 审查启动页

- 输入 GitHub PR URL。
- 支持本地/开发模式和 Replay。
- 展示仓库、分支、文件数和启动错误。

### 10.2 实时审查页

- 展示加载 PR、解析 Diff、构建上下文、专家审查、验证和报告阶段。
- 展示 600 秒预算和已用时间。
- 展示三个 Agent 的等待、运行、完成、降级和失败状态。
- 展示工具调用摘要、候选数量和 Verifier 接受/拒绝动画。
- 不展示模型隐藏思维链。

### 10.3 结果页

- 按严重度、类别、文件筛选 Finding。
- 展示行号、触发条件、影响、证据、置信度和修复建议。
- 展示 Verifier 结论。
- 支持查看或下载 Markdown 报告。

### 10.4 评测页

- 展示五个仓库和实际运行数量。
- 展示成功命中数、成功提交链接、分类统计和平均耗时。
- 支持播放最佳历史运行 Replay。

## 11. 中文工程规范

本节为所有赛马实现的强制约束。

 1. Python、TypeScript 和 Vue 代码中的解释性注释使用中文。
 2. Python 模块、类、公开函数和复杂私有函数使用中文 docstring。
 3. TypeScript 的公共类型、Store、Composable 和复杂组件逻辑使用中文 TSDoc 或注释。
 4. 运行日志、警告、错误信息、CLI 提示、API 的用户可见错误和报告正文使用中文。
 5. 标识符、类名、函数名、字段名、协议枚举和 HTTP 路径继续使用英文，避免破坏生态兼容性。
 6. 日志不得输出 API Key、Authorization Header、完整 Prompt、完整模型私密推理或敏感仓库内容。
 7. 日志采用结构化字段，至少包含 `run_id`、阶段、Agent、耗时和结果状态。
 8. 注释解释设计意图、约束和非显然原因，不逐行翻译代码。
 9. 测试名称可以使用英文标识符，但测试 docstring、失败提示和 fixture 说明使用中文。
10. README、架构说明、评测报告和演示脚本全部使用中文。

示例：

```python
async def build_context(pr_data: PRData) -> list[ContextPack]:
    """围绕 PR 修改行构建受预算约束的审查上下文。"""
```

```python
logger.warning(
    "Semgrep 扫描超时，当前审查将跳过静态信号",
    extra={"run_id": run_id, "stage": "building_context"},
)
```

## 12. 目录结构

```text
reviewcrew/
├── pyproject.toml
├── README.md
├── reviewcrew/
│   ├── config.py
│   ├── schemas.py
│   ├── events.py
│   ├── cli.py
│   ├── llm/glm.py
│   ├── github/pr_loader.py
│   ├── diff/parser.py
│   ├── context/builder.py
│   ├── tools/{files,search,git,semgrep}.py
│   ├── agents/
│   │   ├── base.py
│   │   ├── defect.py
│   │   ├── intent.py
│   │   ├── verifier.py
│   │   └── prompts/
│   ├── pipeline/{orchestrator,dedupe,report}.py
│   └── server/{app,replay}.py
├── benchmark/{dataset,runner,judge,report}.py
├── tests/
└── web/
    ├── src/{api,stores,pages,components,fixtures}/
    └── package.json
```

允许实现者在不改变模块边界的前提下拆分文件，但公共协议名称、API 路径和事件类型必须保持一致。

## 13. 赛马实施方式

今晚四名开发者基于本设计分别进行尽可能完整的全栈实现，而不是按模块互相等待。每份实现都必须：

- 保持相同公共协议和 API。
- 同时包含后端、三个 Agent、前端基础能力、测试和 README。
- 使用 Fake Model、fixture 和 Replay 隔离外部依赖。
- 能够独立启动并演示主要流程。
- 对无法完成的能力提供显式降级，不留下静默空实现。
- 频繁提交 Git，每个可验收能力形成独立提交。

赛马评判维度：

 1. 能否从干净环境启动。
 2. 端到端流程是否完整。
 3. 公共接口是否符合本规范。
 4. 测试和异常降级是否可靠。
 5. 中文注释、docstring 和日志是否合规。
 6. 前端演示是否稳定。
 7. LLM 真实调用是否成功。
 8. Benchmark 实际命中效果。
 9. 单 PR 是否能在 600 秒内收敛。
10. 代码结构是否便于次日上午专项调优。

### 13.1 分支与版本保存

每名开发者使用自己的后缀，分支格式：

```text
feature-1.1.<iteration>-<owner>
```

示例：

- `feature-1.1.2-mw`
- `feature-1.1.2-sxf`
- `feature-1.1.2-ly`
- `feature-1.1.2-zq`

`owner` 由团队自行确定，不能多人共用同一后缀。`iteration` 在形成可复现的新基线时递增，不要求每个小提交都新建分支。

版本保存规则：

1. 当前稳定基线保留在原分支，不直接用实验覆盖。
2. 开始一轮可能显著改变 Prompt、编排或检索策略的实验前，从最近通过验证的提交创建新迭代分支。
3. 每个分支保存 `benchmark/results/ITERATION_LOG.md`，记录父版本、Prompt/Skill 哈希、配置、测试案例和指标。
4. 只将测试通过且指标更好、或明确修复阻断缺陷的版本候选合并到最终分支。
5. 不使用 `git reset --hard`、强推或覆盖他人分支。
6. 分支切换前必须提交或明确保留当前工作，禁止携带不相关脏文件参加比较。
7. 每个可演示版本保存对应 run ID、报告和 Replay；大型运行文件不进入 Git时，在迭代日志中记录其本地路径和生成命令。

### 13.2 迭代循环

Goal 和人工调优都必须重复以下循环，而不是实现一次就结束：

```text
建立可运行基线
  → 运行自动测试
  → 运行 Benchmark quick/指定案例
  → 将失败归因为 Retrieval / Reasoning / Verification / Localization / Runtime
  → 只修改对应层
  → 再次运行相同案例防止误判
  → 运行邻近案例检查回归
  → 保存指标、Prompt/Skill 哈希和 Git 版本
  → 有收益则保留，无收益则不合并
```

在北京时间允许的情况下持续迭代。满足基本功能只代表基线建立完成，不代表 Goal 完成。Goal 至少完成一轮“基线评测 → 修改 → 复测 → 保存版本”的闭环；若时间允许，应持续到连续两轮没有可验证收益或到达 11:30 冻结时间。

## 14. 次日上午调优分工

2026-07-30 09:00 至 12:00：

| 人员 | 工作线 |
| --- | --- |
| 开发者 1 | DefectAgent：静态、安全、内存、资源和 Semgrep 信号调优 |
| 开发者 2 | IntentAgent：业务逻辑、普通逻辑、架构和上下文调优 |
| 开发者 3 | VerifierAgent：反证、误报、严重度、去重和评测归因调优 |
| 开发者 4 | Vue 前端、真实 SSE、Replay、评测页面和演示体验调优 |

09:00 后原则上只允许修改对应 Agent 的 Prompt、检查清单、阈值、上下文选择和前端表现，不再破坏性修改公共协议和主管道。

每轮 Agent 调优必须记录：

- 仓库和目标提交。
- 目标漏洞描述。
- 是否命中。
- 误报数量。
- 总耗时。
- 本轮修改。
- 相比上一轮的变化。

只保留有评测收益或明确修复回归的调整。

## 15. 测试与验收

### 15.1 自动测试

- Schema 序列化和字段校验。
- Diff 文件状态、hunk 和修改行解析。
- ContextPack 构建、裁剪和路径限制。
- Fake Model 下三个 Agent 的结构化输出。
- Finding 修改行约束。
- 确定性去重。
- Verifier 接受和拒绝。
- 单个 Agent 失败和超时降级。
- 全局 watchdog。
- PipelineEvent 顺序和持久化。
- FastAPI 状态接口、SSE 和 Replay。
- 前端事件 Store 和生产构建。

### 15.2 真实冒烟

- LLM 完成一次结构化输出。
- GitHub PR 或本地 base/head 完成一次真实审查。
- 生成 JSON 和 Markdown 报告。
- 前端播放一次真实运行或对应 Replay。
- 至少对五个 Benchmark 仓库各运行一个选定样本。
- 保存成功命中的 PR 或提交链接。
- 验证至少一个完整 PR 在 600 秒内结束。

### 15.3 Greptile Benchmark 测评方法

测评基准以 [Greptile AI Code Review Benchmarks](https://www.greptile.com/benchmarks) 公布的方法和 Case Library 为准。该页面在 2025 年评测了 5 个代码审查工具，数据集包含 5 个不同语言的开源仓库、每个仓库 10 个真实缺陷，共 50 个案例。

基准仓库为：

| 语言 | 仓库 | 上游地址 |
| --- | --- | --- |
| Python | Sentry | `https://github.com/getsentry/sentry` |
| TypeScript | Cal.com | `https://github.com/calcom/cal.com` |
| Go | Grafana | `https://github.com/grafana/grafana` |
| Java | Keycloak | `https://github.com/keycloak/keycloak` |
| Ruby | Discourse | `https://github.com/discourse/discourse` |

Greptile 的原始方法具有以下约束：

1. 从每个仓库选择 1 个真实漏洞修复 PR（MVP 共 5 个案例），并追溯找到引入漏洞的提交。时间允许时补充更多案例。
2. 排除规模极大的修改和单文件修改，使案例更接近真实团队审查。
3. 为每个案例构造干净的测试 PR，使 PR 重新引入原始缺陷。
4. 被测工具可以访问完整仓库、PR diff 和基准分支。
5. 只有工具在行级结果中明确指出错误代码并解释实际影响，才算命中。
6. 只在摘要中提到风险、不定位错误行、只给风格建议或只报告无关问题，均不算命中目标漏洞。
7. 原榜单的 catch rate 只统计目标漏洞是否被发现；误报、风格建议和无关评论不改变该命中率。

#### 15.3.1 Fork 与测试 PR 准备

四名开发者共同使用同一套评测仓库和案例定义，不允许每份赛马实现自行改变目标答案。

1. 将上述 5 个上游仓库分别 Fork 到团队 GitHub 组织或统一账号。
2. 为每个 Benchmark 案例记录原始修复 PR、漏洞描述、严重度、漏洞引入提交和漏洞修复提交。
3. 确定 `base_sha`：漏洞引入前的基准提交。
4. 确定 `head_sha`：包含漏洞引入修改、但尚未修复的提交。
5. 在团队 Fork 中为案例建立独立的 base/head 分支，并创建新的测试 PR。
6. 核对测试 PR diff 确实重新引入目标漏洞，且不存在修复后的代码。
7. 保存测试 PR URL，作为系统输入和最终交付链接。

如果时间不足以在截止前重建全部 5 个 PR，必须优先保证：

- 5 个仓库均已 Fork。
- 每个仓库至少有一个经过核对、能够稳定运行的测试 PR。
- 所有声称”成功扫描”的链接都指向真实运行过的测试 PR。
- 未运行、重建失败或结果不确定的案例明确标记，不计入分母或命中数。

#### 15.3.2 数据集文件

评测案例统一保存在 `benchmark/dataset.yaml`：

```yaml
- id: sentry-01
  language: python
  upstream_repo: https://github.com/getsentry/sentry
  fork_repo: https://github.com/<team>/sentry-reviewcrew
  source_fix_pr: https://github.com/getsentry/sentry/pull/<number>
  test_pr: https://github.com/<team>/sentry-reviewcrew/pull/<number>
  base_sha: <漏洞引入前提交>
  head_sha: <包含漏洞的提交>
  introducing_commit: <漏洞引入提交>
  fixing_commit: <漏洞修复提交>
  title: <案例标题>
  bug_description: <已知目标漏洞描述>
  severity: high
  category: logic
  bug_locations:
    - path: src/example.py
      line_start: 120
      line_end: 126
  status: ready
```

`status` 使用以下枚举：

- `ready`：PR 和目标答案已核对，可以运行。
- `needs_review`：已经收集，但目标行或提交仍需人工核对。
- `unavailable`：仓库、提交或 PR 无法重建。

自动评测只能运行 `ready` 案例。

#### 15.3.3 执行命令

计划提供以下统一入口：

```powershell
# 快速评测：每个仓库优先抽取一个 ready 案例
python -m benchmark.runner --mode quick

# 指定单个案例，用于 Subagent 调优
python -m benchmark.runner --case sentry-01

# 从已有运行记录重新生成报告，不重复调用模型
python -m benchmark.report --latest
```

每次运行的原始结果保存到：

```text
benchmark/results/<timestamp>/
├── cases.jsonl
├── summary.json
├── summary.md
└── runs/
```

每个案例必须记录模型、Prompt 版本、Git 提交、开始时间、总耗时、候选 Finding、Verifier 结果、最终 Finding 和错误信息，保证调优结果可追溯。

#### 15.3.4 自动命中判定

`benchmark.judge` 采用三层判定：

1. **文件匹配**：Finding 的 `file` 必须与任一目标文件一致。
2. **位置匹配**：Finding 行区间必须与目标区间重叠；为兼容重建 PR 的轻微行号变化，可配置最多正负 10 行容差，但报告必须标出是否使用容差。
3. **语义匹配**：Finding 必须明确描述同一个错误机制和实际影响。仅文件、行号相同但描述的是另一个问题，不算命中。

语义判定优先采用人工核对。批量自动化时可以使用独立 LLM Judge，但 Judge 只能读取目标漏洞描述和最终 Finding，不得读取被测 Agent 的隐藏推理。自动 Judge 输出：

```python
class JudgeResult(BaseModel):
    case_id: str
    caught: bool
    matched_finding_id: str | None
    location_match: bool
    semantic_match: bool
    used_line_tolerance: bool
    reason: str
    needs_human_review: bool
```

以下结果不得判为命中：

- 只在报告摘要中泛泛提到风险。
- 没有定位到目标错误代码或附近修改行。
- 只提出测试不足、重构或风格建议。
- 描述了同一文件中的其他缺陷。
- Finding 被 Verifier 最终拒绝。
- 无法解释缺陷会产生什么实际影响。

#### 15.3.5 指标

与 Greptile 榜单直接对应的主指标：

```text
目标漏洞命中率 = 成功命中的 ready 案例数 / 实际完成运行的 ready 案例数
```

同时记录以下工程指标：

- 每个仓库的命中数和运行数。
- 每种语言和缺陷类别的命中率。
- Critical、High、Medium、Low 分级命中率。
- 单 PR 平均耗时、P50 和最大耗时。
- 超过 600 秒的案例数。
- 单 PR 最终 Finding 数量。
- 非目标 Finding 数量，作为内部误报观察值。
- Verifier 接受数、拒绝数和可能误杀数。
- 失败、降级和无法判定案例数。

原 Greptile 榜单不会因误报降低 catch rate，但 ReviewCrew 的内部报告仍必须统计非目标 Finding，避免通过大量泛化输出刷命中。

#### 15.3.6 成功链接与交付报告

最终 `docs/评测报告.md` 至少包含：

| 字段 | 说明 |
| --- | --- |
| 仓库与语言 | 例如 Sentry / Python |
| 测试 PR | 团队 Fork 中重新构造的 PR 链接 |
| 上游修复 PR | 用于核对真实漏洞来源 |
| 漏洞描述 | Benchmark 公布的目标问题 |
| 严重度与类别 | Benchmark 严重度和系统分类 |
| 是否命中 | 是、否或需要人工复核 |
| 命中 Finding | 文件、行号、标题和实际影响 |
| 审查耗时 | 秒 |
| 运行记录 | 对应 JSON、Markdown 或前端 Replay 标识 |

“成功扫描目标漏洞的 PR 提交链接”必须可点击访问，并能证明：

1. PR diff 中包含目标漏洞。
2. ReviewCrew 的最终结果定位到错误行。
3. ReviewCrew 解释了该错误造成的实际影响。
4. 结果未被 Verifier 拒绝。

评测报告必须明确标注实际运行案例数（MVP 目标为 5 个），禁止将小样本命中率表述成完整 Benchmark 成绩。时间允许时补充的案例单独列出并标注"扩展"。

### 15.4 11:30 冻结与 12:00 截止标准

- 后端自动测试通过。
- 前端生产构建通过。
- README 可用于安装、配置和启动。
- API Key 和敏感数据未进入 Git。
- 三个 Subagent 均在真实或受控模型环境运行。
- Verifier 能拒绝无效候选。
- 前端真实模式或 Replay 模式稳定。
- 评测报告包含真实运行结果和成功命中链接。
- 保存一条适合录制演示的稳定运行。

## 16. Git 提交规范

每完成一个可独立验收的能力就提交，通常每 30 至 60 分钟一次。建议提交序列：

```text
docs: 完善竞赛交付架构与赛马规范
feat: 定义审查领域模型与事件协议
chore: 初始化后端与前端工程
feat: 获取并解析拉取请求差异
feat: 构建以差异为中心的审查上下文
feat: 接入 LLM 与 Agent 运行时
feat: 实现缺陷与意图审查 Agent
feat: 实现候选问题验证与去重
feat: 实现审查编排和报告生成
feat: 提供审查接口与事件回放
feat: 实现 Vue 审查控制台
test: 覆盖端到端审查和降级流程
docs: 补充安装、评测与演示说明
```

提交前运行对应范围的测试。不得把 API Key、个人配置、运行缓存、大型仓库副本和无关 IDE 文件提交到仓库。

## 17. 演示方案

演示视频不超过三分钟：

1. 说明传统工具的上下文和逻辑理解短板。
2. 输入一个真实 PR 并启动审查。
3. 展示 DefectAgent 与 IntentAgent 并行工作。
4. 展示 Verifier 拒绝误报并保留有效 Finding。
5. 展示最终代码证据、触发条件、影响和建议。
6. 展示 Benchmark 成功命中链接、耗时和覆盖类型。
7. 总结 Diff 中心、上下文增强、传统工具信号和独立验证四项优势。

现场优先使用保存好的最佳真实运行 Replay，同时保留真实审查入口作为功能证明。若直播演示中模型调用失败或网络不稳定，立即切换为 Replay 模式，不中断演示流程。