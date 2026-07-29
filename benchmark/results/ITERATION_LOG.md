# ReviewCrew 迭代日志

## Runtime-01：生产模型装配与协作窗口收敛

- 时间：2026-07-30 03:58（北京时间）
- 父版本：`feature-1.1.1-mw@f70c3ea`
- 当前版本：`feature-1.1.2-mw@9216ddf`
- 归因层：Runtime
- Prompt 聚合 SHA-256：`fa36d2597f3bca9fb8665d01f1d3a84a98df61a889a01b104d119de20b79685a`
- Skill 聚合 SHA-256：`2c173d3c2078cab2282213338f61fa9338e6396adda3b4c15348fb6ccbca9c63`

### 基线

| 运行 | 模型状态 | 结果 | 耗时/问题 |
|---|---|---|---|
| `run-20260729-193757-1ef8f384` | 生产构造器没有加载模型 | partial，0 Finding | 同时出现“未配置模型”和 Agent Team 超时 |
| `run-20260729-194836-aa41f728` | 已确认发生真实模型调用 | partial，0 Finding | 约 199 秒后 Agent Team 超时 |

### 根因与假设

专家完成模型审查并发布候选后，默认协作窗口为无限，导致其继续等待完整 `review_timeout_seconds`。假设：把默认协作等待限制为可配置的 30 秒，并由生产构造器按角色自动创建模型，可避免“模型已返回但阶段仍等满预算”。

### 定向修改

- 有密钥时，TeamLead、Defect、Intent、Verifier 构造器自动按角色模型覆盖创建 OpenAI 兼容模型。
- 增加 `tool/prompted` 结构化输出切换；当前兼容端点使用 `prompted`。
- 增加 `REVIEWCREW_COLLABORATION_WINDOW_SECONDS`，默认 30 秒；显式测试/调用参数仍优先。

### 同案例复测与邻近回归

- 定向测试：配置窗口与专家默认窗口 2 项先红后绿。
- 运行时/专家/配置测试：36 项通过。
- 后端全量：188 项通过。
- 邻近回归：前端 25 项通过，Vue 生产构建通过。
- Benchmark quick（Fake）：5 个案例完成，2 个命中、3 个非目标 Finding、0 超时，耗时 0.05 秒。Fake 结果只验证链路，不计入真实命中率。
- Benchmark case（Fake，`sentry-offline-01`）：1/1 命中，0 非目标 Finding，耗时 0.01 秒。

### 结论

自动化证据支持保留 Runtime 修改，但当前进程未保留运行时密钥，无法安全执行修复后的真实本地审查。版本暂列 `candidate`；补做真实 smoke 与本地 base/head 审查且不再出现阶段超时后，才可升级为 `stable`。

## Verification-01：让 Verifier 消费专家已检索上下文

- 时间：2026-07-30 04:15（北京时间）
- 父版本：`feature-1.1.2-mw@92acac9`
- 当前版本：`feature-1.1.3-mw@af8877b`
- 归因层：Verification / Runtime
- Prompt 聚合 SHA-256：`fa36d2597f3bca9fb8665d01f1d3a84a98df61a889a01b104d119de20b79685a`
- Skill 聚合 SHA-256：`2c173d3c2078cab2282213338f61fa9338e6396adda3b4c15348fb6ccbca9c63`

### 假设与修改

生产专家原先只发布 Finding 与 `context_id`，Verifier 虽支持 `verification_context`，却拿不到 Context Builder 已检索的入口、相关实现和测试证据。现在候选消息按 `enclosing_code → related_code → related_tests` 的稳定优先级携带最多 12 条去重 `CodeEvidence`，不改变公共 Finding 或 Judge 口径。

复审同时发现并修复：空字符串密钥错误触发生产模型、兼容端点旧配置默认走不支持的工具式结构化输出、协作窗口短于首次 Verifier 模型超时可能错过补证。测试模型仍自动使用原生工具协议。

### 同案例与邻近回归

- 新增失败测试先确认候选载荷缺少 `verification_context`，实现后转绿。
- 专家、Verifier、配置和运行时定向测试：54 项通过。
- 后端全量：192 项通过。
- 前端：25 项通过；生产构建 60 modules 通过。
- 目标案例 `calcom-offline-01`：Fake Runner 仍为 0/1，1 个非目标 Finding；这是故意的文件层负例，Fake Runner 绕过 Agent Team，不作为本修改收益指标。
- 邻近案例 `sentry-offline-01`：Fake Runner 1/1 命中、0 非目标 Finding、0.01 秒，未回归。
- Fake quick：5/5 完成、2 命中、3 个非目标 Finding、0 超时；与基线一致，确认未篡改 Judge 或 fixture。

### 结论

该实验修复了真实生产链路中“检索到了上下文但 Verifier 看不到”的断点，且自动化门禁无回归。随后通过剪贴板只读取得运行时密钥，仅在单个进程注入并在结束时移除：

- `deepseek-v4-pro` 结构化 smoke 成功。
- 本地 `dbdb23c^ → dbdb23c` 审查运行 `run-20260729-201641-9d2d3334`，状态 `completed`，约 182 秒，0 个确认问题，未出现 Agent Team 超时。
- 运行报告位于 `runs/run-20260729-201641-9d2d3334`，不进入 Git。

因此 `feature-1.1.3-mw@a3ce134` 晋升为 `stable`，作为后续实验的可恢复基线。

## Runtime-02：候选发布屏障与协作提前收敛

- 时间：2026-07-30 04:26（北京时间）
- 父版本：`feature-1.1.3-mw@e94783d`
- 当前版本：`feature-1.1.4-mw@e44b970`
- 归因层：Runtime / Verification
- Prompt 聚合 SHA-256：`fa36d2597f3bca9fb8665d01f1d3a84a98df61a889a01b104d119de20b79685a`
- Skill 聚合 SHA-256：`2c173d3c2078cab2282213338f61fa9338e6396adda3b4c15348fb6ccbca9c63`

