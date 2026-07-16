---
版本: v2.0
状态: accepted
更新: 2026-07-16
---

# 目标管理系统 - 服务 API 文档

> 本文档只定义接口格式，不讨论实现细节。

# 一、API 清单

## 1.1 按模块分类

| 模块 | API 路径 | 方法 | 说明 | 对应 Story |
|------|----------|------|------|-----------|
| **通用** | `/api/v1/drafts` | POST | 创建草稿（pm-plan 确认前存储规划数据） | Story 1 |
| | `/api/v1/drafts/{draftId}` | GET | 获取草稿 | Story 1 |
| | `/api/v1/drafts/{draftId}` | PUT | 更新草稿（乐观锁，逐专题追加） | Story 1 |
| | `/api/v1/drafts/{draftId}` | DELETE | 删除草稿 | Story 1 |
| **规划** | `/api/v1/plans/confirm` | POST | 确认方案（用 draft_id 读 drafts 写正式表 + 删 drafts + 给 H5 链接） | Story 1 |
| **调度** | `/api/v1/schedules/confirm` | POST | 确认调度（多选专题+managed/path+填 deadline，即时级联+managed 分支初始化） | Story 2 |
| | `/api/v1/schedules/activate` | POST | 阶段衔接激活 | Story 8 |
| **每日计划** | `/api/v1/daily/plans/pool` | GET | 今日任务池预查询（供 pm-daily LLM） | Story 3 |
| | `/api/v1/daily/confirm` | POST | 确认今日计划（任务勾选+前置勾选） | Story 3 |
| **日终总结** | `/api/v1/daily/summary/generate` | GET | 生成日终总结（只读，状态已即时级联） | Story 5 |
| | `/api/v1/daily/summary/confirm` | POST | 确认日终总结（不级联，仅写快照） | Story 5 |
| **周总结** | `/api/v1/weekly/summary/generate` | GET | 生成本周总结（只读） | Story 6 |
| | `/api/v1/weekly/summary/confirm` | POST | 确认周总结 | Story 6 |
| **任务** | `/api/v1/tasks` | GET | 查询任务列表 | Story 4 |
| | `/api/v1/tasks/{taskId}` | GET | 获取任务详情 | Story 4 |
| | `/api/v1/tasks/{taskId}` | PATCH | 修正单条任务状态（日终异议，触发即时级联+刷新卡片） | Story 5 |
| | `/api/v1/tasks/{taskId}` | DELETE | **物理删除任务（v2.0 新增）** | Story 9 |
| | `/api/v1/tasks/{taskId}/complete` | POST | 标记任务完成（pm-subtask 内调，即时级联，不含后置） | Story 4B |
| | `/api/v1/tasks/{taskId}/confirm-complete` | POST | **4A 人工确认完成（v2.0 新增，即时级联，无后置）** | Story 4A |
| | `/api/v1/tasks/{taskId}/post-confirm` | POST | **4B 后置确认（v2.0 新增，可全取消）** | Story 4B |
| | `/api/v1/tasks/{taskId}/output/confirm` | POST | 验收通过（即时级联） | Story 4A |
| | `/api/v1/tasks/{taskId}/output/reject` | POST | 需要修改（重试/通知） | Story 4A |
| **工作空间** | `/api/v1/workspaces` | POST | 初始化工作空间（managed=1 分支） | Story 2 |
| | `/api/v1/workspaces/{workspaceId}` | GET | 获取工作空间详情（含 managed/path，H5 只读查看） | Story 9 |
| | `/api/v1/workspaces/{workspaceId}/link` | PUT | 关联已有路径（Story 2 卡片 A 调用，managed=0） | Story 2 |
| | `/api/v1/workspaces/{workspaceId}/progress` | GET | 获取工作空间进展 | Story 4/5 |
| | `/api/v1/workspaces/progress` | POST | 记录工作空间产出（回调） | Story 4A |
| **子任务** | `/api/v1/subtasks` | POST | 创建子任务 | Story 3/4 |
| | `/api/v1/subtasks/{subtaskId}` | GET | 获取子任务详情 | Story 3/4 |
| | `/api/v1/subtasks/{subtaskId}` | PATCH | 更新子任务状态 | Story 3/4 |
| **子任务模板** | `/api/v1/subtask-templates` | GET | 查询模板列表 | Story 7 |
| | `/api/v1/subtask-templates` | POST | 创建模板 | Story 7 |
| | `/api/v1/subtask-templates/{templateId}` | PUT | 更新模板 | Story 7 |
| | `/api/v1/subtask-templates/{templateId}` | DELETE | 删除模板（标记 inactive） | Story 7 |
| **统计** | `/api/v1/stats/daily` | GET | 获取日统计 | Story 5 |
| | `/api/v1/stats/weekly` | GET | 获取周统计 | Story 6 |
| | `/api/v1/stats/active-phases` | GET | 获取活跃阶段（排除已暂停，用 activated_at 过滤） | Story 3 |
| **H5 编辑** | `/api/v1/board/{entity}/{id}` | PUT | H5 字段编辑（名称/描述/deadline/executor/增删/排序） | Story 9 |
| | `/api/v1/board/{entity}/{id}/status` | POST | H5 状态变更（回退/暂停/恢复，含 reason + 即时级联） | Story 9 |
| **回调** | `/api/callback/opencode/output` | POST | OpenCode 产出回调 | Story 4A |
| | `/api/callback/opencode/timeout` | POST | Redis 超时告警回调 | Story 4A |

