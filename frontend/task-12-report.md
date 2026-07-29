# Task 12 实施报告：Vue 3 审查与 Replay 控制台

## 完成范围

- 初始化 Vue 3、TypeScript、Vite、Pinia、Vue Router、Vitest 与 pnpm 工程。
- 冻结前端 `PipelineEvent` 六字段契约，实现 SSE、服务端 Replay 与离线 JSONL Replay 共用的 `applyEvent` 归约器。
- 实现新建审查、实时运行、审查报告、历史与回放四个页面。
- 实现阶段进度、600 秒预算、Agent Team 拓扑、公开事件时间线、Finding 证据卡片和 Benchmark 摘要组件。
- 内置完整离线 Demo：两个专家并行、两个候选、Verifier 一接收一拒绝、报告生成与审查终态。

## 可靠性与安全边界

1. `sequence` 小于等于当前序号的事件会被忽略，SSE 重连补历史时不会重复归约。
2. 收到 `review.completed` 或 `review.failed` 后主动关闭 EventSource，Store 终态封口，不再接受后续污染事件。
3. EventSource 断线保留浏览器自动重连，界面明确显示“正在自动恢复”；后台审查不会被前端取消。
4. 时间线只按白名单读取阶段、Agent、工具名、Finding ID、裁决与状态，不展示 Prompt、模型原始响应或隐藏推理。
5. API 地址通过 `VITE_API_BASE_URL` 配置；默认使用同源 `/api`，离线 Demo 不依赖后端、模型或网络。

## TDD 记录

- 首条 Store 测试按预期因 `@/stores/review` 不存在而失败。
- API Client 测试按预期因 `@/api/client` 不存在而失败。
- `hydrateResult/reset` 测试按预期因 `store.hydrateResult is not a function` 失败。
- Verifier/报告阶段测试按预期因阶段保持 `waiting` 而失败。
- 最终覆盖事件归约、重复/倒序/终态处理、报告补全与重置、阶段映射、HTTP 中文错误、JSONL 解析、可调速回放、终态关闭 SSE，以及完整 Demo Replay。

## 验证结果

- `pnpm test -- --run`：3 个测试文件、10 项测试全部通过。
- `pnpm build`：Vue TypeScript 检查与 Vite 生产构建通过，59 个模块完成转换。
- HTTP 路由烟测：首页、离线运行页、报告页、历史页均返回 200 且包含应用挂载点。
- in-app Browser 当前没有可用浏览器实例，因此未完成截图级视觉检查；已通过生产构建、路由烟测与完整 Replay 自动测试覆盖关键演示链路。

## 后续关注点

- 历史页的仓库矩阵在后端不可用时展示明确标注的布局演示值；连接 `/api/benchmarks/latest` 后应以真实摘要字段为准。
- 当前 EventSource 使用浏览器原生重连策略；若后续服务端支持 `Last-Event-ID` 或显式断点参数，可进一步缩短超长历史运行的恢复时间。
