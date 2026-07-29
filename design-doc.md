# AI 驱动智能代码审查系统 — 设计文档

> 代号：**ReviewCrew** · 版本 v0.1 · 2026-07-29

---

## 1. 项目概述

### 1.1 目标

构建一套以 **多 Agent 协作** 为核心架构的 AI Code Review 系统：

| 目标 | 指标 |
|---|---|
| 审查范围 | 聚焦 Git PR diff，按需扩展上下文，不做全量扫描 |
| 缺陷覆盖 | 静态缺陷 / 业务逻辑 / 逻辑缺陷 / 内存问题 / 安全漏洞 / 架构问题 |
| 模型 | GLM 系列 API（子 Agent 独立上下文） |
| 时效 | 单 PR 分析 ≤ 10 分钟，总开发时限 12 小时 |
| 评测 | Greptile Benchmark（5 仓库 × 10 个真实漏洞 PR） |

### 1.2 核心设计哲学

1. **Agent 推理为主，静态工具为辅** —— 逻辑类/业务类缺陷只能靠 LLM 推理，静态工具（Semgrep 等）作为低成本高置信度的"证据信号源"注入。
2. **离线重、在线轻** —— 一切能预计算的（符号索引、架构摘要、历史 bug 模式）全部离线完成，10 分钟额度只花在 PR 本身。
3. **两阶段"高召回 → 高精度"** —— 专家 Agent 放开手脚生成候选缺陷（高召回），Verifier Agent 对抗性验证（高精度），压制误报。
4. **评测驱动开发（Eval-Driven）** —— 先建自动评测 harness，所有迭代对着命中率/误报数调参。

### 1.3 明确不做

- ❌ CodeQL（建库时间不可控，与 10min 时限冲突；其覆盖面由 Semgrep + LLM 数据流推理替代）
- ❌ 全仓库扫描
- ❌ 重型编排框架（LangChain / LangGraph / CrewAI）—— 编排层保持纯 asyncio 固定 DAG
- ✅ Agent 内层采用 **Pydantic AI**（轻量、类型安全）—— 工具注册、结构化输出、校验重试交给框架，不自研 loop

---

## 2. 总体架构

```
┌─────────────────────────── 离线知识层（不占时限） ───────────────────────────┐
│  Repo Profile Builder                                                      │
│  ├── tree-sitter 全仓符号索引 + Call Graph                                  │
│  ├── 架构摘要（LLM 通读生成：模块地图 / 核心数据流 / 编码约定）                │
│  ├── 历史 Bug 模式库（挖掘 git log 中的 fix commit）                         │
│  └── 增量更新：merge 触发 / 定时任务                                         │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │ 读取
┌──────────────────────────────────▼──────────────────────────────────────────┐
│                        在线审查管道（≤10min）                                │
│                                                                             │
│  ① Diff 预处理 → ② 上下文组装 → ③ 专家 Agent 并行审查 → ④ 对抗验证 → ⑤ 报告 │
│                        ▲                  ▲                                  │
│                        │                  │ 工具调用                          │
│              ┌─────────┴────────┐  ┌──────┴───────────────┐                  │
│              │ 静态信号层        │  │ Agent 工具箱          │                  │
│              │ Semgrep/Linter/  │  │ read_file / find_refs │                 │
│              │ 依赖审计          │  │ call_graph / git_blame│                 │
│              └──────────────────┘  └──────────────────────┘                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 离线知识层（Repo Profile）

每个仓库预构建一份 `profile/`，包含：

### 3.1 符号索引与调用图
- **工具**：tree-sitter（全语言统一 AST）
- **产出**：`symbols.db`（SQLite）—— 函数/类/变量的定义位置、签名、引用关系
- **Call Graph**：函数级调用边，支持"给定变更函数 → 上下游 N 跳"查询

### 3.2 架构摘要（LLM 离线生成）
- 模块地图：目录 → 职责 → 依赖方向
- 核心数据流：请求生命周期、关键状态机
- 编码约定：错误处理风格、命名规范、并发模型
- 产出 `architecture.md`，在线阶段按需检索注入 Agent 上下文

### 3.3 历史 Bug 模式库
- 扫描 `git log --grep="fix\|bug"` 的 commit，LLM 归纳该仓库高频缺陷模式
- 产出 `bug_patterns.md`（如："该仓库多次出现锁未释放/边界条件遗漏"）
- 审查时注入专家 Agent，形成仓库定制化检查清单 → **直接回应题目"适配团队编码习惯"痛点**

### 3.4 知识库维护更新方案（题目要求项）
| 触发 | 动作 | 耗时 |
|---|---|---|
| PR merge（webhook/git hook） | 增量更新符号索引（仅变更文件重新解析） | 秒级 |
| 每日定时 | 增量刷新架构摘要（仅变更模块） | 分钟级 |
| 每周定时 | 重挖历史 bug 模式 | 分钟级 |
| 新仓库接入 | 全量构建 Profile | 一次性 |

---

## 4. 在线审查管道（五阶段）

### ① Diff 预处理（目标 <10s）
- 解析 unified diff → hunk 级结构化对象（文件、行号区间、变更类型）
- 噪音过滤：lockfile、生成代码、纯格式化变更、二进制
- 按"文件语义聚类"分组（同模块 hunk 归组），供后续并行分片

### ② 上下文组装（目标 <60s）
为每个变更符号构建 **Context Pack**：

```python
from pydantic import BaseModel, Field

