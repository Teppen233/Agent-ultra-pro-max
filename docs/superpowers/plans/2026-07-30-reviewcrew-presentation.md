# ReviewCrew Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一份可直接用于十分钟竞赛技术展示的 ReviewCrew PowerPoint，包含十页正文、三页答疑附录、真实前端截图、架构图、评测边界和逐页来源备注。

**Architecture:** 使用 `@oai/artifact-tool` 从零生成 16:9 PPTX，以 ReviewCrew 深蓝、青色和紫色产品风格为视觉基线。素材层负责真实截图与事实数据，内容层负责十三页叙事，验证层负责逐页渲染、溢出检测和视觉修订。

**Tech Stack:** JavaScript ES Modules、`@oai/artifact-tool`、PowerPoint、LibreOffice/Poppler 渲染辅助脚本、ReviewCrew Vue 前端截图。

## Global Constraints

- 正文十页必须可在十分钟内讲完；附录三页不计入正文时间。
- 画幅固定为 16:9，标题不小于 35pt，正文不小于 16pt。
- 使用当前仓库与真实本地页面作为产品事实来源，不制作虚构 UI。
- Fake quick 的 40% 只作为离线观察值，必须同时展示 `real_catch_rate = null`。
- 当前 GitHub 远程模式的文件、测试、符号与 Semgrep 降级边界必须如实说明。
- 每个外部来源或非平凡外部结论在对应幻灯片备注中加入 `[Sources]` 区块。
- 最终 PPTX 输出到 `deliverables/ReviewCrew-十分钟技术展示.pptx`，中间产物只存放于临时目录。

---

### Task 1: 建立 PPT 构建环境与素材清单

**Files:**
- Create: `.tmp/reviewcrew-presentation/source-notes.txt`
- Create: `.tmp/reviewcrew-presentation/slide-plan.txt`
- Create: `.tmp/reviewcrew-presentation/build-presentation.mjs`

**Interfaces:**
- Consumes: `README.md`、`docs/评测报告.md`、`docs/知识库维护方案.md`、当前本地前端。
- Produces: 绝对路径素材清单、十三页内容清单和可执行的 ES Module 构建入口。

- [ ] **Step 1:** 加载工作区依赖路径并初始化 Artifact Tool 工作目录。
- [ ] **Step 2:** 读取 Presentation Skill 要求的样式指南、Artifact Tool API 和默认布局资源。
- [ ] **Step 3:** 在 `source-notes.txt` 记录仓库文件、Greptile Benchmark URL 和截图来源。
- [ ] **Step 4:** 在 `slide-plan.txt` 固化十三页标题、单页主结论、素材类型和备注来源。
- [ ] **Step 5:** 创建只含依赖导入、主题常量和导出路径的 `build-presentation.mjs`。

### Task 2: 采集真实产品截图与视觉素材

**Files:**
- Create: `.tmp/reviewcrew-presentation/assets/start-page.png`
- Create: `.tmp/reviewcrew-presentation/assets/operations-room.png`
- Create: `.tmp/reviewcrew-presentation/assets/result-page.png`
- Create: `.tmp/reviewcrew-presentation/assets/benchmark-page.png`

**Interfaces:**
- Consumes: `http://127.0.0.1:5173` 与当前后端运行数据。
- Produces: 至少三张清晰的真实产品截图，供第 8、9 页使用。

- [ ] **Step 1:** 使用浏览器打开并检查启动页、运行页、结果页和 Benchmark 页面。
- [ ] **Step 2:** 选择不包含密钥、终端历史或个人信息的画面区域。
- [ ] **Step 3:** 保存高分辨率截图，并检查中文字体、裁剪和清晰度。
- [ ] **Step 4:** 若真实页面没有合适结果画面，使用仓库内离线 Replay，而不是合成虚构结果。

### Task 3: 实现主题、基础组件与来源备注

**Files:**
- Modify: `.tmp/reviewcrew-presentation/build-presentation.mjs`

**Interfaces:**
- Produces: `addTitle()`、`addFooter()`、`addSourceNotes()`、`addSectionLabel()` 和统一色彩、字体、页码规则。

