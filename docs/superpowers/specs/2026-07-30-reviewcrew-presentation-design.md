# ReviewCrew 十分钟技术展示 PPT 设计

> 日期：2026-07-30  
> 场景：竞赛技术展示与现场答辩  
> 时长：10 分钟正文，附录用于问答  
> 画幅：16:9

## 1. 展示目标

本次展示需要让评委在十分钟内形成四个明确认知：

1. ReviewCrew 不是把一次代码审查拆成串行模型调用，而是一个由确定性 Orchestrator 驱动的流式 Agent Team。
2. 系统围绕 PR diff 和修改行按需补充上下文，避免无目标的全仓 LLM 分析。
3. 专家负责高召回发现，Verifier 负责寻找反证，最终只发布带定位、触发条件、实际影响和代码证据的 Finding。
4. 系统具备可演示、可回放、可降级和可审计的工程交付能力，同时不虚构尚未完成的真实 Benchmark 成绩。

## 2. 叙事策略

采用“产品价值与技术架构混合型”叙事：

```text
问题与目标
  → 核心审查范式
  → 系统总体架构
  → Diff 上下文与流式 Agent Team
  → 协作、工具和可靠性机制
  → 真实产品演示
  → Benchmark 方法与当前边界
  → 竞争优势与总结
```

不采用纯产品故事型，因为无法充分解释 Agent、Mailbox、Verifier 和确定性编排；不采用纯架构型，因为前几分钟缺少用户价值和比赛记忆点。

## 3. 正文页序与时间分配

### 第 1 页：封面（0:00–0:25）

- 标题：ReviewCrew
- 副标题：流式多 Agent 智能代码审查系统
- 核心句：让每一行改动都经得起独立验证
- 视觉：深色背景、Diff 光带或代码纹理，不堆叠功能列表。

### 第 2 页：传统代码审查的缺口（0:25–1:10）

- 规则扫描难以理解业务意图与跨文件逻辑。
- 单模型审查容易产生缺少证据的泛化评论。
- 全仓扫描成本高、噪声大，难满足单 PR 十分钟约束。
- 结论：真正困难的不是“发现更多”，而是确认问题由本次修改引入、能够触发并具有实际影响。

### 第 3 页：核心审查范式（1:10–1:55）

- 高召回发现：DefectAgent 与 IntentAgent 并行寻找候选。
- 独立反证：Verifier 检查 PR 归因、可达性、上游保护、重复和严重度。
- 证据化发布：最终 Finding 必须包含定位、触发、影响、证据和建议。
- 一句话公式：`Diff 中心 + 并行专家 + 独立验证 + 结构化证据`。

### 第 4 页：系统总体架构（1:55–3:10）

- 输入层：GitHub PR 或本地 base/head。
- 上下文层：PR Loader、Diff Parser、Context Builder、可选静态信号。
- 智能体层：TeamLead、Defect、Intent、Verifier watcher。
- 协作层：Mailbox 与 Evidence Blackboard。
- 服务层：FastAPI、REST、SSE、Replay。
- 展示与产物：Vue 3、JSON、中文 Markdown、事件 JSONL。
- 强调模型与确定性代码的边界：模型负责判断，普通代码负责调度、预算、去重、持久化和安全。

### 第 5 页：Diff 中心与按需上下文（3:10–4:00）

- 从修改文件、hunk 和修改行开始。
- 只补充直接相关的局部代码、测试、项目文档、配置与静态信号。
- ContextPack 受字符预算约束，大 PR 默认压缩为最多三个分片。
- GitHub 远程模式缺少本地仓库时明确降级，不伪装成工具执行成功。

### 第 6 页：流式 Agent Team（4:00–5:20）

- TeamLead 根据风险、文件和预算生成 ReviewPlan。
- DefectAgent 与 IntentAgent 并行执行，同一角色可按 ContextPack 分片。
- Verifier watcher 与专家同时启动，候选产生后立即进入反证，不等待所有专家完成。
- Verifier 可以向原专家发起一次定向补证。
- 第一版最多三个 ContextPack、六个专家实例，避免上下文和并发失控。

### 第 7 页：协作、工具与可靠性（5:20–6:25）

- Mailbox：类型化消息、顺序号、相关 ID、幂等和超时。
- Evidence Blackboard：只保存结构化事实、证据和裁决，不保存隐藏思维链。
- Skills：按角色、风险与预算选择，记录版本和内容哈希。
- Hooks：生命周期观测、安全拒绝和工具边界。
- 传统工具：代码读取、测试检索、文档检索、符号搜索和 Semgrep 信号。
- 600 秒全局 watchdog；单工具、单 Agent 或外部服务失败可输出 partial 并保留已有成果。