> **v2.0 移除**：`/webhook/bitable/record`（多维表格回调，改 H5 页面）；`/api/v1/plans/draft`（合并到 drafts）；`/api/v1/schedules/draft`（patch 卡片不需要草案）；`/api/v1/daily/draft`（无草案态）；`/api/v1/subtask-templates/download`、`/upload`（配置走 H5 页面，去文件上传下载）。

---

# 二、通用规范

## 2.1 请求/响应格式
- JSON 格式
- 时间：ISO 8601（`2026-07-06T08:30:00+08:00`）
- 日期：`YYYY-MM-DD`
- ID：UUID v4

## 2.2 响应结构

```json
{ "code": 0, "message": "success", "data": { ... } }
```

错误：
```json
{ "code": 1001, "message": "资源不存在", "data": null }
```

## 2.3 通用错误码

| 错误码 | 说明 |
|--------|------|
| 0 | 成功 |
| 1001 | 资源不存在 |
| 1002 | 参数错误（含 path 不存在） |
| 1003 | 状态冲突（阶段已激活、乐观锁冲突） |
| 1004 | 并发超限（全局进行中阶段 > 3） |
| 1005 | 状态回退/暂停需 reason |
| 1006 | 事务失败 |
| 1007 | 草稿已过期 |
| 2001 | OpenCode 调用失败 |
| 2002 | 工作空间初始化失败 |
| 3001 | 模板已存在 |
| 5000 | 内部错误 |

## 2.4 三入口约定

| 入口 | 端点 | 路径 | 说明 |
|------|------|------|------|
| A 聊天消息 | 8001 | Skill → REST API | 经 Hermes Agent + Skill |
| B 卡片回调 | 8002 | `/webhook/feishu/card` | 飞书卡片按钮，解析 action_id 硬编码路由 |
| C H5 页面 | 8001 | REST API | H5 页面调 Service，校验落库（无反向同步） |

---

# 三、API 详细设计

## 3.1 通用模块：草稿管理（drafts，pm-plan 确认前存储）

### POST /api/v1/drafts

**说明**：创建草稿。pm-plan 生成规划时调用，content 存完整规划 JSON（可达几十 KB）。

**请求**：
```json
{
  "user_id": "user_001",
  "story_type": "plan",
  "content": { "goal": {...}, "themes": [...], "phases": [...], "tasks": [...] },
  "expires_at": "2026-07-08T08:30:00+08:00"
}
```

**响应**：
```json
{
  "code": 0,
  "data": { "draft_id": "draft_001", "status": "pending", "created_at": "...", "expires_at": "..." }
}
```

### GET /api/v1/drafts/{draftId}
返回草稿详情（含 content、version）。

### PUT /api/v1/drafts/{draftId}

**说明**：更新草稿（乐观锁）。pm-plan 逐专题生成时追加内容。

