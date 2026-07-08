---
name: pm-daily
description: 今日计划决策 Skill。Service 任务池预查询 -> LLM 决策候选任务 + 推断 executor（按专题 type）-> 调 pm-subtask 生成今日整体前置 -> 卡片（任务勾选 + 前置勾选两组独立）。
---

# pm-daily - 今日计划

> 对应文档：doc/05_Skill设计文档_v2.0.md「pm-daily」、doc/01 Story3、doc/03 7.3

## 职责
1. **任务池预查询**：Service 查已激活阶段（`phases.activated_at` 有值，排除已暂停）-> 推荐任务
2. **LLM 决策候选**：生成今日候选任务，展示形态 `任务名（阶段名(deadline)）[executor]`
3. **executor 推断**：按专题 type（learning/research/source -> human；dev/survey -> agent）
4. **调 pm-subtask 生成今日整体前置**（type=pre，整体生成，与任务解耦，D22）
5. **发卡片**：候选任务勾选 + 前置勾选（**两组独立勾选**）
6. 用户勾选 + 确认 -> Service `POST /daily/confirm` -> INSERT daily_records/daily_tasks/subtasks（前置）-> 异步执行前置

## 铁律
- 每日计划过滤用 `phases.activated_at`，**不用** goals.scheduled_start_date（6.5）
- 前置**按今日整体生成**，与任务解耦（8.21）
- 任务勾选变化**不触发前置重生成**（Service 不调 LLM，8.21）
- 推送重复判断：当日已有 daily_records 则跳过（6.1）

## executor 推断规则（8.20）
| 专题 type | executor |
|-----------|----------|
| learning / research / source | human |
| dev / survey | agent |

详见 doc/04_服务API文档_v2.0.md 今日计划节。
