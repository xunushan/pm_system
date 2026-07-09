"""ORM model 汇总（自动发现）。

Alembic autogenerate 通过 `Base.metadata` 检测表结构。
model 类只有被 import 才会注册到 metadata。
本文件自动导入目录下所有 model 模块，无需手动添加 import，
**消除多 agent 并行开发时编辑此文件的冲突**。

新增 model：在 app/models/ 下新建 *.py 即可，无需改动本文件。

实现进度（按 Story 推进）：
  - goals               ✅ Story1  (app/models/goal.py)
  - themes              ✅ Story1  (app/models/theme.py)
  - phases              ✅ Story1  (app/models/phase.py)
  - tasks               ✅ Story1  (app/models/task.py)
  - drafts              ✅ Story1  (app/models/draft.py)
  - workspaces          ✅ Story2  (app/models/workspace.py)
  - daily_records       ✅ Story3  (app/models/daily_record.py)
  - daily_tasks         ✅ Story3  (app/models/daily_task.py)
  - workspace_progress  ✅ Story4A (app/models/workspace_progress.py)
  - agent_processes     ✅ Story4A (app/models/agent_process.py)
  - subtasks            ✅ Story3 起建（前置 INSERT）；S4B 扩后置+完成逻辑
  - status_change_log   ✅ Story2 起建（forward）；S5 扩 pause/resume/revert
  - weekly_records      ⬜ Story6
  - subtask_templates   ⬜ Story7
"""

from importlib import import_module
from pathlib import Path

from app.db.base import Base  # noqa: F401  re-export for convenience

# 自动导入所有 model 模块，注册到 Base.metadata。
# 注意：必须用 .parent.glob —— __file__ 是文件，直接对文件调 glob 返回空。
_MODELS_DIR = Path(__file__).resolve().parent
for _f in _MODELS_DIR.glob("*.py"):
    if _f.stem != "__init__":
        import_module(f"app.models.{_f.stem}")

__all__ = ["Base"]