**请求**：
```json
{ "content": {...}, "version": 1 }
```

**响应**：`{ "code": 0, "data": { "draft_id": "draft_001", "version": 2, "updated_at": "..." } }`

**错误**：version 不匹配返回 1003；过期返回 1007。

### DELETE /api/v1/drafts/{draftId}
删除草稿（确认后自动调用，或用户放弃）。

---

## 3.2 规划模块

### POST /api/v1/plans/confirm

**说明**：确认方案。确认按钮回调只传 draft_id（规避飞书回调 30KB 限制）。Service 用 draft_id 读 drafts，事务写入正式表，删 drafts，返回 H5 链接。Story 1 核心事务接口。

**请求**：
```json
{ "draft_id": "draft_001" }
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "goal_id": "goal_001",
    "goal_name": "具身智能算法岗面试准备",
    "themes_created": 4,
    "phases_created": 24,
    "tasks_created": 72,
    "draft_deleted": true,
    "h5_url": "https://pm.example.com/plan/goal_001"
  }
}
```

**事务内容**：
1. 读 drafts WHERE id = draft_id
2. INSERT goals（含 time_range、scheduled_start_date）
3. INSERT themes（无 sort_order/time_range）
4. INSERT phases（含 sort_order，无 deadline）
5. INSERT tasks（无 executor）
6. DELETE drafts WHERE id = draft_id
7. COMMIT
8. 异步：无（H5 链接直接返回）

> **规划态产出**：目标（名称+时间范围+scheduled_start_date+描述）、专题（名称+类型）、阶段（名称+sort_order，无 deadline）、任务（名称，无 executor）。

---

## 3.3 调度模块

### POST /api/v1/schedules/confirm

**说明**：确认调度。多选专题+设 managed/path（卡片 A）+ 填各阶段 deadline（卡片 B）。Story 2 核心事务接口。

**请求**：
```json
{
  "user_id": "user_001",
  "goal_id": "goal_001",
  "items": [
    {
      "theme_id": "theme_001",
      "managed": true,
      "phase_id": "phase_001",
      "deadline": "2026-07-15"
    },
    {
      "theme_id": "theme_002",
      "managed": false,
      "path": "/Users/me/interview",
      "phase_id": "phase_005",
      "deadline": "2026-07-20"
    }
  ]
}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "activated_phases": [
      {
        "phase_id": "phase_001",
        "name": "神经网络基础与 MLP",
        "deadline": "2026-07-15",
        "workspace_id": "ws_001",
        "workspace_managed": true,
        "workspace_status": "已就绪"
      },
      {
        "phase_id": "phase_005",
        "name": "算法基础",
        "deadline": "2026-07-20",
        "workspace_id": "ws_002",
        "workspace_managed": false,
        "workspace_status": "已就绪"
      }
    ],
    "scheduled_start_date": "2026-07-02",
    "bitable_synced": false
  }
}
```

**事务内容**：
1. 校验全局进行中 + 本次 ≤ 3（已暂停不占名额）
2. UPDATE phases SET status='进行中', activated_at=NOW(), deadline=...（多阶段）
3. 即时级联 themes/goals → 进行中
4. 写 status_change_log（forward, triggered_by='user'）
5. COMMIT（<200ms）
6. 异步：工作空间初始化（managed 分支）：
   - managed=1 → mkdir + git init + 骨架含规范文件
   - managed=0 → 校验 path 存在（不存在返回 1002），不创建任何文件，直接置已就绪

> **阶段自动锁定**：每个专题激活其 sort_order 最小的未开始阶段（强约束），客户端选专题时系统自动锁定阶段。
> **deadline 必填**。
> **scheduled_start_date 不在此设**（Story 1 已确认）。

### POST /api/v1/schedules/activate

**说明**：阶段衔接激活。Supervisor 推衔接卡片，用户确认激活下阶段时调用。Story 8。

**请求**：
```json
{
  "phase_id": "phase_002",
  "deadline": "2026-07-25"
}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "phase_id": "phase_002",
    "name": "卷积神经网络",
    "status": "进行中",
    "deadline": "2026-07-25",
    "workspace_id": "ws_003",
    "workspace_managed": true,
    "workspace_status": "已就绪"
  }
}
```

