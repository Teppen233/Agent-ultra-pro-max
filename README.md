# ReviewCrew - AI Code Review 系统

以 Agent 为核心的 Git Pull Request 代码审查系统。两个专家 Agent（Defect + Intent）并行发现缺陷，独立 Verifier Agent 过滤误报，Vue 3 前端实时展示审查进度。

## 功能概述

| 功能 | 说明 |
|------|------|
| 双输入模式 | 支持 GitHub PR URL 和本地仓库 base/head 引用两种输入方式 |
| 并行专家审查 | DefectAgent（技术缺陷）和 IntentAgent（意图对齐）并行审查代码变更 |
| 独立验证 | VerifierAgent 对每个候选 Finding 进行 7 项独立验证，过滤误报 |
| 实时进度 | 基于 SSE 的 PipelineEvent 流，前端实时展示审查各阶段状态 |
| 事件回放 | Replay 模式支持历史运行回放和变速查看 |
| Benchmark 评测 | Greptile Benchmark 5 案例评测套件，文件/行号/语义三层命中判定 |
| Fake 模式 | 离线测试模式，不依赖 API Key 即可验证全流程 |

## 环境要求

- Python >= 3.12
- Node.js >= 18
- Git

## 快速开始

### 安装

```powershell
# 克隆仓库
git clone <repo-url>
cd Agent-ultra-pro-max

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -e ".[dev]"

# 配置环境变量
copy .env.example .env
# 编辑 .env 填入 LLM_API_KEY

# 前端
cd web
npm install
```

### 运行测试

```powershell
# 后端测试（81 tests）
pytest -q

# 前端测试
cd web && npm test -- --run

# 前端构建
npm run build
```

### CLI 使用

```powershell
# Fake 模式（离线，无需 API Key）
python -m reviewcrew.cli review --repo /path/to/repo --base main --head feature/x

# GitHub PR 模式
python -m reviewcrew.cli review --pr https://github.com/owner/repo/pull/1

# Replay 模式
python -m reviewcrew.cli replay --run-id abc123
```

### 启动服务

```powershell
# 后端 API（FastAPI + uvicorn）
uvicorn reviewcrew.server.app:app --reload

# 前端开发服务器（Vite）
cd web && npm run dev
```

### Benchmark 评测

```powershell
# Fake 模式快速评测
python -m benchmark.runner --mode quick --runner fake

# 单个案例评测
python -m benchmark.runner --case sentry-01 --runner fake

# 真实模型评测（需要 API Key）
python -m benchmark.runner --mode quick --runner live
```

## 架构

```
Vue 3 前端 (Vite)          Benchmark 评测
       |                        |
  SSE/HTTP                 runner.py
       |                        |
  FastAPI Server  <----  Orchestrator
  (app.py)                  (编排调度)
       |
  Pipeline 分阶段:
  1. PR Loader  -->  加载 PR 数据 (GitHub API / git diff)
  2. Diff Parser -->  解析 unified diff 为 ChangedFile/Hunk
  3. Context Builder -->  构建 ContextPack（封闭代码、相关文件、测试）
  4. Expert Agents -->  DefectAgent + IntentAgent 并行审查
  5. Dedupe       -->  确定性去重（文件+行号+类别）
  6. Verifier     -->  独立验证候选 Finding，产出 Verdict
  7. Report       -->  生成 Markdown/JSON 报告
```

### 组件说明

| 组件 | 路径 | 说明 |
|------|------|------|
| Config | `reviewcrew/config.py` | Pydantic Settings 全局配置，支持 .env |
| Schemas | `reviewcrew/schemas.py` | 全局领域模型（Finding, Verdict, ContextPack 等） |
| EventStore | `reviewcrew/events.py` | PipelineEvent 持久化，JSONL 格式 |
| CLI | `reviewcrew/cli.py` | 命令行入口，支持 review 和 replay 子命令 |
| Hooks | `reviewcrew/hooks.py` | 生命周期 hook 回调 |
| PR Loader | `reviewcrew/github/pr_loader.py` | GitHub API / 本地 git diff 两种加载方式 |
| Diff Parser | `reviewcrew/diff/parser.py` | Unified diff 逐行状态机解析 |
| Context Builder | `reviewcrew/context/builder.py` | Diff 中心上下文组装 |
| DefectAgent | `reviewcrew/agents/defect.py` | 技术缺陷发现专家 |
| IntentAgent | `reviewcrew/agents/intent.py` | 意图对齐发现专家 |
| VerifierAgent | `reviewcrew/agents/verifier.py` | 7 项独立验证专家 |
| Orchestrator | `reviewcrew/pipeline/orchestrator.py` | 阶段调度、超时控制、降级 |
| Dedupe | `reviewcrew/pipeline/dedupe.py` | 确定性去重（纯逻辑，无 LLM） |
| Report | `reviewcrew/pipeline/report.py` | Markdown 报告渲染 |
| Mailbox | `reviewcrew/team/mailbox.py` | Agent 间异步消息路由 |
| Blackboard | `reviewcrew/team/blackboard.py` | Agent 共享证据内存 |
| Tool Registry | `reviewcrew/tools/registry.py` | 只读工具注册和权限校验 |
| Safe Read | `reviewcrew/tools/files.py` | 安全文件读取（路径穿越防护） |
| Skills | `reviewcrew/skills/` | 12 个 MVP Skill markdown 文件 |
| Server | `reviewcrew/server/app.py` | FastAPI REST/SSE 接口 |

