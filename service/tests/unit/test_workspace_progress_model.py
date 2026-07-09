"""Story4A 单元测试：workspace_progress model + CRUD。"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.workspace import Workspace
from app.models.workspace_progress import WorkspaceProgress
from tests._factory import make_tree


def _make_workspace(db):
    _, themes, _ = make_tree(db, n_themes=1, phases_per_theme=0)
    ws = Workspace(
        id=str(uuid4()),
        theme_id=themes[0].id,
        path=f"data/workspaces/{uuid4().hex[:8]}",
        managed=True,
        status="已就绪",
        type=themes[0].type,
    )
    db.add(ws)
    db.flush()
    return ws


def test_workspace_progress_create(db_session):
    """创建 workspace_progress 记录。"""
    ws = _make_workspace(db_session)
    wp = WorkspaceProgress(
        id=str(uuid4()),
        workspace_id=ws.id,
        date=date(2026, 7, 9),
        task_id=None,
        file_path="docs/schema-v1.md",
        file_type="design",
    )
    db_session.add(wp)
    db_session.flush()

    assert wp.created_at is not None
    assert wp.file_type == "design"


def test_workspace_progress_file_type_check(db_session):
    """file_type CHECK note/code/resource/exercise/design。"""
    ws = _make_workspace(db_session)
    wp = WorkspaceProgress(
        id=str(uuid4()),
        workspace_id=ws.id,
        date=date(2026, 7, 9),
        file_path="test.txt",
        file_type="invalid_type",
    )
    db_session.add(wp)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_workspace_progress_nullable_task_id(db_session):
    """task_id 可为 NULL。"""
    ws = _make_workspace(db_session)
    wp = WorkspaceProgress(
        id=str(uuid4()),
        workspace_id=ws.id,
        date=date(2026, 7, 9),
        task_id=None,
        file_path="notes.md",
        file_type="note",
    )
    db_session.add(wp)
    db_session.flush()
    assert wp.task_id is None


def test_workspace_progress_workspace_not_null(db_session):
    """workspace_id NOT NULL。"""
    wp = WorkspaceProgress(
        id=str(uuid4()),
        workspace_id="nonexistent",
        date=date(2026, 7, 9),
        file_path="test.md",
        file_type="note",
    )
    db_session.add(wp)
    with pytest.raises(IntegrityError):
        db_session.flush()
