---
name: "duplicate-check"
version: "1.0.0"
roles: ["verifier"]
risks: []
estimated_seconds: 2
priority: 50
---

适用条件：共享事实中已有其他候选或裁决。

仅当文件相同、定位重叠、类别相同且触发机制相同时判断重复；比较公开证据并保留更高置信度候选。任一条件不同即停止重复判断。常见误报是把同一行上的不同攻击路径或业务条件合并。输出只说明重复关系，不复制其他 Agent 的隐藏内容。
