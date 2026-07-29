# ReviewCrew 竞赛交付设计

> 日期：2026-07-29
>
> 截止时间：2026-07-30 14:00
>
> 代码冻结时间：2026-07-30 12:00
>
> 实施方式：四名开发者基于同一份规范独立赛马，次日上午合并优势并专项调优。

## 1. 目标与验收范围

开发一套以 Agent 为核心的 AI Code Review 系统，围绕 Git Pull Request 的差异内容开展精准审查，并按需补充与修改代码直接相关的上下文。

截止 2026-07-30 12:00，系统必须具备以下能力：

1. 输入 GitHub PR URL，或输入本地仓库、基准提交和目标提交。
2. 只分析 PR diff、修改符号及相关上下文，不进行无目标的全仓 LLM 扫描。
3. 使用 GLM 5.2 完成代码理解、缺陷发现和结果验证。
4. 覆盖静态缺陷、业务逻辑、逻辑缺陷、内存与资源问题、安全漏洞和架构问题。
5. 使用两个专家 Subagent 生成候选缺陷，使用一个独立 Verifier Subagent 过滤误报。
6. 单个 PR 的全流程由 600 秒全局 watchdog 约束。
7. 输出结构化 JSON、Markdown 报告和适合前端展示的事件流。
8. 提供 Vue 3 前端，展示审查进度、Agent 状态、Finding、Verifier 结论和评测结果。
9. 支持历史运行 Replay，保证演示不依赖现场模型和网络稳定性。
10. 提供可运行源码、README、评测报告、成功命中链接和不超过三分钟的演示视频。

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

第一版不依赖完整 Call Graph。Context Builder 通过修改符号、import、同目录文件、测试命名、代码搜索和 Git 历史生成足够上下文。

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
|---|---|---|
| `POST` | `/api/reviews` | 启动真实审查或 Replay |
| `GET` | `/api/reviews/{run_id}` | 查询运行状态和结果 |
| `GET` | `/api/reviews/{run_id}/events` | 获取实时 SSE 事件 |
| `GET` | `/api/reviews/{run_id}/report` | 获取 Markdown 或 JSON 报告 |
| `GET` | `/api/runs` | 查询历史运行 |
| `GET` | `/api/replays/{run_id}/events` | 按指定速度回放历史事件 |
| `GET` | `/api/benchmarks/latest` | 获取最近一次评测摘要 |

SSE 与 Replay 必须输出相同的 PipelineEvent，前端不得为两种模式维护两套状态逻辑。

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

## 9. 时间预算与降级策略

| 阶段 | 时间上限 |
|---|---:|
| PR 加载和 Diff 解析 | 30 秒 |
| Context 构建 | 90 秒 |
| 两专家并行审查 | 300 秒 |
| Verifier | 120 秒 |
| 报告生成 | 30 秒 |
| 全局 watchdog | 600 秒 |

降级规则：

- Semgrep 缺失、失败或超时：返回空信号并记录中文警告。
- Git 历史不可用：跳过历史上下文并记录中文警告。
- 单个专家失败：继续另一个专家和后续验证。
- Verifier 失败：状态标记为 `partial`，只输出高置信候选，并明确标注未经完整验证。
- GLM 结构化输出失败：携带中文校验错误最多重试两次。
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
7. GLM 5.2 真实调用是否成功。
8. Benchmark 实际命中效果。
9. 单 PR 是否能在 600 秒内收敛。
10. 代码结构是否便于次日上午专项调优。

## 14. 次日上午调优分工

2026-07-30 09:00 至 12:00：

| 人员 | 工作线 |
|---|---|
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

- GLM 5.2 完成一次结构化输出。
- GitHub PR 或本地 base/head 完成一次真实审查。
- 生成 JSON 和 Markdown 报告。
- 前端播放一次真实运行或对应 Replay。
- 至少对五个 Benchmark 仓库各运行一个选定样本。
- 保存成功命中的 PR 或提交链接。
- 验证至少一个完整 PR 在 600 秒内结束。

### 15.3 12:00 冻结标准

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
feat: 接入 GLM 5.2 与 Agent 运行时
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

现场优先使用保存好的最佳真实运行 Replay，同时保留真实审查入口作为功能证明。