**事务内容**：
1. UPDATE phases SET status='进行中', activated_at=NOW(), deadline=...
2. 即时级联 themes/goals
3. 写 status_change_log（forward, triggered_by='supervisor'）
4. COMMIT
5. 异步：工作空间初始化（managed 分支）

---

## 3.4 每日计划模块

### GET /api/v1/daily/plans/pool

**说明**：今日任务池预查询（Service 代码，只读）。为 pm-daily LLM 决策提供结构化输入。过滤已激活阶段（activated_at 有值）+ 排除已暂停。

**查询参数**：`user_id`, `date`（可选）

**响应**：
```json
{
  "code": 0,
  "data": {
    "date": "2026-07-06",
    "yesterday_completed": [
      { "task_id": "task_001", "name": "反向传播推导", "phase_name": "MLP" }
    ],
    "yesterday_unconfirmed": false,
    "active_phases": [
      {
        "phase_id": "phase_001",
        "name": "神经网络基础与 MLP",
        "theme_name": "深度学习基础",
        "theme_type": "learning",
        "deadline": "2026-07-15",
        "progress": "3/6",
        "remaining_tasks": 3
      }
    ],
    "pending_tasks": [
      {
        "task_id": "task_004",
        "name": "优化器专题",
        "phase_id": "phase_001",
        "phase_name": "MLP",
        "phase_deadline": "2026-07-15",
        "theme_type": "learning"
      }
    ],
    "global_active_count": 2,
    "global_active_limit": 3
  }
}
```

> **用途**：pm-daily 接收此结构化任务池，LLM 决策候选任务 + 按专题 type 推断 executor。theme_type 用于推断 executor。

### POST /api/v1/daily/confirm

**说明**：确认今日计划。任务勾选 + 前置勾选（两组独立）。Story 3 核心事务接口。

**请求**：
```json
{
  "user_id": "user_001",
  "date": "2026-07-06",
  "task_ids": ["task_004", "task_005", "task_006"],
  "pre_subtasks": [
    { "name": "搜集优化器相关资料", "type": "前置" },
    { "name": "准备 PyTorch 开发环境", "type": "前置" }
  ]
}
```

> **前置按今日整体生成**（pm-subtask，不按单个任务），与任务解耦。只对 executor=人 的任务生成（pm-daily 推断后过滤）。

**响应**：
```json
{
  "code": 0,
  "data": {
    "daily_id": "daily_001",
    "date": "2026-07-06",
    "task_count": 3,
    "pre_subtask_count": 2,
    "async_triggered": true
  }
}
```

**事务内容**：
1. INSERT daily_records（已确认）
2. INSERT daily_tasks（勾选的）
3. INSERT subtasks（勾选的前置，待执行）
4. COMMIT（<200ms）
5. 异步：opencode run 执行前置；若勾选任务有 executor=智能体 → 启动 opencode serve

---

## 3.5 日终总结模块

### GET /api/v1/daily/summary/generate

**说明**：生成日终总结（只读，状态已即时级联）。

**查询参数**：`user_id`, `date`

**响应**：
```json
{
  "code": 0,
  "data": {
    "date": "2026-07-06",
    "daily_id": "daily_001",
    "is_confirmed": false,
    "completed_tasks": [
      { "task_id": "task_001", "name": "优化器专题", "theme_name": "深度学习基础" }
    ],
    "incomplete_tasks": [
      { "task_id": "task_003", "name": "数组专题 2 题", "theme_name": "面试准备" }
    ],
    "phase_health": [
      { "phase_id": "phase_001", "name": "MLP", "completed": 3, "total": 6, "rate": 0.5, "status": "进行中" }
    ],
    "active_phase_count": 2,
    "global_active_limit": 3
  }
}
```

### POST /api/v1/daily/summary/confirm

**说明**：确认日终总结。**不级联**（级联已即时完成），仅写快照 + 标记 is_confirmed。Story 5。

**请求**：`{ "daily_id": "daily_001" }`

