---
name: pm-summary
description: 日/周总结 Skill。日终总结已退化为纯回顾（级联已即时完成），仅写 daily.md/weekly.md 快照 + 标记 is_confirmed。异议修正走卡片直接改状态（双向，不弹确认）。
---

# pm-summary - 日/周总结

> 对应文档：doc/05_Skill设计文档_v2.0.md「pm-summary」、doc/01 Story5/6、doc/03 8.7

## 职责
- **日终总结（Story5）**：纯回顾。级联已即时完成，**不再执行级联**；仅写 daily.md 快照 + 标记 `daily_records.is_confirmed=1`
- **周总结（Story6）**：写 weekly.md 快照 + 标记 `weekly_records.is_confirmed=1`
- **异议修正**：用户对总结提出异议 -> 走卡片直接改状态（按钮动作形态，双向，直接改不弹确认）

## 铁律
- `daily_records.is_confirmed` 语义为**回顾确认标记**（非级联触发开关，8.7）
- 日终总结不再承担级联（级联即时化，02 变更1）
- 异议走卡片而非回聊（回聊识别有歧义）

## 推送重复判断（6.2/6.3）
- 日终总结提醒 21:00：查当日 is_confirmed，已确认跳过
- 周总结推送周日 12:00：查本周 weekly_records，已存在跳过

详见 doc/04_服务API文档_v2.0.md 日终/周总结节。
