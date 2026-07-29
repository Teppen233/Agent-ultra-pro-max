---
name: changed-line-localization
version: 1.0.0
roles: [defect, intent, verifier]
categories: [shared]
required_tools: [read_file_range, get_diff_context]
max_tool_calls: 2
---

# 修改行定位

## 适用条件
所有 Finding 提交前。

## 检查步骤
1. 验证 Finding 行号在修改行范围内。
2. 确认定位与实际修改内容相关。
3. 如果定位超出修改行，必须有充分理由。

## 停止条件
定位已验证。

## 常见误报
- 报告未修改行的已有问题
- 行号偏移超过 5 行

## 输出要求
行号定位精确到修改行。
