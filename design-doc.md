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
```
ContextPack {
  diff_hunks:        变更本体（带精确行号）
  enclosing_code:    变更所在完整函数/类
  callers/callees:   Call Graph 上下游 1-2 跳的代码
  arch_summary:      相关模块的架构摘要片段
  bug_patterns:      该仓库历史缺陷模式
  intent:            PR title/description + 关联 issue + 测试文件变更
  static_signals:    Semgrep/linter 命中结果（file:line 对齐到 diff）
}
```
**关键点**：
- `intent` 与 `diff` 分离呈现 —— 让 Agent 找"作者想做的"与"实际做的"之间的偏差，这是业务逻辑缺陷的主要来源
- 测试断言的变更是意图金矿，单独标注
- 上下文预算控制：每个 Agent 输入 ≤ 32K tokens，超出按"离 diff 距离"裁剪

### ③ 专家 Agent 并行审查（目标 <5min）

四个专家 Agent **独立上下文、并行执行**，各自持有差异化的系统提示与检查清单：

| Agent | 覆盖缺陷类型 | 检查清单要点 |
|---|---|---|
| **SecurityAgent** | 安全漏洞 | 注入（SQL/命令/路径）、SSRF、反序列化、认证/越权、密钥泄漏、taint 流推理（source→sink 沿 call graph 人工追踪） |
| **LogicAgent** | 业务逻辑 + 逻辑缺陷 | 意图-实现偏差、边界条件、off-by-one、条件反转、状态机漏转移、并发竞态、错误处理遗漏、变更前后语义对比 |
| **MemoryAgent** | 内存/资源问题 | 泄漏（连接/句柄/goroutine）、use-after-free、双重释放、无界增长（缓存/队列）、大对象拷贝 |
| **ArchAgent** | 架构问题 + 静态缺陷 | 循环依赖、层次穿透、接口破坏性变更、依赖缺失/版本冲突、公共 API 兼容性 |

**Agent 循环**（Pydantic AI 基座，封装层 ~100 行）：
```
loop (max 8 turns):
  LLM(system_prompt + context_pack + tool_results) 
  → 要么调用工具（read_file / find_references / get_callers / git_blame / run_semgrep_rule）
  → 要么输出结构化 findings JSON
```

**Findings Schema**：
```json
{
  "category": "logic|security|memory|architecture|static",
  "severity": "critical|high|medium|low",
  "confidence": 0.0-1.0,
  "file": "path", "line_start": n, "line_end": n,
  "title": "一句话", 
  "reasoning": "推理过程",
  "trigger_path": "触发条件/复现路径",
  "suggestion": "修复建议"
}
```

### ④ 对抗验证 Verifier（目标 <2min）——压误报的命门

- 汇总去重所有候选 findings（同文件同行区间 + 语义相似合并）
- 每个 finding 交给 VerifierAgent **反向质疑**：
  1. 触发路径是否真实可达？（可调工具重读代码验证）
  2. 是否被别处的校验/防御代码兜住了？
  3. 是否是测试代码/示例代码的误判？
  4. 置信度重打分，`confidence < 0.6` 直接丢弃
- 输出上限控制：单 PR 最多报 **8 条**，按 severity × confidence 排序取头部
  （benchmark 每个 PR 只埋 1 个目标漏洞，宁精勿滥）

### ⑤ 报告生成（目标 <30s）
- Markdown 报告 + GitHub PR Review Comment 格式（行级锚定）
- 包含：缺陷摘要表、每条 finding 的推理/触发路径/修复建议、审查覆盖说明

### 时间预算总表

| 阶段 | 预算 | 说明 |
|---|---|---|
| 预处理 | 10s | 纯本地计算 |
| 上下文组装 | 60s | 索引查询 + Semgrep 并行跑 |
| 专家审查 | 5min | 4 Agent 并行，单 Agent 8 轮内 |
| 对抗验证 | 2min | findings 并行验证 |
| 报告 | 30s | 单次 LLM 调用 |
| **合计** | **~8.5min** | 预留 1.5min buffer |

超时保护：全局 watchdog，任一 Agent 超预算强制收敛输出当前结果。

---

## 5. 静态信号层

抽象为 `SignalProvider` 接口，即插即用：

| Provider | 作用 | 耗时 |
|---|---|---|
| **Semgrep** | 安全规则 + 通用 bug 模式，diff 文件定向扫描 | ~10-30s |
| 语言 Linter | go vet / eslint / clippy / ruff 等按语言启用 | ~10s |
| 依赖审计 | lockfile diff → 已知 CVE 检查（osv.dev API） | ~5s |

信号结果对齐到 diff 行号后注入 ContextPack —— **Agent 负责裁决信号真伪**，而不是直接透传（这就是比传统工具误报低的原因）。

---

## 6. 模型与 Agent 工程

- **模型**：GLM API（对齐 GLM 4.5+/5.x 能力），温度 0.2，经 OpenAI 兼容端点接入
- **Agent 基座**：Pydantic AI —— `@agent.tool` 注册工具、`output_type` 结构化输出（直接绑 Finding schema）、校验失败自动 `ModelRetry`、`UsageLimits` 控轮次；自带 `TestModel/FunctionModel`，Agent 逻辑可离线 TDD
- **上下文策略**：子 Agent 独立上下文（避免注意力稀释），Orchestrator 只收结构化 JSON 汇总
- **并发**：`asyncio` + 信号量控制 API 并发数
- **可靠性**：JSON 解析失败自动重试（带错误反馈）；单 Agent 失败不阻塞整体，降级输出
- **可观测**：全程结构化日志（每轮 prompt/response/工具调用落盘），便于 debug 与演示回放

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
