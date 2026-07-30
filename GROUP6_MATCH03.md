# Group 6 · Match 03

评委离线评分以本文件为入口。请在仓库根目录执行以下命令。

## 赛题

- 题目名称：AI 驱动的高端智能代码审查系统
- 题目来源：Group 6 · Match 03

## 成员与分工

| 成员 | 负责部分 | 贡献度 |
| --- | --- | ---: |
| 缪威 | 使用 Superpowers 编写设计文档，组织四人赛马；负责最终胜出方案的主要实现，并基于最终代码整理 PPT | 25% |
| 彭于轩 | 独立完成赛马方案，参与方案比较、功能验证和材料检查 | 25% |
| 高圣和 | 独立完成赛马方案，参与方案比较、测试验证和结果复核 | 25% |
| 林佳 | 独立完成赛马方案，参与方案比较、演示验证和材料完善 | 25% |

贡献度合计 100%。

## 运行说明

环境要求：

- Python 3.12+
- Git
- Node.js 20.19+、22.12+ 或更高的受支持版本
- pnpm 11
- 可选：Miniconda 或 Anaconda
- Windows、Linux 或 macOS

以下命令以 PowerShell 为例。Linux/macOS 请将 `Set-Location` 替换为 `cd`，并使用 `export NAME="value"` 设置环境变量。

首先确认运行环境：

```powershell
python --version
git --version
node --version
pnpm --version
```

使用 Conda 安装 Python 依赖：

```powershell
conda create -n reviewcrew python=3.12 -y
conda activate reviewcrew
python -m pip install -e ".[agent,dev]"
```

如果没有 Conda，也可以使用 Python 标准虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[agent,dev]"
```

Linux/macOS 激活标准虚拟环境时使用：

```bash
source .venv/bin/activate
```

安装前端依赖：

```powershell
pnpm --dir frontend install --frozen-lockfile
```

配置真实模型时，Key 从环境变量读取，不要写进代码：

```powershell
$env:REVIEWCREW_LLM_PROVIDER = "openai-compatible"
$env:REVIEWCREW_LLM_BASE_URL = "https://<model-service>/v1"
$env:REVIEWCREW_LLM_API_KEY = "<api-key>"
$env:REVIEWCREW_LLM_MODEL = "<model-name>"
```

Linux/macOS 使用：

```bash
export REVIEWCREW_LLM_PROVIDER="openai-compatible"
export REVIEWCREW_LLM_BASE_URL="https://<model-service>/v1"
export REVIEWCREW_LLM_API_KEY="<api-key>"
export REVIEWCREW_LLM_MODEL="<model-name>"
```

离线演示不需要模型 Key。启动前端：

```powershell
pnpm --dir frontend dev
```

打开 `http://127.0.0.1:5173`，点击“播放最佳离线回放”。该模式读取仓库内置事件，不需要后端、模型 Key 或外部网络。

如需启动完整前后端：

```powershell
# 终端一：后端
python -m uvicorn reviewcrew.server.app:app --host 127.0.0.1 --port 8000

# 终端二：前端
pnpm --dir frontend dev
```

真实 PR 审查。公开 PR 可以匿名读取，但频繁调用时建议配置只读 GitHub Token，以避免 API 限流：

```powershell
$env:REVIEWCREW_GITHUB_TOKEN = "<github-token>"
```

```powershell
python -m reviewcrew.cli review --pr https://github.com/OWNER/REPOSITORY/pull/123
```

## 自测结果

离线全链路测试：

```powershell
pytest tests/test_full_stack.py -v
```

本次实际输出：

```text
tests/test_full_stack.py::test_post_fake_orchestrator_sse_result_report_and_replay_match_frontend_contract PASSED
1 passed in 13.12s
```

Python 编译检查：

```powershell
python -m compileall -q reviewcrew benchmark
```

实际结果：退出码为 `0`。

前端测试与构建：

```powershell
pnpm --dir frontend test -- --run
pnpm --dir frontend build
```

本次实际结果：前端 `14` 个测试文件、`63` 个测试全部通过，生产构建成功。

## 设计说明

缪威先使用 Superpowers 编写统一设计文档，明确系统架构、Agent 分工、运行接口、测试标准和十分钟时间限制。随后四名成员按照同一设计分别实现方案并进行赛马，比较各方案的完整性、可运行性、测试情况和演示效果。

最终选用缪威实现的方案作为代码基线，并在此基础上完善前端、Replay、评测展示和 PPT。

系统以 PR diff 为中心，由 DefectAgent 和 IntentAgent 并行发现问题，再由独立的 VerifierAgent 验证和过滤误报，最后输出 JSON、中文 Markdown 报告和前端事件流。后端使用 FastAPI，前端使用 Vue 3，并提供离线 Replay，方便在没有网络或模型 Key 时演示。

设计文档位于：

- `docs/superpowers/specs/2026-07-29-reviewcrew-competition-design.md`
- `docs/superpowers/specs/2026-07-30-reviewcrew-frontend-operations-design.md`
- `docs/superpowers/specs/2026-07-30-reviewcrew-presentation-design.md`

## 参考文献 / 引用来源

- [Greptile AI Code Review Benchmarks](https://www.greptile.com/benchmarks)
- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [Vue.js 官方文档](https://vuejs.org/)
- [Pydantic AI 官方文档](https://ai.pydantic.dev/)
- [Semgrep 官方文档](https://semgrep.dev/docs/)

## 使用的模型

- [ ] DeepSeek-V4-Flash-Local
- [ ] glm-5.2-local

当前仓库实际配置并验证的是 OpenAI 兼容接口下的 `deepseek-v4-pro`，因此没有勾选与实际名称不一致的选项。