## 配置说明

所有配置通过环境变量或 `.env` 文件设置。复制 `.env.example` 为 `.env` 后修改。

### LLM 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `LLM_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | OpenAI 兼容端点 Base URL |
| `LLM_MODEL_NAME` | `glm-4-flash` | 模型名称 |
| `LLM_API_KEY` | (必填) | API Key |

### GitHub 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `GITHUB_TOKEN` | (可选) | GitHub Personal Access Token，公开仓库可不填 |

### 运行参数

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `REVIEWCREW_GLOBAL_TIMEOUT_SECONDS` | 600 | 单次审查全局超时（秒） |
| `REVIEWCREW_PR_LOAD_TIMEOUT_SECONDS` | 30 | PR 加载和 Diff 解析超时 |
| `REVIEWCREW_CONTEXT_TIMEOUT_SECONDS` | 90 | 上下文构建超时 |
| `REVIEWCREW_EXPERT_TIMEOUT_SECONDS` | 300 | 两专家并行审查超时 |
| `REVIEWCREW_VERIFIER_TIMEOUT_SECONDS` | 120 | Verifier 验证超时 |
| `REVIEWCREW_REPORT_TIMEOUT_SECONDS` | 30 | 报告生成超时 |
| `REVIEWCREW_MAX_CONCURRENT_EXPERTS` | 3 | 每个角色最多并发分片数 |
| `REVIEWCREW_RUNS_DIR` | `runs` | 运行记录持久化目录 |
| `REVIEWCREW_CONTEXT_PACK_CHAR_BUDGET` | 8000 | 单个 ContextPack 字符预算 |

### 各阶段超时之和不应超过全局超时的 2 倍（软校验，仅告警）

## 项目结构

```
reviewcrew/             # Python 后端包
  config.py             # 环境变量配置（Pydantic Settings）
  schemas.py            # 全局领域模型（Pydantic）
  events.py             # PipelineEvent 持久化（JSONL）
  cli.py                # CLI 入口
  hooks.py              # 生命周期 Hook 管理
  llm/                  # LLM 模型构建（OpenAI 兼容端点）
    glm.py              # 模型构建、Fake Model、Smoke Test
  github/               # GitHub 集成
    pr_loader.py        # PR 加载（GitHub API / 本地 Git）
  diff/                 # Diff 处理
    parser.py           # Unified diff 状态机解析
  context/              # 上下文构建
    builder.py          # ContextPack 组装
  tools/                # 只读工具
    files.py            # 安全文件读取
    registry.py         # 工具注册表和权限校验
  agents/               # Agent 实现
    base.py             # 基类、协议和 AgentRuntime
    defect.py           # DefectAgent（技术缺陷）
    intent.py           # IntentAgent（意图对齐）
    verifier.py         # VerifierAgent（独立验证）
    prompts/            # 中文系统提示词
      shared-system.md   # 共享系统提示词
      team-lead.md       # TeamLead 提示词
      defect.md          # DefectAgent 提示词
      intent.md          # IntentAgent 提示词
      verifier.md        # VerifierAgent 提示词
  pipeline/             # 审查管道
    orchestrator.py     # 编排器（阶段调度+超时控制）
    dedupe.py           # 确定性去重
    report.py           # Markdown 报告生成
  server/               # Web 服务
    app.py              # FastAPI 应用（REST + SSE）
    replay.py           # 事件回放逻辑
  skills/               # 12 个 MVP Skill 文件
    shared/             # 共享 Skill
    defect/             # DefectAgent Skill
    intent/             # IntentAgent Skill
    verifier/           # VerifierAgent Skill
    team-lead/          # TeamLead Skill
  team/                 # Agent 团队通信
    mailbox.py          # 类型化 Agent Mailbox
    blackboard.py       # 共享证据黑板
benchmark/              # Greptile Benchmark 评测
  models.py             # DatasetEntry / JudgeResult 数据模型
  judge.py              # 文件/行号/语义三层判定
  runner.py             # 评测运行器
  report.py             # 摘要生成
  dataset.yaml          # 5 案例数据集定义
tests/                  # pytest 测试（81 tests）
web/                    # Vue 3 前端
  src/
    contracts.ts        # 前端协议定义
    main.ts             # 入口
    router.ts           # 路由
pyproject.toml          # Python 项目配置
.env.example            # 环境变量示例
```

