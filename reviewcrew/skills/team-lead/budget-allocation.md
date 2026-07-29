---
name: budget-allocation
version: 1.0.0
roles: [team_lead]
categories: [planning]
required_tools: []
max_tool_calls: 1
---

# 预算分配

## 适用条件
生成 ReviewPlan 和运行时。

## 检查步骤
1. 估算每个分片的复杂度。
2. 按复杂度分配时间预算。
3. 预留 Verifier 和报告生成的时间。
4. 剩余预算不足时限制分片数。

## 停止条件
预算分配完成。

## 常见误报
无

## 输出要求
各分片预算和时间限制。
