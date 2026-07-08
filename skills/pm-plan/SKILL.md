---
name: pm-plan
description: 目标规划生成 Skill。与用户全程聊天沟通，逐专题生成目标/专题/阶段/任务，追加到 drafts；总览卡片触发写库，确认后给 H5 链接。
---

# pm-plan - 规划生成

> 对应文档：doc/05_Skill设计文档_v2.0.md「pm-plan」、doc/01 Story1、doc/03 7.2

## 职责
1. **提问引导**：问目标时间范围、scheduled_start_date（计划开始日，用于提醒激活）
2. **逐专题生成**：LLM 生成「目标 / 专题（无序）/ 阶段（roadmap 强约束）/ 任务」，**逐专题追加到同一个 draft**
3. **写 drafts**：调 Service `POST /drafts` 写入规划 JSON（content 存完整四层结构，可达几十 KB）
4. **总览卡片**：发概览卡片（<30KB）+ 确认按钮（action_value 只含 draft_id，规避飞书回调 30KB 限制）
5. 用户点确认 -> 回调（入口 B）只传 draft_id -> Service `POST /plans/confirm` 读 drafts -> 写正式表 -> 删 drafts -> 返回 H5 链接

## 铁律
- drafts **纯存储，不同步展示**（不进 H5 / 看板）
- drafts 乐观锁 version，24h 过期（8.4）
- 确认按钮只传 draft_id（8.18 数据量原则）
- executor 规划态**不填**（pm-daily 推断，8.20）

## 关键 Service 接口
- `POST /drafts` / `PUT /drafts/{id}` / `GET /drafts/{id}`
- `POST /plans/confirm`（draft_id -> 正式表）

详见 doc/04_服务API文档_v2.0.md 规划/drafts 节。
