---
name: intent-vs-implementation
version: 1.0.0
roles: [intent]
categories: [business_logic]
required_tools: [read_file_range, search_project_docs]
max_tool_calls: 3
---

# 意图与实现比较

## 适用条件
任何 PR 审查。

## 检查步骤
1. 从 PR 描述和提交信息总结作者意图。
2. 分析实际代码变更的行为。
3. 比较意图和实现是否一致。
4. 检查关键路径是否被遗漏。

## 停止条件
意图和实现已对齐。

## 常见误报
- 仅命名不一致但语义正确
- 实现比描述更保守（安全选择）

## 输出要求
明确描述意图偏差和实际影响。
