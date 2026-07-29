# Task 12 第一轮修复报告

## 修复范围

- 评审基线：`180ddb976638b04b2ee7a62f8f06d8f77d8b81d3`
- 输入评审：`frontend/task-12-review.md`（仅作为输入，未修改）
- 本轮目标：修复 6 个 Important 与 4 个 Minor，并补齐关键回归测试。

## Important 修复

### I-1 最终结果水合不再依赖实时 Finding 数量

- Store 新增 `resultHydrated`，仅在完整 `ReviewResult` 写入后置为 `true`，重置运行时恢复为 `false`。
- 真实结果页只依据 `resultHydrated` 判断是否需要获取最终 JSON，不再用 `findings.length` 代替最终报告状态。
- Demo 通过显式 `demo=1` 分支跳过后端，避免演示数据与真实运行混用。

### I-2 Benchmark 契约与真假标识对齐

- `BenchmarkSummary` 已与后端 `benchmark/models.py` 对齐，使用 `runner`、`offline`、`real_catch_rate`、`observed_offline_catch_rate`、`elapsed_seconds` 等真实字段。
- 仅当 `runner === 'real' && offline === false` 时展示真实命中率。
- fake/offline 结果明确标注“离线观察值，不计入真实命中率”。
- 接口或字段无数据时显示“暂无数据”，删除 `12 / 9 / 75% / 184s` 等硬编码回退值和伪造逐仓成绩。

### I-3 阶段顺序与 Orchestrator 一致

阶段固定为：

1. `loading_pr`
2. `building_context`
3. `planning`
4. `team_review`
5. `reporting`

删除前端自行添加的 `parsing_diff`、`verifying` 等幽灵阶段；Verifier 继续作为 `team_review` 内的智能体状态展示。离线 fixture 已补入 `planning` 的开始与完成事件，并验证所有阶段最终收敛。

### I-4 离线 Replay 具备生命周期取消能力

- `replayEventLog` 支持 `AbortSignal`、运行令牌与当前令牌校验。
- 每次等待前后及写入事件前均检查取消状态和令牌有效性。
- `ReviewPage` 卸载时会使令牌失效并中止 Replay，旧回放不能继续写入全局 Store。

### I-5 区分运行中状态与完整 ReviewResult

- `GET /api/reviews/{run_id}` 建模为可辨识联合类型：`pending` 或 `result`。
- 客户端对响应进行运行时结构校验，运行中 `{run_id, status}` 不会进入 `hydrateResult`。
- 结果页会持续轮询并显示等待状态，只在完整终态 JSON 到达后渲染报告。
- 补充取消边界：若页面在请求返回前卸载，轮询不会交付过期最终结果，也不会触发后续 Store 写入。

### I-6 删除真实报告的伪造指标

- 删除真实运行中的固定 `7` 个文件、`6s`、`88% / 92%` 和固定文件名回退。
- 无最终数据时显示“暂无数据”；合法的零文件、零秒保持显示为 `0` 和 `0s`。
- 因后端没有覆盖率分母，覆盖圆环改为展示实际覆盖文件数量，不再臆造百分比。
- 演示指标仅存在于显式 Demo 分支，并标注“演示数据”。

## Minor 修复

### M-1 移动端导航

760px 以下保留固定底部主导航，用户仍可进入“新建审查”和“历史与回放”。

### M-2 SSE 终态连接提示

订阅处理器新增终态关闭回调；收到 `review.completed` 或 `review.failed` 后，页面明确显示连接已关闭，不再保留“实时事件已连接”的误导状态。

### M-3 基础无障碍

- 增加全局 `:focus-visible` 键盘焦点样式。
- 连接状态、加载状态使用 `role="status"` 与 `aria-live`。
- 表单错误使用 `role="alert"` 与 `aria-live="assertive"`。

### M-4 中文文案与关键行为回归

- 主要页面眉标、导航、阶段和智能体标签已改为中文；GitHub、PR、Diff、Markdown、Agent 等保留为领域术语。
- 新增页面展示模型测试，覆盖最终结果获取条件、Benchmark 真/离线/缺失展示、真实零值和 Demo 隔离。
- API、Store 与完整 Demo Replay 测试覆盖运行中状态、最终水合、阶段顺序、终态关闭和取消写入。

## TDD 证据

本轮新增回归用例均先观察到预期失败，再实施最小修复：

- 运行中响应被误当最终结果。
- 结果页已有实时 Finding 时跳过最终 JSON。
- Benchmark 使用错误字段和硬编码成绩。
- Orchestrator 阶段顺序缺失 `planning` 并存在幽灵阶段。
- Replay 在取消或令牌失效后继续写入。
- SSE 终态关闭未通知页面。
- 真实零值被回退值覆盖，Demo 数据缺少隔离。
- 请求尚未返回时取消轮询，旧终态结果仍会被交付；RED 结果为 18 通过、1 失败，最小修复后 API 客户端 9 项通过。

## 最终验证

最终提交前执行：

```text
pnpm test -- --run
pnpm build
```

验证结果：

- Vitest：4 个测试文件、19 项测试全部通过。
- 生产构建：通过，Vite 转换 60 个模块并成功输出 `dist/`。

## 非阻塞说明

- 默认轮询间隔使用 1 秒定时器；取消后不会再请求或水合，但当前定时器会自然结束后退出。
- 若服务端仅返回失败状态而没有完整结果文件，结果页会显示安全错误提示，不会把不完整结构渲染为报告。
- `fetchLatestBenchmark` 当前依赖 TypeScript 契约；展示层对接口不可用提供“暂无数据”降级，尚未增加完整运行时字段校验。
