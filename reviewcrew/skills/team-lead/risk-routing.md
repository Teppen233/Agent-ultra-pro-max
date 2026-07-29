---
name: risk-routing
version: 1.0.0
roles: [team_lead]
categories: [planning]
required_tools: []
max_tool_calls: 2
---

# 风险路由

## 适用条件
生成 ReviewPlan 时。

## 检查步骤
1. 分析 diff 文件类型和修改模式。
2. 识别安全相关修改 → 路由到 DefectAgent。
3. 识别业务逻辑修改 → 路由到 IntentAgent。
4. 两者均有 → 同时路由。

## 停止条件
路由计划完成。

## 常见误报
- 过度路由导致分片过多

## 输出要求
每个路由决策附理由。
