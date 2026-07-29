---
name: "severity-calibration"
version: "1.0.0"
roles: ["verifier"]
risks: []
estimated_seconds: 3
priority: 40
---

适用条件：候选通过基本可达性与归因检查。

根据可利用条件、影响范围、数据敏感度和恢复难度校准严重度与置信度；需要引用已验证的触发条件和影响证据。证据只能支持较低等级时下调，不得为了显著性上调。常见误报是把理论影响当成真实可达影响。输出最终严重度、置信度和简短理由。