class Hunk(BaseModel):
    """单个 diff hunk"""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]  # 带前缀 ' '/'+'/'-' 的行

class FileDiff(BaseModel):
    """单文件 diff"""
    path: str
    change_type: Literal["add", "modify", "delete", "rename"]
    old_path: str | None = None  # rename 时旧路径
    hunks: list[Hunk]

class Signal(BaseModel):
    """静态信号（Semgrep/linter/deps）"""
    provider: str  # "semgrep" / "ruff" / "osv"
    rule_id: str
    file: str
    line: int
    message: str
    severity: Literal["error", "warning", "info"]

class ContextPack(BaseModel):
    """单个审查上下文包，喂给一个 Agent 实例"""
    pack_id: str
    
    # 变更本体
    diff_hunks: list[FileDiff]
    
    # 代码上下文
    enclosing_code: dict[str, str]  # {file: 完整函数/类代码}
    callers: dict[str, list[str]]   # {func: [调用者代码片段]}
    callees: dict[str, list[str]]   # {func: [被调代码片段]}
    
    # 仓库知识
    arch_summary: str = Field(max_length=2048, description="相关模块架构摘要片段")
    bug_patterns: str = Field(max_length=1024, description="该仓库历史缺陷模式")
    
    # 意图信号（与 diff 分离呈现，让 Agent 找偏差）
    intent: str = Field(description="PR title/description + issue + 测试变更摘要")
    
    # 静态信号
    static_signals: list[Signal]
    
    # token 预算：tiktoken 估算 ≤32K
```

**关键点**：
- `intent` 与 `diff` 分离呈现 —— 让 Agent 找"作者想做的"与"实际做的"之间的偏差，这是业务逻辑缺陷的主要来源
- 测试断言的变更是意图金矿，单独标注
- 上下文预算控制：每个 ContextPack 用 tiktoken 估算 ≤ 32K tokens，超出按"离 diff 行距离"由远及近裁剪 callers/callees

### ③ 专家 Agent 并行审查（目标 <5min）

> **架构决策**：采用 **2 专家 + 1 Verifier 共 3 个 Agent**（详见 `agent-topology.md`），
> 用"推理模式"而非"缺陷类型"拆分，避免上下文重叠导致的成本浪费。

两个专家 Agent **独立上下文、并行执行**：

| Agent | 覆盖缺陷类型 | 推理模式 | 检查清单要点 |
|---|---|---|---|
| **DefectAgent** | 安全漏洞 / 内存问题 / 静态缺陷 | 模式匹配型 | 分节 checklist（安全 → 内存 → 静态）：注入、taint 流、资源生命周期、裁决静态信号真伪 |
| **IntentAgent** | 业务逻辑 / 逻辑缺陷 / 架构问题 | 语义理解型 | 三步固定流程：总结意图 → 总结实际变更 → diff 两者找偏差 → 过边界/状态机/依赖方向清单 |

**Agent 循环**（Pydantic AI 基座，封装层 ≤150 行）：
```python
# 每个 Agent 最多 12 轮（从原 4×8 调整为 2×12，更深而非更宽）
loop (max 12 turns):
  LLM(system_prompt + context_pack + tool_results) 
  → 调用工具（read_file / find_references / get_callers / git_blame / run_semgrep_rule）
  OR 调用 submit_snapshot(findings)  # 每 4 轮强制快照
  OR 输出最终结构化 findings
