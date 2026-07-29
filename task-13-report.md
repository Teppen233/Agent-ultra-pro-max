# Task 13 报告：全栈契约集成与真实冒烟

## 实现范围

- 新增 `tests/test_full_stack.py`，以临时 Git 仓库构造真实 base/head。
- HTTP 链路覆盖：`POST /api/reviews` → 后台生产 Orchestrator（模型角色使用确定性 Fake）→ 实时 SSE → JSON/Markdown 报告 → 服务端 Replay。
- 冻结后端公开契约：`PipelineEvent` 六字段、事件类型白名单、连续序号、Replay 等价顺序，以及 `ReviewResult` 公开字段。
- 验证真实 Git 加载、ContextPack 构建、Finding、Verdict、结果和三类持久化产物贯通。
- 直接读取落盘 `events.jsonl`、`result.json` 与 `report.md`，断言它们分别与 SSE、JSON API 和 Markdown API 完整等价。
- 新增前端生产 payload 合同测试，让事件与最终结果实际经过 `parseEventLog`、`replayEventLog`、`fetchReview` 和 Pinia Store。
- 修复本地审查 `review.started` 只发送 `mode` 的适配缺口，补充前端实时 Store 已公开消费的 `repository` 与 `title`。

## TDD 记录

1. 首版全链路测试通过，表明断言只覆盖已有能力，未形成有效回归保护。
2. 加入本地启动事件的前端公开消费字段后，定向测试按预期失败：实际数据只有 `{"mode": "local"}`，缺少 `repository/title`。
3. 最小修改 Orchestrator 的启动事件数据，不改变事件类型、领域 Schema 或 HTTP 路径。
4. 定向测试重新运行通过。

## 门禁结果

| 门禁 | 结果 |
|---|---|
| `pytest tests/test_full_stack.py -v` | 通过，1 项 |
| `pytest -q` | 通过，182 项 |
| `python -m benchmark.runner --mode quick --runner fake` | 通过，5 个离线案例；2 个命中；Fake 结果不计入真实命中率 |
| CLI 本地 fixture（仓库 `180ddb9 → ef27f61`，Fake 模型角色） | 通过，退出码 0；生成 `events.jsonl`、`result.json`、`report.md` |
| `pnpm test -- --run` | 通过，5 个测试文件、24 项测试 |
| `pnpm build` | 通过，60 个模块完成生产构建 |

## 真实模型状态

- 仅检查环境变量是否存在，未读取、回显或保存任何密钥值。
- `GLM_API_KEY`、`REVIEWCREW_LLM_API_KEY`、`ZAI_API_KEY` 均未设置。
- 因无可用运行时密钥，真实 GLM smoke 与小 Context 配置模型审查均未执行；不伪造成功记录。

## 关注点

- 独立首轮审查发现三个缺口：未执行 TypeScript/Pinia、未读取落盘 JSON、Replay 只比较类型与序号；三项均已补齐并重新验证。
- 本机 Codex fallback `pnpm` shim 的子进程 PATH 不包含 Node；门禁通过临时前置系统 Node 目录执行，未修改项目配置。
- 当前仓库存在与 Task13 无关的用户/其他任务改动；本任务只提交 `tests/test_full_stack.py`、`frontend/src/full-stack-contract.spec.ts`、`reviewcrew/pipeline/orchestrator.py` 与本报告。
