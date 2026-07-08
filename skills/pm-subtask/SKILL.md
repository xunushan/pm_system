---
name: pm-subtask
description: 前置/后置子任务生成 Skill（只服务人执行任务，智能体执行）。type 参数区分：pre=今日整体前置（与任务解耦），post=单个任务后置（和完成脱钩，可全取消）。
---

# pm-subtask - 前置/后置生成

> 对应文档：doc/05_Skill设计文档_v2.0.md「pm-subtask」、doc/01 Story3/4B、doc/02 2.5

## 职责
前置/后置**只服务人执行任务**（智能体任务不生成），都由 LLM 生成（Service 不调 LLM），都智能体执行（opencode run）。

### type=pre（前置，今日整体）
- pm-daily 调用，按**今日整体**生成（不按单个任务），与任务解耦
- 任务勾选变化**不触发前置重生成**（D22）

### type=post（后置，单个任务）
- 用户 `/pm 完成 [任务]` 触发
- 调 Service 标记完成 + 即时级联（任务此时已完成，后置**和完成脱钩**，D23）
- LLM 生成后置清单 -> 后置勾选卡片（用户可**全取消**）-> 确认后置 -> 异步 opencode run 执行

## 铁律
- 后置和完成脱钩：完成即时级联，后置可选收尾（8.21）
- 模板合并：阶段级优先于专题级，同名去重（8.12 / 2.18）
- `/pm 确认完成`（4A 验收通过）**不进 pm-subtask**（无后置），直接调 `POST /tasks/{id}/confirm-complete`

## 关键 Service 接口
- `POST /tasks/{id}/post-confirm`（后置确认，可全取消）
- 子任务模板查询（合并后）

详见 doc/04_服务API文档_v2.0.md 子任务节、doc/06 操作流程。
