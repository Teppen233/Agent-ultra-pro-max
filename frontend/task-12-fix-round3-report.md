# Task 12 第三轮修复报告

## 范围

- 基线提交：`f6e7dcc0ed61237087da520c10a7a9824ef27bc8`
- 仅修复第二轮复审剩余的 1 个 Important 与 1 个 Minor。

## 修复内容

### Partial / failed Finding 不再冒充已验证

- 已核对后端 `_final_findings`：当 Verifier 失败或全局超时时，最终结果可能回退为尚未裁决的高置信候选。
- 只有 `completed` 结果显示“已验证问题”并传递 `accepted`。
- `partial` / `failed` 显示“当前可用问题”，传递 `pending` 和“需人工复核”。
- FindingCard 的 pending 状态会直接显示传入的人工复核文案，不再显示“Verifier 已确认”。

### Benchmark 枚举严格校验类型

- `mode`、`runner` 先校验为 string，再检查合法枚举值。
- `['quick']`、`['real']` 等可被 `String()` 强制转换的错误类型现在会被拒绝并降级 unavailable。

## TDD 证据

- 状态展示测试先因缺少列表标题、裁决状态和人工复核文案而失败，补充视图模型字段后转绿。
- Benchmark 数组枚举测试先观察到错误摘要被接受，改为严格类型校验后转绿。

## 最终验证

提交前执行结果：

- `pnpm test -- --run`：5 个测试文件、24 项测试全部通过。
- `pnpm build`：通过，Vite 转换 60 个模块。