**响应**：
```json
{
  "code": 0,
  "data": { "daily_id": "daily_001", "confirmed": true, "daily_md_path": "daily/2026-07-06.md" }
}
```

**事务**：UPDATE daily_records SET is_confirmed=1 → COMMIT → 异步写 daily.md。

---

## 3.6 周总结模块

### GET /api/v1/weekly/summary/generate

**说明**：生成本周总结（只读）。

**查询参数**：`user_id`, `week`

**响应**：
```json
{
  "code": 0,
  "data": {
    "week": "2026-W27",
    "date_range": { "start": "2026-06-30", "end": "2026-07-06" },
    "daily_stats": [...],
    "phase_health": [...],
    "agent_output_stats": { "total_files": 12, "by_type": {...} },
    "subtask_stats": { "pre": {...}, "post": {...} },
    "supervisor_linking_status": { "next_phase": "phase_002", "suggested_deadline": "2026-07-25" }
  }
}
```

> **下周建议参考 Supervisor 衔接状态**：pm-summary LLM 生成下周建议时参考 supervisor_linking_status。

### POST /api/v1/weekly/summary/confirm

**说明**：确认周总结。Story 6。

**请求**：`{ "week": "2026-W27" }`

**响应**：`{ "code": 0, "data": { "week": "2026-W27", "confirmed": true, "weekly_md_path": "weekly/2026-W27.md" } }`

**事务**：INSERT/UPDATE weekly_records SET is_confirmed=1 → COMMIT → 异步写 weekly.md。

---

## 3.7 任务模块

### GET /api/v1/tasks

**查询参数**：`user_id`（必填）、`phase_id`、`status`（待执行/已完成/已暂停）、`executor`、`date`

**响应**：
```json
{
  "code": 0,
  "data": {
    "tasks": [
      { "task_id": "task_001", "name": "反向传播推导", "status": "待执行", "executor": "human", "phase_name": "MLP", "theme_name": "深度学习基础", "retry_count": 0 }
    ],
    "total": 72, "filtered": 6
  }
}
```

### GET /api/v1/tasks/{taskId}

返回任务详情（含 executor，规划态可能为 null）。

### PATCH /api/v1/tasks/{taskId}

**说明**：修正单条任务状态（日终异议）。**触发即时级联** + 重新统计 + 刷新卡片。Story 5。

**请求**：
```json
{ "status": "已完成", "completed_at": "2026-07-06T18:00:00+08:00", "triggered_by": "user" }
```

**响应**：
```json
{
  "code": 0,
  "data": { "task_id": "task_001", "status": "已完成", "cascade": { "phase_completed": false } }
}
```

> **双向**：未完成↔已完成。即时级联。

### DELETE /api/v1/tasks/{taskId}（v2.0 新增）

**说明**：物理删除任务。H5 页面操作。Story 9。

**响应**：`{ "code": 0, "data": { "task_id": "task_001", "deleted": true } }`

### POST /api/v1/tasks/{taskId}/complete

**说明**：标记任务完成。pm-subtask 内部调用（4B 人完成任务时，pm-subtask 调此接口标记完成 + 即时级联，再生成后置）。不含后置。Story 4B。

**请求**：
```json
{ "user_id": "user_001" }
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "task_id": "task_001",
    "status": "已完成",
    "cascade": { "phase_completed": false, "theme_completed": false, "goal_completed": false }
  }
}
```

**事务**：
1. UPDATE tasks SET status='已完成', completed_at=NOW()
2. 写 status_change_log（forward, triggered_by='user'）
3. 即时级联检查（阶段→专题→目标）
4. 发阶段完成事件 → Supervisor 衔接（若阶段完成）
5. COMMIT

### POST /api/v1/tasks/{taskId}/confirm-complete（v2.0 新增）

**说明**：4A 人工确认完成。3 次重试不通过，用户手动接管处理后调用。即时级联，无后置。Story 4A。

**请求**：`{ "user_id": "user_001" }`

**响应**：
```json
{
  "code": 0,
  "data": {
    "task_id": "task_001",
    "status": "已完成",
    "cascade": { "phase_completed": false },
    "opencode_restarted": true,
    "next_agent_task": "task_002"
  }
}
```

