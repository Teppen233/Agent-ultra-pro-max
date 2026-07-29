# Task 10 实施报告：FastAPI、SSE 与 Replay

## 完成范围

- 新增可注入依赖的 FastAPI 应用工厂与默认 `app`。
- 实现 `POST /api/reviews`，先原子预留运行 ID，再以后台任务执行审查并返回 `202`。
- 实现审查状态、JSON/Markdown 报告、分页运行摘要、实时 SSE、历史 Replay 和最近 Benchmark 摘要接口。
- 实现 Replay 的稳定时序、正有限倍速校验与可注入异步等待函数。
- 与 Task9 的 `EventStore.reserve/claim` 及 `Orchestrator.review(..., emit_terminal_event=False)` 契约完成联动。

## 关键实现

1. **终态单一所有权**：HTTP 后台任务要求 Orchestrator 不直接发送终态，在真实返回或异常后由 Server 恰好发送一次 `review.completed` 或 `review.failed`。运行中状态只返回普通状态字典，不构造虚假的 `ReviewResult`。
2. **无丢失 SSE**：先注册实时订阅，再读取并输出持久化历史；历史与订阅重叠窗口使用 `sequence` 去重，最终终态后关闭生成器。SSE 生成器关闭只注销订阅，不取消后台审查任务。
3. **统一公开协议**：实时 SSE 与 Replay 均输出经过再次脱敏的 `PipelineEvent` 六个公开字段，不返回 Prompt、模型响应或内部推理字段。
4. **安全文件边界**：运行 ID 拒绝路径穿越；运行目录、报告和 Benchmark 文件拒绝符号链接、Windows NTFS Junction，并校验解析后路径仍位于固定根目录。
5. **可恢复错误**：缺失资源、请求校验、损坏的 result、Markdown 和 events 文件均返回中文 `detail`；后台异常日志只记录中文上下文和异常类型，不公开异常原文。
6. **有界历史列表**：`GET /api/runs` 支持 `limit`（1-100）和 `offset`，只读取事件摘要，不逐份解析完整 `result.json`。
7. **真实 Benchmark 目录**：`GET /api/benchmarks/latest` 同时支持根目录摘要和 `benchmark/results/<timestamp>/summary.json`，返回前执行脱敏。

## TDD 记录

- 初始 `pytest tests/test_server.py -v` 按预期因 `reviewcrew.server` 不存在而失败。
- 分别观察并修复了以下 RED：时间戳 Benchmark 子目录未发现、Fake 结果无磁盘报告、过早 completed 后异常、损坏 Markdown 英文 500、运行列表无界并解析完整结果、NTFS Junction 越界、纯 `**kwargs` Fake 注入失败、损坏 events 的四接口英文 500。
- 最终 `tests/test_server.py` 共 24 项，覆盖 REST、后台成功/失败、SSE 历史/实时重叠、终态关闭、脱敏、报告、分页、路径安全、Replay 时序和参数校验。

## 验证结果

- `pytest tests/test_server.py tests/test_events.py tests/test_orchestrator.py -q`：48 passed。
- `pytest -q`：140 passed，耗时 9.11 秒。
- `python -m compileall -q reviewcrew`：通过。
- `git diff --check`：通过。
- 独立只读代码复核：Critical 0、Important 0，Ready Yes。

## 文件与提交边界

- 新增：`reviewcrew/server/__init__.py`
- 新增：`reviewcrew/server/app.py`
- 新增：`reviewcrew/server/replay.py`
- 新增：`tests/test_server.py`
- 新增：`task-10-report.md`
- Task9 已在提交 `e232359` 中提供 Orchestrator/EventStore 必要兼容，本任务不重复暂存或提交 Task9 文件。

## 后续关注点

- 当前运行列表返回条数有界，但为了计算总数和精确时间顺序仍需扫描所有运行的事件文件；当历史运行达到较大规模时，可增加独立的持久化运行摘要索引。
