# Task 9 审查修复 Round 1 报告

## 修复结果

- C1：Verifier 改为强制实例级 `expected_agent_ids`/`stop_event` 契约；新增多 Context 后到候选端到端测试，旧 watcher 不再静默降级。
- C2：移除报告阶段 `asyncio.to_thread`；同步等待生成结束，超预算后重建并原子提交最终 partial，返回前无后台写入。
- C3：新增统一脱敏模块；Publisher 只向 Mailbox 持久化脱敏副本，内存队列和 Blackboard 保留完整验证载荷；result、report、events 同步脱敏。
- I1：Verifier 失败终态仅在缺失时补发，真实 watcher 自行发布后不会重复事件。
- I2：`required_agents` 和 `shards` 转换为真实工作项；专家与静态分析受 `max_concurrency` semaphore 限制。
- I3：团队预算到期前发送 `budget_warning`，在有界 grace 内消费 `agent_snapshot`，阶段取消前保存快照。
- I4：自定义中文 ArgumentParser；缺参数、未知选项、非法子命令和帮助路径均由 `main()` 返回整数。
- M1：Planning 与 Verifier 分别使用独立可注入阶段预算。
- M2：最终 elapsed 覆盖报告生成阶段，并与磁盘结果一致。

## TDD 与验证

- 新增多 Context、强 watcher 契约、计划分片、并发上限、终态唯一、预算 snapshot、报告竞态、全目录脱敏及 argparse 错误测试。
- 专项：Orchestrator/CLI/Report/Mailbox/Verifier/Expert 共 `58 passed`。
- 最新全量：`pytest -q` → `108 passed in 8.16s`。
- `git diff --check` → 退出码 0。

## 提交边界

- 包含 Task 9 Orchestrator、CLI、Report、Mailbox/Publisher 脱敏边界、统一 redaction 模块及对应测试。
- 不包含 Task8 round2 的 `base.py`，不包含用户现有文档删除和未跟踪目录。