**事务**：
1. UPDATE tasks SET status='已完成', completed_at=NOW()
2. 写 status_change_log
3. 即时级联
4. COMMIT
5. 异步：检测该工作空间是否还有待执行智能体任务，是→重启 opencode serve（不同端口）接管

### POST /api/v1/tasks/{taskId}/post-confirm（v2.0 新增）

**说明**：4B 后置确认。pm-subtask 生成后置清单后，用户勾选确认。可全取消。Story 4B。

**请求**：
```json
{
  "user_id": "user_001",
  "post_subtasks": [
    { "name": "笔记归档", "type": "后置" },
    { "name": "自测题生成", "type": "后置" }
  ]
}
```

> **可全取消**：post_subtasks 为空数组表示不要后置，任务仍是已完成。

**响应**：
```json
{
  "code": 0,
  "data": {
    "task_id": "task_001",
    "post_subtask_count": 2,
    "async_triggered": true
  }
}
```

**事务**：
1. INSERT subtasks（勾选的后置，待执行；全取消则不插入）
2. COMMIT
3. 异步：opencode run 执行后置（智能体执行）

### POST /api/v1/tasks/{taskId}/output/confirm

**说明**：验收通过智能体产出。即时级联。Story 4A。

**请求**：
```json
{ "user_id": "user_001", "workspace_progress_ids": ["wp_001", "wp_002"] }
```

**响应**：
```json
{
  "code": 0,
  "data": { "task_id": "task_001", "status": "已完成", "cascade": { "phase_completed": false } }
}
```

**事务**：
1. UPDATE tasks SET status='已完成', completed_at=NOW()
2. UPDATE subtasks（相关前置）SET status='已完成'
3. 写 status_change_log
4. 即时级联
5. 发阶段完成事件 → Supervisor
6. COMMIT

### POST /api/v1/tasks/{taskId}/output/reject

**说明**：退回智能体产出，重试或通知。Story 4A。

**请求**：
```json
{ "user_id": "user_001", "feedback": "Schema 字段不全，缺少 timestamp" }
```

**响应**（重试）：
```json
{
  "code": 0,
  "data": { "task_id": "task_001", "retry_count": 1, "max_retry": 3, "action": "retry", "async_triggered": true }
}
```

**响应**（超次）：
```json
{
  "code": 0,
  "data": {
    "task_id": "task_001",
    "retry_count": 3,
    "max_retry": 3,
    "action": "manual_intervention",
    "opencode_stopped": true,
    "workspace_path": "/Users/me/workspaces/mlp"
  }
}
```

> **3 次不通过不改状态**（去"需人工介入"），系统 opencode serve 退出，飞书通知 + 工作空间路径 + 建议手动启动。用户介入后调 `/tasks/{id}/confirm-complete`。

---

## 3.8 工作空间模块

### POST /api/v1/workspaces

**说明**：初始化工作空间（内部调用，managed=1 时）。骨架文件含规范文件（claude.md 类）。

**请求**：
```json
{
  "theme_id": "theme_001",
  "base_path": "~/workspaces/mlp",
  "skeleton_files": [
    { "path": "README.md", "template": "workspace_readme" },
    { "path": "claude.md", "template": "opencode_spec" }
  ]
}
```

**响应**：
```json
{
  "code": 0,
  "data": { "workspace_id": "ws_001", "theme_id": "theme_001", "path": "~/workspaces/mlp", "managed": true, "status": "已就绪", "created_files": ["README.md", "claude.md"] }
}
```

### GET /api/v1/workspaces/{workspaceId}

**说明**：获取工作空间详情（含 managed/path，H5 页面只读查看）。Story 9。

**响应**：
```json
{
  "code": 0,
  "data": {
    "workspace_id": "ws_001",
    "theme_id": "theme_001",
    "theme_name": "深度学习基础",
    "path": "~/workspaces/mlp",
    "managed": true,
    "status": "已就绪",
    "type": "learning",
    "created_at": "...",
    "last_heartbeat": "..."
  }
}
```

### PUT /api/v1/workspaces/{workspaceId}/link

**说明**：关联已有路径（managed=0）。Story 2 卡片 A 调用。激活后不能改 managed。

