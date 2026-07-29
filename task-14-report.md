# Task 14 报告：中文交付文档与可复现命令

## 交付内容

- 新增根目录 `README.md`，覆盖架构、Conda Python 3.12 安装、全部模型/角色/预算变量、Fake 与真实审查边界、FastAPI、Vue、Replay、Benchmark quick/case/full、测试构建、600 秒预算、中文日志、安全和故障排查。
- 新增 `docs/知识库维护方案.md`，明确第一版知识源、版本模型、更新、回滚、质量门禁和安全规则；合并触发增量索引仅作为尚未实现的维护设计。
- 新增 `docs/评测报告.md`，只录入已生成的五仓 Fake quick 结果；40% 明确排除在真实命中率之外。真实模型 smoke 与真实 PR 审查分开陈述，没有伪造真实 Finding、Replay 或成功链接。
- 新增 `docs/三分钟演示脚本.md`。原七段指定时长合计 210 秒，脚本通过两处 15 秒画中画重叠把总成片压到 180 秒，同时保留每段规定展示时长。
- 补全 `.env.example` 的角色、阶段预算、上下文预算，并记录已验证的 `deepseek-v4-pro` OpenAI 兼容 Base URL；强调必须包含 `/v1`。
- 更新实施计划 Task11–14 checkbox 与 Task14 实际文档路径。

## 前端开发联通修正

- 前端 `/api` 到本地 FastAPI 的 Vite 开发代理已由提交 `bc1f220` 提供。
- 原测试位于 `frontend/src/vite-config.spec.ts`，会被 `vue-tsc` 当作应用源码编译并引入 `node:url` 类型，导致生产构建失败。
- 本任务把该测试移动到 `frontend/vite-config.spec.ts`；功能配置不变，Vitest 仍覆盖代理契约，应用构建不再包含该测试。

## 真实模型与评测口径

- 最新真实 smoke 使用 `deepseek-v4-pro`、OpenAI compatible 和 `https://api.ai-native-x.site/v1` 成功返回提示式结构化对象；兼容修复位于 `dbdb23c`。
- 密钥只通过进程环境注入，未写入 `.env`、Git、日志或报告。
- 真实 smoke 只证明连接与结构化输出，不代表完成真实 PR 审查。
- 当前没有真实 PR 完整审查链接或真实 Benchmark 结果；五条公开数据仍为 `needs_review`。

## 验证结果

| 验证 | 结果 |
|---|---|
| 临时 Conda Python 3.12.13 + `pip install -e ".[agent,dev]"` | 通过；默认 Anaconda channels 因本机未接受 ToS 被拒绝，改用 conda-forge 成功；临时环境已清理 |
| Python 3.12 `pytest -q` | 183 passed，11.09 秒 |
| `python -m compileall -q reviewcrew benchmark` | 通过 |
| CLI help | `reviewcrew`、`review`、`replay` 参数入口通过 |
| Benchmark Fake quick | 5 案例完成，生成报告 |
| Benchmark Fake case | `sentry-offline-01` 单案例完成 |
| Benchmark Fake full | 5 个 ready fixture 完成 |
| Benchmark Real CLI | 按设计退出码 2，明确要求注入 `RealReviewRunner(executor=...)` |
| `pnpm test -- --run` | 6 个测试文件、25 项通过 |
| `pnpm build` | 60 个模块完成生产构建 |
| README 本地 Markdown 链接 | 全部目标存在 |
| Greptile Case Library | HTTP 200 |
| 五个公开 PR | GitHub REST API 逐条 HTTP 200；当前环境访问 HTML 页面连接被重置，报告已注明 |
| `git diff --check` | 通过，仅有 Git 的 LF→CRLF 提示，无 whitespace error |

## Git 与文件边界

- 本任务只提交 README、三份中文文档、`.env.example`、实施计划、Vite 测试移动和本报告。
- 不提交用户已有的 `design-doc.md` 删除、`doc/`、Task9 审查材料或 `frontend/task-12-review.md`。
- 未推送远端。

## 关注点

- README 中不存在 `reviewcrew --fake`：公开 CLI 没有该参数，离线 Fake 入口是全栈测试、前端 Demo Replay 和 Benchmark Fake。
- `--runner real` CLI 尚未接入执行器，文档明确写为未完成状态。
- Benchmark Fake 不生成 `runs/{run_id}/events.jsonl`，因此逐案例 Replay 标识为“无”，没有伪造 run ID。
- 生产部署需由反向代理保持前后端同源，Vite `/api` 代理只在开发服务器生效。
