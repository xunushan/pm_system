---
版本: v1.0
状态: accepted
更新: 2026-07-16
---

# opencode 验证（serve 集成行为）

> opencode serve 集成验证事实。


## 验证事实

### opencode serve session 管理
- **DELETE /session/:sessionID 退 session**：3 次验收不通过时退该 task 的 session，全局 serve 进程保留（服务其他 workspace）。用户可用 session_id 在本地接管。
- **session 复用**："/pm 确认完成" 后系统重新建/复用 session 驱动后续任务。
- **实现**：`service/app/clients/opencode.py` `delete_session`。决策依据 D26。

> 待补验证：dispatch 真实执行超时（PROGRESS 未实测项：opencode 执行 learning 任务 httpcore.ReadTimeout 300s）、session 生命周期、产出回调链路。后续 e2e 补充于此。

## 官方文档链接

| 主题                                                    | 链接                             |
| ------------------------------------------------------- | -------------------------------- |
| opencode serve API（含 DELETE /session/:id 退 session） | https://opencode.ai/docs/server/ |
