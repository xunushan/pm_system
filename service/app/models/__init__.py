"""ORM model 汇总。

Alembic autogenerate 通过 `Base.metadata` 检测表结构——
**每实现一个表，在此 import 其 model 类**，否则 autogenerate 看不到它。

实现进度（按 Story 推进，逐个添加 import）：
  - goals               ✅ Story1  (app.models.goal)
  - themes              ⬜ Story1
  - phases              ⬜ Story1
  - tasks               ⬜ Story1
  - drafts              ⬜ Story1
  - workspaces          ⬜ Story2
  - daily_records       ⬜ Story3
  - daily_tasks         ⬜ Story3
  - workspace_progress  ⬜ Story4A
  - agent_processes     ⬜ Story4A
  - subtasks            ⬜ Story4B
  - status_change_log   ⬜ Story5
  - weekly_records      ⬜ Story6
  - subtask_templates    ⬜ Story7
"""

from app.models.goal import Goal

__all__ = ["Goal"]
