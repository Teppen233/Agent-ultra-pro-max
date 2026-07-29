# Task 9：Orchestrator 与 CLI 实现报告

## 实现结果

- 新增 `Orchestrator.review(request: ReviewRequest) -> ReviewResult`，串联 PR 加载、Context 构建、Team Lead 规划、两个专家、Verifier watcher、可选静态分析和报告持久化。
- Agent Team 使用 `asyncio.TaskGroup` 并发启动；Verifier 优先创建，收到首个候选后可在专家完成前立即裁决。
- 每次运行统一创建 Mailbox、EvidenceBlackboard、MessagePublisher 和 EventStore；团队消息使用共享序号，公开摘要同步转为 PipelineEvent。
- watcher 同时兼容 `expected_agent_ids` 与 `stop_event` 注入，专家完成后显式停止，并在超时或取消的 `finally` 路径终止残留 watcher。
- 全局 watchdog 默认 600 秒；PR 加载、Context、规划/团队审查、Verifier 和报告均使用可注入预算。
- 单专家失败、Verifier 失败、阶段超时和全局超时均降级为 `partial`，输出中文 warning，并保留已返回或已发布到 Blackboard 的验证结果。
- Verifier 失败时只保留置信度不低于 0.8、且尚未被裁决的候选，并明确标注未经完整验证。
- 持久化 `runs/{run_id}/result.json`、`report.md`、`events.jsonl`；结果与事件不保存 Prompt、原始模型响应或异常原文，报告继续移除 `reasoning_summary`。
- 新增 CLI：
  - `python -m reviewcrew.cli review --pr <github-pr-url>`
  - `python -m reviewcrew.cli review --repo <path> --base <ref> --head <ref>`
  - `python -m reviewcrew.cli replay --run-id <run-id>`
- CLI 使用中文进度、错误和警告；参数错误、运行失败、Replay 不存在均返回非零退出码。

## Task8 注入适配

- Orchestrator 仅通过签名检测向 watcher 传递 `expected_agent_ids` 和 `stop_event`，没有修改 Verifier、专家、Mailbox、Blackboard 或 Publisher 的 Task8 内部实现。
- 当前工作区中 Task8 的并行修改未纳入本任务暂存或提交。

## TDD 与验证

- RED：`pytest tests/test_orchestrator.py tests/test_cli.py -v` 初次因缺少 `reviewcrew.pipeline.orchestrator` 和 `reviewcrew.cli` 收集失败。
- 专项：`pytest tests/test_orchestrator.py tests/test_report.py tests/test_cli.py -v` → `17 passed`。
- 全量：`pytest -q` → `93 passed`。
- CLI：`python -m reviewcrew.cli --help` → 退出码 0。
- 补充检查：`git diff --check` → 退出码 0。

## 重点回归覆盖

- 首候选在两个专家完成前被 Verifier 消费。
- 单专家失败不丢失另一路已验证 Finding。
- Verifier 失败仅保留高置信候选。
- 阶段超时和全局 watchdog 生成 `partial`、中文 warning 和持久化报告。
- watcher 被全局取消前已发布的裁决可从 Blackboard 恢复。
- watcher 同时“发布裁决消息并返回裁决”时不会重复生成 PipelineEvent。
- 未知异常文本不会进入 `result.json`。
- 本地、GitHub PR、Replay、参数错误与失败退出码均有 Fake 无网络测试。
