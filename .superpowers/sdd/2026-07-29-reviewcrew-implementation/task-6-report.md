# Task 6 完成报告

## RED

命令：

```powershell
& 'C:\Users\SXF-Admin\miniconda3\envs\reviewcrew\python.exe' -m pytest tests/test_glm.py tests/test_agent_runtime.py tests/test_hooks.py tests/test_skill_registry.py -v
```

预期失败：收集阶段报出 `ModuleNotFoundError`，分别缺少 `reviewcrew.llm`、`reviewcrew.agents`、`reviewcrew.hooks` 与 `reviewcrew.skills`，证明测试覆盖的是尚未实现的运行时接口。

## GREEN

专项命令：

```powershell
& 'C:\Users\SXF-Admin\miniconda3\envs\reviewcrew\python.exe' -m pytest tests/test_glm.py tests/test_agent_runtime.py tests/test_hooks.py tests/test_skill_registry.py -v
```

结果摘要：12 passed。

全量命令：

```powershell
& 'C:\Users\SXF-Admin\miniconda3\envs\reviewcrew\python.exe' -m pytest -v
```

结果摘要：38 passed，3.04s。另已执行 `python -m reviewcrew.llm.glm --smoke`；未设置 `GLM_API_KEY` 时按要求输出中文说明并以状态码 1 退出，未访问网络。

## 改动清单

- 新增 GLM OpenAI 兼容模型构建器和显式 smoke 命令，避免密钥进入对象展示与日志。
- 新增共享 `Budget` Schema、可校验 Finding/Verdict 的 AgentRuntime，以及对 Mailbox/Blackboard 参数的兼容传递。
- 新增 TeamLead、HookManager、带 YAML 元数据和稳定哈希的 SkillRegistry，以及版本化 Prompt/Skill 文件。
- 新增四个专项测试文件，覆盖结构化输出、TestModel、请求上限、工具事件、Hook 容错/拒绝与 Prompt 选择顺序。

## 提交

提交 SHA：`42958a8`

## 自审问题

- `Budget` 已放入 `reviewcrew.schemas`，作为 Task 7 至 Task 9 可复用的公共契约；`reviewcrew.agents.base` 保持重新导出，避免导入路径分裂。
- AgentRuntime 按被调用 Agent 的签名选择性传递 Mailbox 与 Blackboard，为后续团队协作实现预留兼容接口。
- 已检查暂存内容不包含密钥或 `__pycache__`；工作区中预先存在的 `design-doc.md` 删除和 `doc/` 未暂存、未修改。

## 修复轮次 1

基线提交：`42958a8`。

- GLM 模型现在从 `Config` 读取温度、超时和重试；smoke 在仅设置 `GLM_API_KEY` 时使用 GLM 5.2 与 GLM 兼容端点，并支持离线替身测试。
- AgentRuntime 统一组装固定顺序的 Prompt，运行记录只保留 Prompt 文件哈希、Skill 名称/版本/哈希、模型名和输出 Schema；Team Lead 已接入该路径、预算和 Hook。
- 普通 PR 强制保留 Defect，安全 PR 强制保留 Defect 与 Intent；大 PR 在预算充足时按文件模块扩展语义分片，预算不足时保持已有分片。
- 依赖约束已收紧为 `pydantic-ai>=2.20,<3`；新增模型配置、smoke、运行审计、路由、分片、Hook 与 Skill 变更哈希测试。

验证：专项测试 20 passed；全量测试 46 passed（2.91s）。
