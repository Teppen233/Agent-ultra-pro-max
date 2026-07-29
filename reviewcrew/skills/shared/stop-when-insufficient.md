---
name: stop-when-insufficient
version: 1.0.0
roles: [defect, intent, verifier]
categories: [shared]
required_tools: []
max_tool_calls: 1
---

# 证据不足时停止

## 适用条件
工具调用后依然无法收集足够证据。

## 检查步骤
1. 评估当前证据是否足够支撑 Finding。
2. 不足时标记为 uncertain。
3. 不要为了数量制造低质量 Finding。

## 停止条件
证据不足，输出 uncertain。

## 常见误报
- 强行发布证据不足的 Finding

## 输出要求
明确声明证据不足的原因。
