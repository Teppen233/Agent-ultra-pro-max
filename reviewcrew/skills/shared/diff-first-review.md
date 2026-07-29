---
name: diff-first-review
version: 1.0.0
roles: [defect, intent, verifier]
categories: [shared]
required_tools: [read_file_range, get_diff_context]
max_tool_calls: 3
---

# Diff 优先审查

## 适用条件
任何 PR diff 审查的第一步。

## 检查步骤
1. 通读所有 diff hunk，理解修改范围。
2. 标记修改行和周边代码的关系。
3. 识别修改涉及的关键符号（函数、类、变量）。
4. 只在修改行中发现可疑模式时使用工具读取更多代码。

## 需要收集的证据
- 修改行的直接上下文
- 修改符号的定义和使用位置

## 停止条件
- 已理解所有修改意图
- 或者没有更多修改行需要检查

## 常见误报
- 不要报告未修改行的纯风格问题
- 不要在已经存在的问题上创建 Finding

## 输出要求
- 每个 Finding 必须包含修改行号
- 引用具体的 diff hunk
