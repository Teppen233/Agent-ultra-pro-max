---
name: pr-attribution
version: 1.0.0
roles: [verifier]
categories: [verification]
required_tools: [git_show, git_blame]
max_tool_calls: 2
---

# PR 归属验证

## 适用条件
验证 Finding 是否由当前 PR 引入。

## 检查步骤
1. 使用 git blame 检查可疑代码的作者。
2. 确认问题代码在 PR 修改范围内。
3. 如果问题是历史遗留，标记为 not_introduced_by_pr。

## 停止条件
归属确认。

## 常见误报
- 将历史问题归因到当前 PR

## 输出要求
明确 Finding 与当前 PR 的关联。