**请求**：
```json
{ "path": "/Users/me/projects/dl_notes", "managed": false }
```

**响应**：
```json
{
  "code": 0,
  "data": { "workspace_id": "ws_001", "theme_id": "theme_001", "path": "/Users/me/projects/dl_notes", "managed": false, "path_exists": true, "status": "已就绪" }
}
```

**错误**：path 不存在返回 1002。已激活专题改 managed 返回 1003。

> **managed=0 不创建任何文件**（包括规范文件），用户自己保证。

### GET /api/v1/workspaces/{workspaceId}/progress
获取工作空间文件快照（pm-subtask 后置生成时用）。

### POST /api/v1/workspaces/progress
记录工作空间产出（OpenCode 回调）。

---

## 3.9 子任务模块

### POST /api/v1/subtasks
创建子任务（前置/后置，由 pm-subtask 生成后调用）。

### GET /api/v1/subtasks/{subtaskId}
获取子任务详情。

### PATCH /api/v1/subtasks/{subtaskId}
更新子任务状态（异步执行完成后回调）。

---

## 3.10 子任务模板模块

### GET /api/v1/subtask-templates
查询模板列表（阶段级优先于专题级，同名去重）。

**查询参数**：`scope_type`、`scope_id`、`type`、`status`

### POST /api/v1/subtask-templates
创建模板（H5 页面，Story 7）。

### PUT /api/v1/subtask-templates/{templateId}
更新模板。

### DELETE /api/v1/subtask-templates/{templateId}
删除模板（标记 inactive）。

> **配置时不校验专题 type**（生成时自然跳过智能体任务）。

---

## 3.11 统计模块

### GET /api/v1/stats/daily
获取日统计（同 daily/summary/generate data）。

### GET /api/v1/stats/weekly
获取周统计（同 weekly/summary/generate data）。

### GET /api/v1/stats/active-phases

**说明**：获取当前活跃阶段（status='进行中'，排除已暂停，用 activated_at 过滤）。

**查询参数**：`user_id`

**响应**：
```json
{
  "code": 0,
  "data": {
    "active_phases": [
      { "phase_id": "phase_001", "name": "MLP", "theme_name": "深度学习基础", "deadline": "2026-07-15", "activated_at": "2026-07-01", "task_total": 6, "task_completed": 3 }
    ],
    "global_active_count": 2,
    "global_active_limit": 3
  }
}
```

---

## 3.12 H5 编辑模块

### PUT /api/v1/board/{entity}/{id}

**说明**：H5 页面字段编辑。已激活实体字段编辑/增删/排序。Story 9。

**路径参数**：`entity`（goal/theme/phase/task）、`id`

**请求**：
```json
{ "fields": { "deadline": "2026-07-28", "name": "卷积神经网络" } }
```

**响应**：
```json
{ "code": 0, "data": { "entity": "phase", "id": "phase_002", "updated_fields": ["deadline", "name"] } }
```

> **支持**：字段编辑（名称/描述/deadline/executor）、增删任务（物理删除）、阶段排序。**任务排序不支持**。

### POST /api/v1/board/{entity}/{id}/status

**说明**：H5 状态变更（回退/暂停/恢复）。校验状态机 + reason + status_change_log + 即时级联。Story 9。

**路径参数**：`entity`、`id`

**请求**：
```json
{ "to_status": "待执行", "reason": "标记错了，实际未完成", "triggered_by": "user" }
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "entity": "task",
    "id": "task_005",
    "from_status": "已完成",
    "to_status": "待执行",
    "change_type": "revert",
    "cascade": { "phase_pulled_back": true, "phase_id": "phase_001", "phase_from": "已完成", "phase_to": "进行中" },
    "audit_logged": true
  }
}
```

**校验与事务**：
1. 校验状态机（from→to 是否允许）
2. 校验 reason（revert/pause 必填，缺失返回 1005；resume 不填）
3. UPDATE status + status_changed_at
4. 写 status_change_log
5. 即时重算级联（revert 可能拉回上级进行中，forward 可能触发上级完成）
6. COMMIT

**change_type**：forward/pause/resume/revert/cascade

---

## 3.13 回调模块