### 第 8 页：产品演示（6:25–8:10）

- 使用真实前端截图和现场页面，不制作虚构 UI。
- 展示入口：GitHub PR、本地仓库和离线 Replay。
- 展示运行页：阶段进度、共享工具链、并行 Agent 作战卡、当前动作、检查进度和事件时间线。
- 展示验证结果：候选、Verifier 接受或拒绝、最终 Finding。
- 展示稳定性：切换页面任务不终止、顶部常驻任务条、Replay 支持暂停和倍速。
- 现场网络或模型不稳定时使用同一公开事件协议的离线 Replay，并明确其不是实际 Benchmark 成绩。

### 第 9 页：Greptile Benchmark 与评测边界（8:10–9:10）

- 数据覆盖五个语言仓库，目标是回溯真实漏洞修复 PR 和引入提交。
- Judge 使用文件、位置和语义三层匹配。
- 当前公开可复现结果为五案例离线 Fake：五个完成、两个三层命中、三个非目标 Finding、Verifier 接受五个并拒绝一个。
- `observed_offline_catch_rate = 40%` 只验证 Runner、Judge 和报告链路，不计入真实命中率。
- `real_catch_rate = null`；真实公开 PR 仍需完成人工回溯和完整运行，不制作虚假成功链接。

### 第 10 页：竞争优势与总结（9:10–10:00）

- 精准：围绕 PR diff 与修改行，按需补充上下文。
- 可信：专家高召回、Verifier 找反证，只发布可验证 Finding。
- 高效：流式并行，不采用低效串行 Agent 链。
- 可审计：Mailbox、Blackboard、Skill/Prompt 哈希、事件与报告可回放。
- 可交付：十分钟硬预算、中文报告、Vue 作战室和故障降级。
- 收束句：ReviewCrew 的核心竞争力不是“多一个模型”，而是把 AI Review 变成一条可验证、可回放、可控制的工程流水线。

## 4. 附录设计

### 附录 A：技术栈与公开接口

- Python 3.12、Pydantic AI、FastAPI、Vue 3、Pinia、SSE。
- `POST /api/reviews`
- `GET /api/reviews/{run_id}`
- `GET /api/reviews/{run_id}/events`
- `GET /api/replays/{run_id}/events`
- `GET /api/benchmarks/latest`

### 附录 B：Finding 与证据协议

- Finding：类别、严重度、置信度、文件、修改行、标题、触发条件、影响和建议。
- CodeEvidence：来源、文件、行区间、描述和有界内容。
- Verifier：接受、拒绝、严重度校准和可选补证。

### 附录 C：已知边界与下一步

- GitHub 远程模式当前以 PR diff 为主，缺少本地 checkout 时文件、测试、符号与 Semgrep 能力会降级。
- 当前没有可对外宣称的真实 Greptile 命中率。
- 下一步优先接入临时只读 checkout 或 GitHub Contents API，并完成人工核验后的真实五仓运行。

## 5. 视觉规范

- 使用与 ReviewCrew 前端一致的深蓝背景、青色主强调和紫色协作强调。
- 标题页保持极简；正文标题不小于 35pt，正文不小于 16pt。
- 每页只表达一个主要结论，避免密集仪表盘式卡片堆叠。
- 架构页使用一张主架构图；Agent Team 页使用一张并行拓扑图。
- 产品页使用真实前端截图，优先展示共享工具链、最多六个专家和事件时间线。
- Benchmark 页使用五语言矩阵或简洁统计图，并将 Fake 与真实结果边界作为视觉重点。
- 不使用未实现功能截图、虚构 GitHub 成功链接或未实际运行的数据。

## 6. 素材与来源

- 产品与架构事实：仓库 README、实现代码、现有设计文档和本地运行截图。
- Benchmark 方法与公开案例来源：Greptile Benchmark Case Library。
- 评测数字：`docs/评测报告.md` 中已实际运行的 Fake quick 结果。
- 所有外部来源与非平凡外部结论在对应幻灯片备注中增加 `[Sources]` 区块。

## 7. 验收标准

1. 正文十页能够在十分钟内完整讲完，附录不占正文时间。
2. 架构、Agent Team、工具、可靠性、产品和评测均有清晰落点。
3. 所有数字、状态和能力与当前仓库一致。
4. 每页经过渲染检查，不存在文本溢出、异常换行、元素遮挡或低清截图。
5. 最终交付可直接使用的 `.pptx`，不交付临时脚本和中间素材。