```

**Finding Schema（完整定义）**：
```python
from typing import Literal
from pydantic import BaseModel, Field

class Finding(BaseModel):
    """单条缺陷发现，由专家 Agent 输出，Verifier 打分"""
    category: Literal["logic", "security", "memory", "architecture", "static"]
    severity: Literal["critical", "high", "medium", "low"]
    confidence: float = Field(ge=0.0, le=1.0, description="初始由专家给出，Verifier 重打分")
    
    file: str = Field(description="仓库相对路径")
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    
    title: str = Field(max_length=120, description="一句话缺陷摘要")
    reasoning: str = Field(description="完整推理过程，含证据引用")
    trigger_path: str = Field(description="触发条件/复现步骤/调用链")
    suggestion: str = Field(description="具体修复建议，最好附代码片段")
    
    # Verifier 填充字段
    verdict: Literal["keep", "reject"] | None = None
    verdict_reason: str | None = None
```

### ④ 对抗验证 Verifier（目标 <2min）——压误报的命门

**去重合并阶段**：
```python
def dedupe(findings: list[Finding]) -> list[Finding]:
    """
    1. 同文件行区间重叠（±3 行容差）→ 合并取高 confidence
    2. 跨文件语义近似 → embedding 余弦 >0.85 合并
    """
```

**对抗验证阶段**：
每个 finding 交给 VerifierAgent **反向质疑四问**：
  1. 触发路径是否真实可达？（可调工具重读代码验证）
  2. 是否被别处的校验/防御代码兜住了？
  3. 是否是测试代码/示例代码的误判？
  4. severity 是否虚高？

VerifierAgent 输出：
```python
class Verdict(BaseModel):
    finding_id: str
    verdict: Literal["keep", "reject"]
    reason: str
    confidence_adjusted: float  # 重打分后的置信度
```

**门限控制**：
- `confidence_adjusted < 0.6` 直接丢弃
- 按 `severity_weight × confidence_adjusted` 排序
- 截断取前 **8 条**（benchmark 每个 PR 只埋 1 个目标漏洞，宁精勿滥）

### ⑤ 报告生成（目标 <30s）
- Markdown 报告 + GitHub PR Review Comment 格式（行级锚定）
- 包含：缺陷摘要表、每条 finding 的推理/触发路径/修复建议、审查覆盖说明

### 时间预算总表

| 阶段 | 预算 | 说明 |
|---|---|---|
| 预处理 | 10s | 纯本地计算 |
| 上下文组装 | 60s | 索引查询 + Semgrep 并行跑 |
| 专家审查 | 5min | **2 Agent 并行（DefectAgent/IntentAgent），单 Agent 12 轮内** |
| 对抗验证 | 2min | findings 并行验证 |
| 报告 | 30s | 单次 LLM 调用 |
| **合计** | **~8.5min** | 预留 1.5min buffer |

超时保护：全局 watchdog，任一 Agent 超预算强制收敛输出当前快照。

**架构调整说明**：从原 4 Agent × 8 轮调整为 2 Agent × 12 轮，token 成本降低 ~40%，推理深度增加。

---

## 5. 静态信号层

抽象为 `SignalProvider` 接口，即插即用：

```python
from abc import ABC, abstractmethod

class SignalProvider(ABC):
    """静态信号提供者基类"""
    @abstractmethod
    async def scan(self, repo_path: Path, files: list[str]) -> list[Signal]:
        """
        扫描指定文件，返回信号列表
        - 超时 60s 返回空列表（不抛异常阻塞管道）
        - 单 provider 失败只记日志
        """
```

| Provider | 作用 | 实现 | 耗时 |
|---|---|---|---|
| **SemgrepProvider** | 安全规则 + 通用 bug 模式 | `semgrep --config auto --json <files>` | ~10-30s |
| **LinterProvider** | 语言 linter | go vet / eslint / clippy / ruff 按语言路由 | ~10s |
| **DepsProvider** | 依赖审计 | lockfile diff → osv.dev batch API | ~5s |

**失败语义**：单 provider 异常/超时 → 返回空列表 + 日志，绝不抛出阻塞管道。

信号结果对齐到 diff 行号后注入 ContextPack —— **Agent 负责裁决信号真伪**，而不是直接透传（这就是比传统工具误报低的原因）。

---

## 6. 模型与 Agent 工程

### 6.1 模型配置
```python
from pydantic_ai.models import OpenAIModel

