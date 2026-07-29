# ReviewCrew 版本登记

> 状态只依据可复现门禁登记。版本号更高不代表效果更好；`champion` 必须先满足 `stable`。

| 分支 | Git SHA | 状态 | 关键证据 | 未满足门禁 |
|---|---|---|---|---|
| `feature-1.1.1-mw` | `f70c3ea` | archived | 后端 183 项、前端 25 项、构建与 Fake Benchmark 通过；真实模型结构化 smoke 成功 | 生产构造器未自动加载配置模型；真实本地审查超时 |
| `feature-1.1.2-mw` | `9216ddf` | candidate | 后端 188 项、前端 25 项、生产构建通过；Fake quick 5/5 完成；生产模型构造与 30 秒协作窗口已覆盖测试 | 当前进程没有运行时密钥，修复后真实本地审查尚未复测，因此暂不登记 stable/champion |
| `feature-1.1.3-mw` | `a3ce134` | stable | 后端 192 项、前端 25 项、生产构建与 Fake quick 通过；真实 smoke 成功；真实本地审查 `run-20260729-201641-9d2d3334` 在约 182 秒完成且无 Agent Team 超时 | 当前最佳稳定基线；后续实验仍需同门禁比较后才能替代 |

## 状态定义

- `experimental`：正在验证假设，不能用于最终演示。
- `candidate`：自动化门禁通过，但仍缺至少一项稳定版硬门禁。
- `stable`：后端、前端、构建、Fake、真实模型 smoke 和真实 PR/本地审查全部通过。
- `champion`：从 stable 版本中按命中、误报、耗时、Finding 质量和演示稳定性选出的最佳版本。
- `rejected`：回归、收益不足或不可复现。
- `archived`：保留历史证据，但不再继续调优。
