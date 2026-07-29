---
name: "pr-attribution"
version: "1.0.0"
roles: ["verifier"]
risks: []
estimated_seconds: 3
priority: 30
---

适用条件：候选已定位到某个问题行为。

比较变更前后行为，确认风险由当前 PR 新增或扩大，并要求定位与修改行相交。若问题完全存在于基准版本或只位于未修改代码，停止并拒绝。常见误报是把历史缺陷错误归因给当前作者。输出简述归因证据，不记录推理过程。
