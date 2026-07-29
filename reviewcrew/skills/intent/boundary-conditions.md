---
name: boundary-conditions
version: 1.0.0
roles: [intent]
categories: [logic]
required_tools: [read_file_range]
max_tool_calls: 3
---

# 边界条件检查

## 适用条件
PR 修改涉及循环、数组、集合操作或数值计算。

## 检查步骤
1. 检查循环边界是否正确（off-by-one）。
2. 检查空集合、null 值处理。
3. 检查数值溢出、除零风险。
4. 检查条件组合是否覆盖所有分支。

## 停止条件
所有边界已覆盖。

## 常见误报
- 框架已提供默认保护
- 输入已在更上层校验

## 输出要求
提供触发边界条件的输入示例。
