"""测试数据工厂：建 goal/theme/phase/task 树（初始未开始/待执行）。"""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.goal import Goal
from app.models.phase import Phase
from app.models.task import Task
from app.models.theme import Theme


def make_tree(
    db: Session,
    *,
    n_themes: int = 1,
    phases_per_theme: int = 1,
    tasks_per_phase: int = 0,
    goal_status: str = "未开始",
) -> tuple[Goal, list[Theme], list[Phase]]:
    """建一棵 goal->themes->phases->tasks 树，全部初始状态。返回 (goal, themes, phases)。"""
    goal = Goal(id=str(uuid4()), name=f"goal-{uuid4().hex[:6]}", status=goal_status)
    db.add(goal)
    db.flush()
    themes: list[Theme] = []
    phases: list[Phase] = []
    for i in range(n_themes):
        theme = Theme(
            id=str(uuid4()),
            goal_id=goal.id,
            name=f"theme-{i}",
            type="learning",
            status="未开始",
        )
        db.add(theme)
        db.flush()
        themes.append(theme)
        for j in range(phases_per_theme):
            phase = Phase(
                id=str(uuid4()),
                theme_id=theme.id,
                sort_order=j + 1,
                name=f"phase-{i}-{j}",
                status="未开始",
            )
            db.add(phase)
            db.flush()
            phases.append(phase)
            for k in range(tasks_per_phase):
                task = Task(
                    id=str(uuid4()),
                    phase_id=phase.id,
                    sort_order=k + 1,
                    name=f"task-{i}-{j}-{k}",
                    status="待执行",
                    executor=None,
                )
                db.add(task)
    db.flush()
    return goal, themes, phases
