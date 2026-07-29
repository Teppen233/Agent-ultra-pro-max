# Task 11：Greptile Benchmark 实施报告

## 交付内容

- 新增 `benchmark` 包，提供 Dataset、三层 Judge、Fake/Real 后端接口、`quick/case/full` 选择与中文报告。
- `benchmark/dataset.yaml` 准确转录 Greptile Case Library 中五仓各一条公开案例的标题、严重度、漏洞描述和重建 PR。
- 五条公开记录全部保持 `needs_review`。除调研已核验的 Sentry 重建 PR base/head 外，不填写未知 SHA；`source_fix_pr`、引入/修复提交和目标位置均不猜测。
- `benchmark/fixtures/fake_dataset.yaml` 提供 Python、TypeScript、Go、Java、Ruby 各一条明确使用 `fixture://` / `fixture/*` 身份的离线 ready 案例。
- Fake Runner 不导入或调用网络客户端，固定覆盖直接命中、文件错误、超过十行、语义错误、Verifier 拒绝计数和恰好十行容差命中。
- 输出 `cases.jsonl`、`summary.json`、`summary.md`，统计误报、Verifier 接受/拒绝、超时、失败、耗时和人工复核数。

## 数据与评分边界

- 公共 `ready` 案例必须具有 fork、重建 PR、原始修复 PR、base/head、引入/修复提交、目标位置、漏洞描述、机制和影响关键词。
- 公共 `ready` 进一步要求真实仓库 slug、完整 `https://github.com/{owner}/{repo}/pull/{number}` URL 和 40 位十六进制提交 SHA。
- Judge 只读取 `ReviewResult.findings`，即 Verifier 最终接受并发布的 Finding；拒绝项不会被恢复为命中。
- 命中必须依次满足目标文件、目标区间重叠或案例显式允许的最多 ±10 行、同一错误机制及实际影响。
- 多个正确 Finding 可共同命中同一目标；只有未通过三层匹配的 Verifier 接受项计入误报。
- Fake 结果只给出 `observed_offline_catch_rate`，`real_catch_rate` 固定为 `null`，并在 Markdown 中声明“不计入真实命中率”。

## Runner 行为

- `python -m benchmark.runner --mode quick --runner fake`：每仓最多一条离线 ready 案例。
- `--case <id>`：无需额外指定 mode，自动切换为单案例模式；未知 ID 返回退出码 2。
- `--mode full`：运行全部 ready 案例。
- Real API 通过 `RealReviewRunner(executor=...)` 注入真实 ReviewCrew 执行器；CLI 未注入时返回退出码 2，不生成“0 案例成功”报告。
- 单案例超时或异常会写入 failed 记录、保留真实等待耗时、标记人工复核，并从真实命中率分母排除。
- 数据集缺失、损坏或模型校验失败时输出中文错误并返回退出码 2，不暴露 traceback。

## TDD 与审查

- 初始 RED：25 项测试因 `benchmark` 尚不存在而全部失败。
- 后续按问题逐条补 RED，覆盖 `source_fix_pr`、公共来源格式、真实 Case Library 字段、重复正确命中、超时/异常落盘、`--case`、Real CLI、缺失/损坏数据集和失败耗时。
- 专项最终覆盖 Dataset、Judge、Runner/CLI 与三种报告产物。
- 两轮独立只读代码审查提出的 1 个 Critical 和 5 个 Important 均已修复；最后补强完整 PR URL 和数据集错误处理。

## Fake quick 实际结果

- 选择案例：5
- 完成案例：5
- 离线观察命中：2
- 离线观察命中率：40%
- 误报 Finding：3
- Verifier 接受/拒绝：5/1
- `real_catch_rate`：`null`
- 网络：离线，无凭据、无 token、无外部写入

运行产物位于 `benchmark/results/fake-quick/`，该目录默认忽略运行时文件，仅保留 `.gitignore`。
