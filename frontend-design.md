# ReviewCrew 前端设计方案（演示驾驶舱）

> 定位：不是后台管理系统，是"看得见 Agent 思考过程"的演示驾驶舱。
> 一切设计服务于 3 分钟演示视频的视觉冲击力。

---

## 1. 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 框架 | **Vue 3 + Vite + TypeScript** | 题目推荐栈，生态成熟，AI coding 生成质量高 |
| 状态 | **Pinia** | 官方推荐，管 pipeline 运行态 |
| 样式 | **Tailwind CSS** + 深色主题 | 演示视频必须深色，代码类产品的天然审美 |
| 组件库 | **Naive UI** | Vue3 原生、深色模式一流、无需引入重型 admin 风格 |
| 实时通信 | **SSE（EventSource）** | 后端 FastAPI 推流，比 WebSocket 简单，单向足够 |
| 图标 | **@iconify/vue** | 全量图标按需加载 |

## 2. 核心依赖组件清单

| 用途 | 包 | 说明 |
|---|---|---|
| Diff 渲染 | **@git-diff-view/vue** | GitHub 风格 diff 视图，支持行级装饰（挂 finding 标记）；备选 v-code-diff |
| 代码高亮 | **shiki** | VSCode 同款高亮引擎，颜值天花板 |
| Agent 拓扑图 | **@vue-flow/core** | 画 Orchestrator → 4 专家 Agent → Verifier 的 DAG，节点状态实时变色 |
| 图表 | **echarts + vue-echarts** | benchmark 仪表盘：命中率、分类矩阵热力图、耗时分布 |
| Markdown | **markdown-it** + shiki 插件 | 渲染最终审查报告 |
| 动效 | **@vueuse/motion** | 节点脉冲、finding 卡片入场动画 |
| 打字机流 | 自研 composable（~30 行） | Agent 思考文本逐字滚动 |

## 3. 页面结构（3 个页面就够）

### 3.1 主页面：审查驾驶舱 `/review`（视频 80% 镜头）

三栏布局：

```
┌────────────┬──────────────────────┬────────────────┐
│ 左栏 (20%) │    中栏 (45%)         │  右栏 (35%)     │
│            │                      │                │
│ PR 信息卡   │  Agent 拓扑图         │ Findings 流     │
│ 文件树      │  (Vue Flow DAG)      │ (卡片实时落下)   │
│ (变更文件+  │  ──────────────      │                │
│  finding   │  Agent 思考流         │ 每张卡片:       │
│  数量徽标)  │  (tab 切 4 个 agent,  │  severity 色条  │
│            │   打字机滚动 +        │  置信度环形图    │
│ 阶段进度条  │   工具调用气泡)       │  file:line     │
│ (5 阶段 +  │                      │  展开→推理/触发  │
│  倒计时)   │                      │  路径/修复建议   │
└────────────┴──────────────────────┴────────────────┘
```

**关键演示效果**：
- **拓扑图节点状态机**：待命(灰) → 运行中(蓝色脉冲动画) → 完成(绿) → 有发现(橙色徽标数字跳动)
- **Agent 思考流**：打字机效果滚动推理文本；工具调用渲染成气泡（🔍 read_file `auth.py` / 🕸️ find_references `verify_token`），一眼看出 Agent 在"主动查证据"
- **Verifier 淘汰动画**：被砍掉的 finding 卡片变灰划掉 + "已验证排除：该路径有上游校验兜底"——**这是压误报卖点的可视化，评委最吃这个**
- **10 分钟倒计时**：顶部时限进度条，强化"时效达标"印象

### 3.2 Diff 审查页 `/review/diff`
- @git-diff-view/vue 渲染 PR diff，命中行挂 severity 色块装饰
- 点击行内标记 → 侧滑抽屉展示完整 finding（推理、触发路径、修复建议、"采纳建议"按钮生成 GitHub comment 格式）
- 演示话术："精准锚定到行，直接变成 PR review comment"

### 3.3 Benchmark 仪表盘 `/benchmark`（视频结尾镜头）
- 大数字卡：**命中率 / 平均误报数 / 平均耗时**（三个达标指标）
- ECharts 热力图：5 仓库 × 6 缺陷类型命中矩阵
- 50 个 PR 结果表格：仓库、PR 链接、是否命中(✅/❌)、耗时、报告数
- 对比条形图：本系统 vs 传统工具（逻辑类漏洞覆盖率 <30% 那个背景数据可以拿来当对照）

## 4. 数据通道设计

后端 FastAPI 推 SSE 事件流，前端一个 store 消费：

```ts
type PipelineEvent =
  | { type: 'stage',   stage: 'preprocess'|'context'|'review'|'verify'|'report', status: 'start'|'done', elapsed: number }
  | { type: 'agent',   agent: 'security'|'logic'|'memory'|'arch'|'verifier', status: 'running'|'done' }
  | { type: 'thought', agent: string, text: string }                    // 思考流增量
  | { type: 'tool',    agent: string, tool: string, args: string }      // 工具调用气泡
  | { type: 'finding', payload: Finding }                               // 右栏落卡
  | { type: 'verdict', findingId: string, verdict: 'keep'|'reject', reason: string }  // 淘汰动画
  | { type: 'report',  markdown: string }
```

**⚠️ 录制视频的保命设计 —— Replay 模式**：
后端本来就全程落盘结构化日志（设计文档 §6），做一个 `GET /replay/{run_id}` 按原始时间戳（可 2x 加速）重放事件流。**录视频不依赖现场调 API**，不会翻车，还能挑一个最精彩的 run 反复录。这个功能优先级和驾驶舱本体一样高。

## 5. 视频 3 分钟分镜建议

| 时间 | 镜头 | 说的点 |
|---|---|---|
| 0:00-0:30 | 粘贴 PR 链接 → 点击审查 → 拓扑图亮起 | 流程极简，聚焦 diff |
| 0:30-1:30 | 驾驶舱全景：4 Agent 并行思考 + 工具调用气泡 + finding 落卡 | Agent 主动查证、跨文件推理 |
| 1:30-2:00 | Verifier 划掉两条误报 → Diff 页行级锚定 | 对抗验证压误报、精准到行 |
| 2:00-2:50 | Benchmark 仪表盘：命中率大数字 + 热力图 + PR 链接表 | 评测达标、真实数据 |
| 2:50-3:00 | 特点总结画面（§9 差异化表格做成一屏） | 收尾 |

## 6. 工程注意

- 所有动画走 CSS transform/opacity，避免重排卡顿影响录屏帧率
- 组件按页面懒加载，ECharts 按需引入
- 深色主题一把梭，不做浅色适配（演示用，别浪费时间）
- 先用 replay 假数据把 UI 全部开发完，再对接真后端 —— 前后端完全解耦并行开发