- [ ] **Step 1:** 定义深蓝背景、青色主强调、紫色协作强调、白色正文和灰蓝辅助文本。
- [ ] **Step 2:** 实现标题、页脚、页码和章节标签函数。
- [ ] **Step 3:** 实现 `[Sources]` 备注写入函数，并验证备注不会显示在正文画布。
- [ ] **Step 4:** 生成一页测试幻灯片并导出，确认字体大小和 16:9 画幅。

### Task 4: 实现十页正文

**Files:**
- Modify: `.tmp/reviewcrew-presentation/build-presentation.mjs`

**Interfaces:**
- Consumes: Task 2 的真实截图和 Task 3 的主题组件。
- Produces: 第 1–10 页完整正文。

- [ ] **Step 1:** 制作极简封面与核心标语。
- [ ] **Step 2:** 制作传统工具缺口页，用三个高价值问题支撑结论。
- [ ] **Step 3:** 制作“高召回发现 → 独立反证 → 证据化发布”核心范式页。
- [ ] **Step 4:** 使用单张主架构图制作总体架构页，区分确定性代码与模型判断。
- [ ] **Step 5:** 制作 Diff 中心与 ContextPack 数据流页。
- [ ] **Step 6:** 制作 TeamLead、Defect、Intent、Verifier watcher 的流式并行拓扑页。
- [ ] **Step 7:** 制作 Mailbox、Blackboard、Skills、Hooks、工具链和 600 秒预算页。
- [ ] **Step 8:** 使用真实截图制作产品演示页，突出共享工具链、Agent 作战卡和事件流。
- [ ] **Step 9:** 制作 Greptile Benchmark 页，展示五语言、三层 Judge、Fake/Real 边界。
- [ ] **Step 10:** 制作竞争优势与总结页，收束到可验证、可回放、可控制的工程流水线。

### Task 5: 实现三页答疑附录

**Files:**
- Modify: `.tmp/reviewcrew-presentation/build-presentation.mjs`

**Interfaces:**
- Produces: 技术栈与 API、Finding 协议、已知边界与下一步三页附录。

- [ ] **Step 1:** 制作技术栈与五个主要 REST/SSE 接口页。
- [ ] **Step 2:** 制作 Finding、CodeEvidence 和 Verifier 裁决协议页。
- [ ] **Step 3:** 制作远程上下文降级、真实 Benchmark 待办和下一步只读 checkout 页。

### Task 6: 导出、渲染与视觉修订

**Files:**
- Create: `deliverables/ReviewCrew-十分钟技术展示.pptx`
- Create: `.tmp/reviewcrew-presentation/rendered/slide-*.png`
- Create: `.tmp/reviewcrew-presentation/montage.png`
- Create: `.tmp/reviewcrew-presentation/qa-ledger.txt`

**Interfaces:**
- Consumes: 完整 `build-presentation.mjs`。
- Produces: 经视觉验收的最终 PPTX。

- [ ] **Step 1:** 执行构建脚本并导出 PPTX。
- [ ] **Step 2:** 使用 `render_slides.py` 渲染全部十三页。
- [ ] **Step 3:** 使用 `create_montage.py` 检查整体节奏与相邻页面轮廓变化。
- [ ] **Step 4:** 逐页全尺寸检查标题换行、正文溢出、截图裁剪、连接线穿越和元素遮挡。
- [ ] **Step 5:** 使用 `slides_test.py` 检查画布溢出。
- [ ] **Step 6:** 将问题记录到 `qa-ledger.txt`，修复后重新导出与渲染，直到无未解决问题。
- [ ] **Step 7:** 核对十三页来源备注、正文时间和事实边界。

### Task 7: 最终验证与本地提交

**Files:**
- Add: `deliverables/ReviewCrew-十分钟技术展示.pptx`
- Add: `docs/superpowers/plans/2026-07-30-reviewcrew-presentation.md`
- Modify: `docs/superpowers/specs/2026-07-30-reviewcrew-presentation-design.md`

**Interfaces:**
- Produces: 可直接交付和本地版本化保存的演示文稿。

- [ ] **Step 1:** 确认 PPTX 可打开、十三页均可渲染、无溢出报告。
- [ ] **Step 2:** 确认产品截图、Fake 数据和真实评测边界与仓库一致。
- [ ] **Step 3:** 仅暂存设计、计划和最终 PPTX，不包含临时目录或用户其他文件。
- [ ] **Step 4:** 使用中文提交信息 `演示：制作十分钟技术展示PPT` 创建本地 Git 提交，不推送远程仓库。
