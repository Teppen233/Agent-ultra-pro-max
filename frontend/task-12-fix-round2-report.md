# Task 12 第二轮修复报告

## 范围

- 基线提交：`ef27f611268bbc54fdeb0bb991611cacb6b66393`
- 仅处理第一轮复审中的 2 个 Important 与指定易修 Minor。
- 未修改评审输入、后端代码或其他用户工作区文件。

## Important 修复

### Benchmark API 运行时契约

- 在 API 边界增加 `asBenchmarkSummary`，校验 mode、runner、offline、全部计数字段、两个命中率、离线排除标记和耗时。
- 计数字段必须为非负整数，命中率必须为 `null` 或 `[0, 1]` 有限数，耗时必须为非负有限数。
- 无效或不完整 JSON 会抛出稳定错误；History 页现有 `Promise.allSettled` 将其降级为 unavailable，展示“暂无数据”，不会执行 `undefined.toFixed()`。

### ReviewResponse 与结果状态展示

- `ReviewResponse` 现在明确区分：运行中 `pending`、仅状态失败 `failed`、完整 `result`。
- 轮询遇到仅状态失败会停止等待，结果页展示“审查已失败，未生成完整报告”，不会把它当作不完整成功报告。
- 完整 `completed`、`partial`、`failed` 结果继续水合 Store，并分别使用成功勾、警告三角、失败叉号图标。
- `partial` 使用“部分结果，需人工复核”，不再声称整个结果已经独立验证；`failed` 明确标注为失败前保留结果。

## Minor 修复

- 将全局 `:focus-visible` 规则移动到局部 `outline: none/0` 之后，并使用足够的选择器优先级，输入框与筛选框不再丢失键盘焦点。
- Demo 耗时副标题改为“离线演示耗时”；只有真实水合结果使用“服务端实际结果”。
- 视图模型测试覆盖 completed、partial、failed 三种终态及 Demo 耗时来源；API 测试覆盖无效 Benchmark 和仅状态失败响应。

## TDD 证据

- 无效 Benchmark 测试先观察到 Promise 错误地返回不完整对象，随后增加运行时校验并转绿。
- 仅状态失败测试先观察到“最终审查结果尚未完整生成”异常，随后增加 `failed` 分支并转绿。
- 状态展示测试先因 `presentResultStatus` 不存在而失败，随后实现三态展示模型并转绿。

## 最终验证

提交前执行：

```text
pnpm test -- --run
pnpm build
```

最终结果：

- Vitest：5 个测试文件、23 项测试全部通过（包含共享工作区中的全栈契约门禁）。
- 生产构建：通过，Vite 转换 60 个模块并成功输出 `dist/`。
