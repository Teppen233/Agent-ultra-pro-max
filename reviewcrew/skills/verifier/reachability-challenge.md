---
name: reachability-challenge
version: 1.0.0
roles: [verifier]
categories: [verification]
required_tools: [read_file_range, search_code]
max_tool_calls: 3
---

# 可达性挑战

## 适用条件
验证每个候选 Finding 时。

## 检查步骤
1. 检查是否存在上游校验阻止攻击载荷。
2. 检查异常分支是否覆盖可疑路径。
3. 检查框架默认保护是否生效。
4. 尝试找到绕过检查的路径。

## 停止条件
可达性确认或排除。

## 常见误报
- 忽略框架中间件保护
- 忽略 try-except 分支

## 输出要求
明确说明代码路径是否可达。