### POST /api/callback/opencode/output

**说明**：OpenCode 产出回调。Story 4A。

**请求**：
```json
{
  "task_id": "task_001",
  "workspace_id": "ws_001",
  "outputs": [
    { "file_path": "docs/design/schema-v1.md", "file_type": "design", "summary": "消息 Schema 设计文档" }
  ],
  "exit_code": 0,
  "duration": 3600
}
```

**响应**：`{ "code": 0, "data": { "received": true, "progress_count": 1 } }`

> Service 收到回调后：记录 workspace_progress → DEL Redis 超时 key → 发验收卡片 + 发送产出文件到飞书。

### POST /api/callback/opencode/timeout

**说明**：Redis 超时告警回调（KeyExpirationEvent 触发）。

**请求**：
```json
{ "task_id": "task_001", "workspace_id": "ws_001", "timeout_at": "...", "expected_callback": "..." }
```

**响应**：`{ "code": 0, "data": { "alert_sent": true } }`

---

# 四、接口依赖关系

```
Story 1: 目标规划
  ├─ POST /drafts (pm-plan 逐专题生成追加)
  ├─ PUT /drafts/{id} (更新)
  └─ POST /plans/confirm (用 draft_id 读 drafts 写正式表 + 删 drafts + 给 H5 链接)
        ↓ 事务：INSERT goals/themes/phases/tasks + DELETE drafts

Story 2: 首次调度（含项目空间设置）
  └─ POST /schedules/confirm (多选专题+managed/path+deadline)
        ↓ 事务：UPDATE phases(进行中,activated_at,deadline) + 即时级联 + status_change_log
        ↓ 异步：工作空间初始化（managed 分支）
  注：managed=0 关联路径，调 PUT /workspaces/{id}/link（卡片 A 设）

Story 3: 当日计划
  ├─ GET /daily/plans/pool (Service 预查询)
  ├─ pm-daily LLM 决策 + 推断 executor + 调 pm-subtask 生成前置（整体）
  └─ POST /daily/confirm (任务勾选+前置勾选)
        ↓ 事务：INSERT daily_records/tasks/subtasks
        ↓ 异步：opencode run 前置 + opencode serve 智能体

Story 4A: 智能体执行
  ├─ POST /callback/opencode/output → 记录产出 + 发验收卡片 + 发送文件
  ├─ POST /tasks/{id}/output/confirm (验收通过，+即时级联)
  ├─ POST /tasks/{id}/output/reject (重试/通知，3次不通过进程退出)
  └─ POST /tasks/{id}/confirm-complete (人工确认完成，+即时级联+重启opencode接管)

Story 4B: 人执行任务
  ├─ /pm 完成 [任务] → pm-subtask
  │   ├─ POST /tasks/{id}/complete (标记完成+即时级联，脱钩)
  │   └─ 生成后置清单 (LLM)
  └─ POST /tasks/{id}/post-confirm (后置确认，可全取消)
        ↓ 异步：opencode run 后置

Story 5: 日终总结
  ├─ GET /daily/summary/generate (只读)
  ├─ PATCH /tasks/{id} (异议修正，+即时级联+刷新卡片)
  └─ POST /daily/summary/confirm (不级联，写快照)

Story 6: 周总结
  ├─ GET /weekly/summary/generate (只读，含 supervisor_linking_status)
  └─ POST /weekly/summary/confirm (写 weekly.md)

Story 7: 子任务配置
  └─ GET/POST/PUT/DELETE /subtask-templates (H5 页面 CRUD)

Story 8: 主动巡检与阶段衔接
  ├─ [事件] 阶段完成 → Supervisor 推衔接卡片
  ├─ POST /schedules/activate (确认激活下阶段)
  └─ [定时] Supervisor 巡检（scheduled_start_date/deadline/未总结/衔接未响应）

Story 9: 轻量编辑与状态回退
  ├─ PUT /board/{entity}/{id} (字段编辑)
  ├─ POST /board/{entity}/{id}/status (状态变更：回退/暂停/恢复，+即时级联)
  ├─ DELETE /tasks/{id} (物理删除)
  └─ GET /workspaces/{id} (只读查看 managed/path)
```
