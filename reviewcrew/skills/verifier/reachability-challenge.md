---
name: "reachability-challenge"
version: "1.0.0"
roles: ["verifier"]
risks: []
estimated_seconds: 4
priority: 10
---

适用条件：候选声称某个输入或状态能够触发修改行。

检查触发入口、必要前置状态、分支条件与目标行之间是否存在连续可达路径；需要保留入口和修改行证据。任一必要条件不可满足时停止并拒绝。常见误报是只看到危险语句，却没有证明真实调用路径能够到达。输出只包含公开结论和证据摘要。