## 审查流程

### 输入

1. **GitHub PR 模式**：提供 `https://github.com/<owner>/<repo>/pull/<number>` 格式的 URL
   - 通过 GitHub REST API 获取 PR 元数据和 unified diff
   - 支持公开仓库无需 Token（建议配置以获得更高限流）

2. **本地仓库模式**：提供本地仓库路径 + base/head 引用
   - 执行 `git diff base...head` 生成 diff
   - 自动验证 ref 存在性
   - 离线可用，无需网络

### 阶段流程

1. **PR 加载**（30s 超时）：加载 PR 元数据，解析 unified diff 为 `ChangedFile` 列表
2. **上下文构建**（90s 超时）：围绕每个修改文件，收集封闭代码、同目录文件，构造 `ContextPack`
3. **专家审查**（300s 超时）：DefectAgent 和 IntentAgent 并行审查，产出候选 `Finding`
4. **去重**：确定性去重（基于文件+行号+类别，纯逻辑，无 LLM）
5. **验证**（120s 超时）：VerifierAgent 对每个候选进行 7 项验证：PR 引入、修改行定位、触发路径可达性、上游保护、重复、严重度合理性、证据充分性
6. **报告生成**（30s 超时）：生成 Markdown 和 JSON 格式审查报告，最多展示 8 条 Finding

### 输出

- `runs/{run_id}/events.jsonl`：完整 PipelineEvent 事件流
- `runs/{run_id}/result.json`：JSON 格式审查结果
- `runs/{run_id}/report.md`：Markdown 格式审查报告
- `runs/{run_id}/mailbox.jsonl`：Agent 间消息记录

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/reviews` | 启动审查（异步后台任务） |
| GET | `/api/reviews/{run_id}` | 查询审查状态 |
| GET | `/api/reviews/{run_id}/events` | SSE 实时事件流 |
| GET | `/api/reviews/{run_id}/report` | 获取审查报告 |
| GET | `/api/runs` | 历史运行列表 |
| GET | `/api/replays/{run_id}/events` | 事件回放（支持变速） |

## 故障排查

### 问题：`LLM_API_KEY 环境变量未设置`

**原因**：未配置 .env 文件或 API Key 为空。

**解决**：
```powershell
copy .env.example .env
# 编辑 .env 填入真实的 LLM_API_KEY
```

Fake 模式下不需要 API Key（CLI 默认使用 Fake Model）。

### 问题：`pydantic-ai 未安装`

**原因**：未安装项目开发依赖。

**解决**：
```powershell
pip install -e ".[dev]"
```

### 问题：`仓库路径不存在或不是 Git 仓库`

**原因**：指定的本地仓库路径不正确或不是有效的 Git 仓库。

**解决**：确认路径为包含 `.git` 目录的 Git 仓库根目录，或用 `git clone` 克隆目标仓库后指定该路径。

### 问题：`引用不存在`

**原因**：指定的 base 或 head 引用在本地仓库中不存在。

**解决**：执行 `git branch -a` 确认分支/标签名称，或先 `git fetch` 更新远程引用。

### 问题：`GitHub API 限流或权限不足 (HTTP 403)`

**原因**：无认证请求达到 GitHub API 限流上限（每小时 60 次）。

**解决**：设置 `GITHUB_TOKEN` 环境变量（限流提升至每小时 5000 次）。在 GitHub Settings > Developer settings > Personal access tokens 中创建 Token。

### 问题：`审查超时`

**原因**：审查超过了 `REVIEWCREW_GLOBAL_TIMEOUT_SECONDS` 指定的全局超时。

**解决**：增大 `REVIEWCREW_GLOBAL_TIMEOUT_SECONDS` 值；或调整上下文预算 `REVIEWCREW_CONTEXT_PACK_CHAR_BUDGET` 减少审查范围。

### 问题：前端 SSE 连接异常

**原因**：跨域或代理未正确配置。

**解决**：确保后端 uvicorn 在 `--reload` 模式运行，前端 `npm run dev` 配置 Vite 代理指向 `http://localhost:8000`。

## 开发

### 提交规范

- `feat:` 新功能
- `fix:` 修复
- `docs:` 文档
- `test:` 测试
- `refactor:` 重构
- `chore:` 杂务

### 分支策略

- `develop-1.1`：当前开发分支
- 功能分支从 `develop-1.1` 创建
- 合并前运行 `pytest -q` 确保 81 tests 全部通过

### Smoke Test（模型连通性测试）

```powershell
python -m reviewcrew.llm.glm
```

### 运行单个测试

```powershell
pytest tests/test_schemas.py -v
pytest tests/test_diff_parser.py -v
pytest tests/test_config.py -v
```

## 许可证

MIT