def build_glm_model() -> OpenAIModel:
    """构建 GLM 模型客户端"""
    return OpenAIModel(
        model="glm-4-plus",  # 或 glm-5
        base_url="https://open.bigmodel.cn/api/paas/v4/",  # GLM OpenAI 兼容端点
        api_key=os.getenv("GLM_API_KEY"),
        temperature=0.2,
        http_client=httpx.AsyncClient(
            timeout=120.0,
            transport=RetryTransport(retries=3, backoff=2.0)  # 429/5xx 指数退避
        )
    )
```

### 6.2 Agent 基座封装
```python
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings, UsageLimits

class ReviewAgent:
    """专家 Agent 基类，封装 pydantic-ai 循环"""
    def __init__(self, role: str, system_prompt: str):
        self.agent = Agent(
            model=build_glm_model(),
            output_type=AgentFindings,  # 结构化输出，校验失败自动 ModelRetry
            system_prompt=system_prompt,
            settings=ModelSettings(
                usage_limits=UsageLimits(request_limit=12)  # 12 轮上限
            )
        )
        # 注册工具
        self._register_tools()
    
    async def run(self, pack: ContextPack, budget: Budget) -> list[Finding]:
        """执行审查循环，每 4 轮调用 submit_snapshot"""
        # 封装层 ≤150 行，处理：
        # - 快照机制
        # - 事件流透传（thought/tool → EventLogger）
        # - 超时/超轮次兜底
```

### 6.3 事件流（可观测性 + 前端数据源）
```python
from typing import Literal
from pydantic import BaseModel

class PipelineEvent(BaseModel):
    """结构化事件，全程落盘 runs/<run_id>/events.jsonl，供前端 SSE 和 replay"""
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
    finding: Finding | None = None
    
    # type=verdict
    verdict: Verdict | None = None
    
    # type=report
    markdown: str | None = None

class EventLogger:
    """事件日志器，写 JSONL + 推 SSE"""
    def emit(self, event: PipelineEvent) -> None:
        # 落盘 + 推送到前端 SSE 连接
```

### 6.4 上下文策略与并发
- **子 Agent 独立上下文**：避免注意力稀释，Orchestrator 只收结构化 JSON 汇总
- **并发**：`asyncio.gather([defect.run(...), intent.run(...)])` + 信号量控制 API qps
- **可靠性**：单 Agent 失败不阻塞整体，降级输出（返回部分 findings）

---

## 7. 评测方案（最高优先级，先于主管道开发）

### 7.1 自动评测 Harness
```
benchmark/
  dataset.yaml        # 5 仓库 × 10 PR：repo, pr_url, bug_commit, 目标漏洞描述, 目标文件:行
  run_eval.py         # 批量跑 50 个 PR → 收集 findings
  judge.py            # 自动判定是否命中目标漏洞（文件+行区间匹配 → LLM 语义比对兜底）
  report.py           # 输出：命中率 / 平均误报数 / 平均耗时 / 分类命中矩阵
