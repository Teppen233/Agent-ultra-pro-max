---
name: trace-untrusted-input
version: 1.0.0
roles: [defect]
categories: [security]
required_tools: [search_code, read_file_range]
max_tool_calls: 4
---

# 不可信输入追踪

## 适用条件
PR 修改涉及用户输入、HTTP 参数、文件上传、外部 API 数据。

## 检查步骤
1. 识别修改中新增的输入来源。
2. 追踪输入是否经过校验、过滤或转义。
3. 检查是否直接拼接到 SQL、命令、HTML 或文件路径。
4. 检查是否存在 SSRF、注入或路径穿越风险。

## 停止条件
- 所有输入路径已追踪
- 或输入校验链完整

## 常见误报
- 已存在上游中间件校验
- 仅内部使用的 API

## 输出要求
必须说明攻击载荷如何到达目标代码。
