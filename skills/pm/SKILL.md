---
name: pm
description: 目标管理系统主路由 Skill。识别 /pm 前缀，纯路由：生成类指令路由到子 Skill（pm-plan/pm-daily/pm-subtask/pm-summary），配置类指令由 LLM 提取参数生成预填 H5 链接（不调 Service）。
---

# pm - 主路由 Skill（纯路由）

> 对应文档：doc/05_Skill设计文档_v2.0.md「pm 主路由」、doc/03_系统架构文档_v2.0.md 1.2/2.2

## 职责
pm 是**纯路由**，不做业务：
- **生成类**指令（规划 / 今日计划 / 完成 / 总结）-> 通过 `skill_view()` 调用子 Skill（子 Skill 内调 Service + LLM）
- **配置类**指令（配置子任务 / 关联项目空间）-> LLM 提取参数 -> 生成**预填 H5 链接**（不调 Service）

## 铁律
- pm **不直接调 Service**（D12）
- pm **不调 LLM 做业务生成**（只做配置类的参数提取 + 拼链接）
- 配置态走 H5 页面 CRUD，不建 Skill（8.13）

## 路由表（TODO 实现）
| 指令 | 路由 |
|------|------|
| `/pm 规划` | -> pm-plan |
| `/pm 今日计划` | -> pm-daily |
| `/pm 完成 [任务]` | -> pm-subtask（后置生成，type=post） |
| `/pm 确认完成` | -> 直接调 Service `POST /tasks/{id}/confirm-complete`（不进 pm-subtask，无后置） |
| `/pm 总结` | -> pm-summary |
| `/pm 配置子任务` | -> 生成预填 H5 链接（config 页面） |
| `/pm 关联项目空间` | -> 生成预填 H5 链接（workspaces 页面） |

详见 doc/06_操作流程与技术动作清单_v2.0.md 指令表。
