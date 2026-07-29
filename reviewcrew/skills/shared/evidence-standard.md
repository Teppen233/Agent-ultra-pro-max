---
name: evidence-standard
version: 1.0.0
roles: [defect, intent, verifier]
categories: [shared]
required_tools: [read_file_range]
max_tool_calls: 2
---

# 证据标准

## 适用条件
每个候选 Finding 提交前必须通过此检查。

## 检查步骤
1. Finding 必须至少包含一条代码证据。
2. 至少一条证据来自 PR 修改文件。
3. 证据内容必须与 Finding 描述一致。
4. 行号定位必须精确到修改行。

## 停止条件
- 证据满足最低标准
- 或无法收集足够证据，标记为 uncertain

## 常见误报
- 不要用非修改文件的代码作为主要证据
- 不要使用不相关的代码片段

## 输出要求
- 每条证据包含文件路径、行号和内容