### 假设

1.1.3 虽不再超时，但无候选的小差异仍耗时约 182 秒。根因是专家必须等满协作窗口，Verifier 又把专家最终终态当作“不会再有候选”的唯一屏障。增加独立的 `agent_review_completed` 消息后，Verifier 可以在所有初审候选发布完毕时收敛；专家收到 Verifier 终态即可提前退出，同时保留 125 秒异常兜底。

### 同案例复测

| 版本 | 运行 ID | 状态 | 确认 Finding | 耗时 |
|---|---|---|---:|---:|
| 1.1.3 | `run-20260729-201641-9d2d3334` | completed | 0 | 约 182 秒 |
| 1.1.4 | `run-20260729-202329-19ffd896` | completed | 0 | 约 106 秒 |

相同模型、端点、仓库与 `dbdb23c^ → dbdb23c` 差异下缩短约 76 秒，降幅约 42%，且两次都没有 Agent Team 超时。

### 邻近回归

- Team 协作定向：61 项通过。
- 后端全量：194 项通过。
- 前端：25 项通过；生产构建 60 modules 通过。
- Fake quick：5/5 完成、2 命中、3 个非目标 Finding、0 超时，与基线一致。

### 结论

1.1.4 在不减少 Verifier 补证窗口、不修改 Prompt/Skill/Judge 的前提下显著降低真实耗时，晋升为 `stable`，并成为当前 Champion 候选。

## Retrieval-01：跨文件调用证据与终态竞态修复

- 时间：2026-07-30 04:36（北京时间）
- 父版本：`feature-1.1.4-mw@01b3d25`
- 当前版本：`feature-1.1.5-mw@9fee642`
- 归因层：Retrieval / Runtime
- Prompt 聚合 SHA-256：`fa36d2597f3bca9fb8665d01f1d3a84a98df61a889a01b104d119de20b79685a`
- Skill 聚合 SHA-256：`2c173d3c2078cab2282213338f61fa9338e6396adda3b4c15348fb6ccbca9c63`

### 根因与修改

- `ContextPack.related_code` 和 Verifier 消费通道已经存在，但 Context Builder 从未填充跨文件实现或调用入口。
- 从新增声明行保守提取最多 3 个 Python/TypeScript/JavaScript/Go/Java 符号，检索当前文件之外的代码引用；排除 Markdown 等文档噪声，稳定去重并最多保留 10 条 `CodeEvidence`。
- 独立复审发现最后一个专家可能在注册 Mailbox 前触发 Verifier 终态广播。专家现在进入运行时立即注册，确定性竞态测试证明不再等满兜底窗口。

### 目标与邻近回归

- Cal.com 风格 fixture：修改 `packages/auth/session.ts` 的 `getCalendar`，成功定位 `apps/web/api/calendar.ts` 调用入口与准确行范围。
- 文档中同名字符串不会进入 `related_code`；当前修改文件、重复证据被排除，总数不超过 10。
- 相关 Context/Expert/Verifier/Orchestrator 回归：55 项通过。
- 后端全量：196 项通过。
- 前端：25 项通过；生产构建 60 modules 通过。
- Fake quick：5/5 完成、2 命中、3 个非目标 Finding、0 超时，与基线一致。
- 相同真实审查 `dbdb23c^ → dbdb23c`：`run-20260729-203428-67713bf5`，状态 completed，0 Finding，约 59 秒。该耗时优于 1.1.4，但模型响应存在波动，不把全部降幅归因于检索修改。

### 结论

1.1.5 同时补齐了跨文件 Localization 证据和团队终态竞态，全部硬门禁通过，晋升为 `stable` 与当前 Champion 候选。

## Presentation-01：真实 Benchmark 执行闭环

- 时间：2026-07-30 04:48（北京时间）
- 父版本：`feature-1.1.5-mw@2c98b57`
- 当前版本：`feature-1.1.6-mw@59b1cb6`
- 归因层：Presentation / Runtime
- Prompt 聚合 SHA-256：`fa36d2597f3bca9fb8665d01f1d3a84a98df61a889a01b104d119de20b79685a`
- Skill 聚合 SHA-256：`2c173d3c2078cab2282213338f61fa9338e6396adda3b4c15348fb6ccbca9c63`

### 根因与修改

原 `--runner real` 在 CLI 层硬编码退出，数据集即使补成 ready 也不能进入 ReviewCrew。现在 Real Runner 默认把每个 `test_pr` 交给 Orchestrator，保留 executor 注入用于测试；没有 ready 案例时仍退出 2，拒绝把空运行伪装为成绩。README 与评测报告同步说明真实状态。

### 验证

- Benchmark 模型/Judge/Runner：42 项通过。
- 后端全量：197 项通过。
- 前端：25 项通过；生产构建 60 modules 通过。
- Fake quick：5/5 完成，口径不变。
- 当前生产数据集无 ready 案例：`--runner real` 退出 2，并提示先完成人工核验。
- 直接使用数据集中公开测试 PR 验证真实适配器链路：`run-20260729-204215-9ed6a5a4`，状态 completed，0 Finding，约 285 秒；该运行只证明 GitHub PR → Orchestrator → ReviewResult 可用，不计入正式命中率。

### 结论

1.1.6 补齐交付要求中的真实评测执行入口，全部硬门禁通过，晋升为 `stable` 与当前 Champion 候选。正式 Greptile 命中率仍必须在人工补齐 source fix、40 位 SHA、目标行和语义关键词后计算。