```

### 7.2 核心指标
| 指标 | 目标 |
|---|---|
| 目标漏洞命中率 | ≥ 60%（迭代目标 70%+） |
| 单 PR 平均报告数 | ≤ 8 条 |
| 单 PR 平均耗时 | ≤ 8min |

### 7.3 迭代流程
改 prompt/策略 → `python run_eval.py --quick`（抽样 10 PR）→ 看分数 → 全量验证。
**所有优化必须有分数支撑，拒绝玄学调参。**

---

## 8. 技术选型与项目结构

- **语言**：Python 3.12 + asyncio
- **索引**：tree-sitter + SQLite
- **UI**：Vue3 + Vite（演示用，展示 Agent 实时思考流 via WebSocket/SSE）
- **接口**：CLI（`review --pr <url>`）+ FastAPI（供 UI 调用）

```
reviewcrew/
├── profile/            # 离线知识层
│   ├── indexer.py      # tree-sitter 符号索引 + call graph
│   ├── summarizer.py   # 架构摘要生成
│   └── bug_miner.py    # 历史 bug 模式挖掘
├── pipeline/
│   ├── diff_parser.py
│   ├── context.py      # ContextPack 组装
│   ├── orchestrator.py # 并行调度 + watchdog
│   └── report.py
├── agents/
│   ├── base.py         # Agent loop + 工具协议
│   ├── security.py / logic.py / memory.py / arch.py
│   └── verifier.py
├── signals/
│   ├── base.py         # SignalProvider 接口
│   ├── semgrep.py / linters.py / deps.py
├── tools/              # Agent 可调用工具
│   ├── code_reader.py / references.py / blame.py
├── llm/
│   └── glm.py          # GLM client（重试/JSON mode/日志）
├── benchmark/          # 评测 harness（见 §7）
├── web/                # Vue3 演示 UI
├── cli.py
└── README.md
```

---

## 9. 与传统工具（SonarQube）的差异化叙事（用于演示材料）

| 传统工具痛点 | 本系统对策 |
|---|---|
| 规则滞后、新语言盲区 | LLM 推理不依赖规则库，tree-sitter 覆盖全语言 |
| 无法理解深层逻辑 | LogicAgent 做意图-实现偏差分析 + call graph 跨文件推理 |
| 误报率高 | Verifier 对抗验证 + 置信度门限 + 输出条数上限 |
| 不适配团队习惯 | 离线挖掘仓库专属 bug 模式与编码约定，定制化检查清单 |
| 缺乏上下文关联 | PR 描述/issue/测试变更作为业务意图信号注入 |

---

## 10. 里程碑（12 小时压缩版）

| 阶段 | 时间 | 内容 | 产出 |
|---|---|---|---|
| M1 | 0-2h | 项目骨架 + GLM client + 简易评测 harness（1-2 仓库 × 3-5 PR） | `cli.py` + `llm/glm.py` + 跑通 baseline |
| M2 | 2-5h | 核心管道：diff 解析 → 上下文组装 → 2 专家 Agent（Security + Logic）并行 → 报告 | 端到端可跑，第一批分数 |
| M3 | 5-8h | Verifier 对抗验证 + 输出控制 + 时限调优 + Memory/Arch Agent（如有余力） | 误报数下降，分数提升 |
| M4 | 8-11h | Web UI（Vue3 最小可用版：提交 PR URL → 看审查结果 + Agent 思考流） | 可演示的 UI |
| M5 | 11-12h | README + 评测报告 + 录屏 + 最终提交 | 交付物 |

### 10.1 12h 范围裁切

| 原计划 | 12h 策略 |
|---|---|
| 5 仓库 × 50 PR benchmark | 1-2 仓库 × 3-5 PR 快速验证，保证评测流程跑通 |
| 离线 Profile（tree-sitter + 架构摘要 + bug 挖掘） | **砍掉**：上下文组装阶段直接读文件 + git blame，不做预索引 |
| 4 专家 Agent | 优先 Security + Logic；Memory + Arch 作为 stretch goal |
| 完整 Web UI（实时 SSE + 回放） | 最小可用版：输入 PR URL → 轮询/SSE 展示结果 |
| Semgrep/linter 信号层 | **砍掉**：纯 Agent 推理，12h 内集成外部工具风险太高 |
| 历史 bug 模式挖掘 | **砍掉**：无离线阶段，无法实现 |

---

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| **12h 时间硬约束** | 严格按 §10.1 范围裁切执行；每个阶段到期强制收敛，不恋战；砍掉离线层/信号层降低复杂度 |
| GLM 长上下文注意力稀释 | 子 Agent 独立上下文 + 32K 预算裁剪 |
| API 限流导致超时 | 并发信号量 + watchdog 强制收敛 + 结果缓存 |
| 逻辑类漏洞命中率低 | 意图信号强化 + 变更前后语义对比 + 针对 miss 案例专项归因 |
| Semgrep 对某语言弱 | ~~SignalProvider 可插拔~~ 12h 版已砍掉信号层，纯 Agent 推理 |
| 评测判定有歧义 | judge 用"行区间匹配 → LLM 语义比对"两级判定，人工抽检校准 |
| 无离线索引导致上下文不足 | Agent 工具箱（read_file/git_blame）按需拉取，代价是多 1-2 轮工具调用 |
