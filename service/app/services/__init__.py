"""AppSvc 层：业务逻辑 + 事务管理 + 即时级联。共 11 个，命名 XAppSvc。

  PlanAppSvc        Story1  规划确认（drafts -> 正式表 -> 删 drafts）
  ScheduleAppSvc    Story2  调度激活（多选专题 + managed/path + deadline -> 激活 + 即时级联）
  DailyAppSvc       Story3  今日计划（INSERT daily_records/daily_tasks/subtasks + 异步前置）
  TaskAppSvc        Story4A/4B/9  任务完成（即时级联 + 发事件）/ 物理删除 / 状态变更
  WeeklyAppSvc      Story6  周总结
  WorkspaceAppSvc   Story2  项目空间（managed=1 初始化 / managed=0 校验路径）
  SubtaskAppSvc     Story4B 前置/后置（后置和完成脱钩）
  ConfigAppSvc      Story7  子任务模板 CRUD（阶段级优先于专题级）
  AgentAppSvc       Story4A 主 Agent 进程管理（端口分配/心跳/重启/关机恢复）
  PushAppSvc        推送 + 重复判断（当日/当周已推则跳过）
  BoardAppSvc       Story9  H5 页面编辑（状态机校验 + 回退 + 即时级联）

铁律：
  - Service 不调用 LLM（LLM 交互由交互层 Skill 完成）
  - 事务内禁止 IO/HTTP；模式：写 DB + 即时级联 -> 提交 -> 异步 IO/HTTP
  - 确认类 API 仅做 DB 写 + 即时级联（<200ms），满足飞书 3 秒回调
"""
