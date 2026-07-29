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

