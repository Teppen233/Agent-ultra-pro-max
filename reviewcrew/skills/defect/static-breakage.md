---
name: static-breakage
version: 1.0.0
roles: [defect]
categories: [static]
required_tools: [read_file_range, search_code]
max_tool_calls: 4
---

# 静态缺陷检测

## 适用条件
PR 修改涉及函数签名、导入、类型或配置变更。

## 检查步骤
1. 检查修改是否引入语法错误或类型不匹配。
2. 检查导入是否存在或路径正确。
3. 检查配置变更是否完整（如重命名一处但遗漏引用）。
4. 检查是否留下未完成的实现（TODO、pass、raise NotImplementedError）。

## 需要收集的证据
- 修改的函数签名和调用处
- import 语句和目标模块
- 配置文件的引用位置

## 停止条件
- 所有修改的静态元素已验证
- 或无法访问相关文件

## 常见误报
- 仅存在于测试文件中的未完成代码
- 类型注解变化不影响运行时

## 输出要求
每个 Finding 必须指出具体的不一致位置。
