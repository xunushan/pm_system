# Architecture Decision Records

本项目架构决策记录（ADR）。每条记录一个难以反转、需上下文才理解、源于真实权衡的架构决策。

## 索引
| ADR                   | 决策                                       | 状态     |
| --------------------- | ------------------------------------------ | -------- |
| [ADR-001](ADR-001.md) | 状态变更即时级联                           | accepted |
| [ADR-002](ADR-002.md) | Skill 重构为 5 个原子能力                  | accepted |
| [ADR-003](ADR-003.md) | 今日计划由 LLM 决策                        | accepted |
| [ADR-004](ADR-004.md) | 事件即时 + 定时巡检兜底（Supervisor）      | accepted |
| [ADR-005](ADR-005.md) | 状态机扩充--已暂停态 + 有限回退            | accepted |
| [ADR-006](ADR-006.md) | 项目空间托管模式（managed 字段）           | accepted |
| [ADR-007](ADR-007.md) | 配置类操作不建 Skill                       | accepted |
| [ADR-008](ADR-008.md) | 状态看板载体--自研 H5 页面                 | accepted |
| [ADR-009](ADR-009.md) | pm-plan 职责收敛（仅沟通与产出）           | accepted |
| [ADR-010](ADR-010.md) | pm 主路由纯路由 + 预填 H5 链接             | accepted |
| [ADR-011](ADR-011.md) | 专题无序 + 阶段 roadmap 强约束             | accepted |
| [ADR-012](ADR-012.md) | executor 规划态不填，按专题 type 推断      | accepted |
| [ADR-013](ADR-013.md) | 时间字段精简（去专题时间）                 | accepted |
| [ADR-014](ADR-014.md) | 前置/后置只服务人执行任务                  | accepted |
| [ADR-015](ADR-015.md) | 去掉"需人工介入"终态                       | accepted |
| [ADR-016](ADR-016.md) | 前置按今日整体生成 + 与任务解耦            | accepted |
| [ADR-017](ADR-017.md) | 后置和任务完成脱钩                         | accepted |
| [ADR-018](ADR-018.md) | drafts 表用于确认前存储                    | accepted |
| [ADR-019](ADR-019.md) | 飞书卡片全生命周期归 Service 层            | accepted |
| [ADR-020](ADR-020.md) | opencode 进程模型--全局单进程 + 多 session | accepted |