"""Story7 单元测试：子任务模板 repository + ConfigAppSvc（合并规则 + CRUD）。

验收要点（doc/01 S7 / doc/02 2.6/2.18）：
  - repository：list 过滤、find_existing 预检、list_active_by_scope
  - create：成功 + UNIQUE(scope_id,type,name) 冲突 -> 3001
  - update：成功 + name 变更 3001 + status 切换
  - delete：标记 inactive（非物理删除，可恢复，幂等）
  - 合并规则：阶段级优先专题级，同名去重（阶段级为准），无顺序性
  - 配置不校验专题 type（智能体专题配也能存）
"""

from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError, NotFoundError, TemplateExistsError
from app.models.subtask_template import SubtaskTemplate
from app.models.task import Task
from app.repositories.subtask_template import SubtaskTemplateRepository
from app.schemas.subtask_template import (
    SubtaskTemplateCreateRequest,
    SubtaskTemplateUpdateRequest,
)
from app.services.config_app_svc import ConfigAppSvc
from tests._factory import make_tree

# ---- 辅助 ----


def _make_template(
    db,
    *,
    scope_type="phase",
    scope_id=None,
    type="前置",
    name="准备题目",
    description="desc",
    status="active",
):
    t = SubtaskTemplate(
        id=str(uuid4()),
        scope_type=scope_type,
        scope_id=scope_id or str(uuid4()),
        type=type,
        name=name,
        description=description,
        status=status,
    )
    db.add(t)
    db.flush()
    return t


# ===== Repository =====


class TestSubtaskTemplateRepository:
    def test_list_templates_no_filter(self, db_session):
        _make_template(db_session, name="a")
        _make_template(db_session, name="b")
        repo = SubtaskTemplateRepository(db_session)
        assert len(repo.list_templates()) == 2

    def test_list_templates_with_filters(self, db_session):
        phase_id = str(uuid4())
        theme_id = str(uuid4())
        _make_template(db_session, scope_type="phase", scope_id=phase_id, type="前置", name="a")
        _make_template(db_session, scope_type="phase", scope_id=phase_id, type="后置", name="b")
        _make_template(db_session, scope_type="theme", scope_id=theme_id, type="前置", name="c")
        _make_template(
            db_session,
            scope_type="theme",
            scope_id=theme_id,
            type="前置",
            name="d",
            status="inactive",
        )
        repo = SubtaskTemplateRepository(db_session)

        # scope_type + scope_id
        result = repo.list_templates(scope_type="phase", scope_id=phase_id)
        assert len(result) == 2

        # + type
        result = repo.list_templates(scope_type="phase", scope_id=phase_id, type="前置")
        assert len(result) == 1
        assert result[0].name == "a"

        # + status
        result = repo.list_templates(scope_type="theme", scope_id=theme_id, status="inactive")
        assert len(result) == 1
        assert result[0].name == "d"

    def test_find_existing(self, db_session):
        scope_id = str(uuid4())
        t = _make_template(db_session, scope_id=scope_id, type="前置", name="准备题目")
        repo = SubtaskTemplateRepository(db_session)

        found = repo.find_existing(scope_id=scope_id, type="前置", name="准备题目")
        assert found is not None
        assert found.id == t.id

        # 不存在
        assert repo.find_existing(scope_id=scope_id, type="前置", name="不存在") is None
        assert repo.find_existing(scope_id=scope_id, type="后置", name="准备题目") is None

        # 排除自身（更新时用）
        assert (
            repo.find_existing(scope_id=scope_id, type="前置", name="准备题目", exclude_id=t.id)
            is None
        )

    def test_list_active_by_scope(self, db_session):
        phase_id = str(uuid4())
        _make_template(db_session, scope_type="phase", scope_id=phase_id, type="前置", name="a")
        _make_template(
            db_session,
            scope_type="phase",
            scope_id=phase_id,
            type="前置",
            name="b",
            status="inactive",
        )
        _make_template(db_session, scope_type="phase", scope_id=phase_id, type="后置", name="c")
        repo = SubtaskTemplateRepository(db_session)

        result = repo.list_active_by_scope(scope_type="phase", scope_id=phase_id)
        assert len(result) == 2

        result = repo.list_active_by_scope(scope_type="phase", scope_id=phase_id, type="前置")
        assert len(result) == 1
        assert result[0].name == "a"


# ===== ConfigAppSvc: create =====


class TestConfigAppSvcCreate:
    def test_create_success(self, db_session):
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateCreateRequest(
            scope_type="phase",
            scope_id=str(uuid4()),
            type="前置",
            name="准备题目与代码框架",
            description="算法基础阶段",
        )
        data = svc.create_template(req)
        assert data.id is not None
        assert data.scope_type == "phase"
        assert data.type == "前置"
        assert data.name == "准备题目与代码框架"
        assert data.status == "active"

    def test_create_unique_conflict_returns_3001(self, db_session):
        scope_id = str(uuid4())
        _make_template(db_session, scope_id=scope_id, type="前置", name="准备题目")
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateCreateRequest(
            scope_type="phase",
            scope_id=scope_id,
            type="前置",
            name="准备题目",
        )
        with pytest.raises(TemplateExistsError) as exc_info:
            svc.create_template(req)
        assert exc_info.value.code == 3001
        assert exc_info.value.http_status == 409

    def test_create_invalid_scope_type(self, db_session):
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateCreateRequest(
            scope_type="goal",  # 非法
            scope_id=str(uuid4()),
            type="前置",
            name="x",
        )
        with pytest.raises(BadRequestError):
            svc.create_template(req)

    def test_create_invalid_type(self, db_session):
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateCreateRequest(
            scope_type="phase",
            scope_id=str(uuid4()),
            type="中间",  # 非法
            name="x",
        )
        with pytest.raises(BadRequestError):
            svc.create_template(req)

    def test_create_same_name_different_type_ok(self, db_session):
        """同 scope_id 下，不同 type 同 name 不冲突（UNIQUE 是 scope_id+type+name）。"""
        scope_id = str(uuid4())
        _make_template(db_session, scope_id=scope_id, type="前置", name="笔记归档")
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateCreateRequest(
            scope_type="phase",
            scope_id=scope_id,
            type="后置",  # 不同 type
            name="笔记归档",
        )
        data = svc.create_template(req)
        assert data.type == "后置"

    def test_create_does_not_validate_theme_type(self, db_session):
        """配置时不校验专题 type（doc/01 line 572）。

        即便 scope_id 指向一个智能体专题（type=dev），也能存模板。
        Service 不查 theme 表、不校验 theme.type。
        """
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateCreateRequest(
            scope_type="theme",
            scope_id="some-agent-theme-id",
            type="前置",
            name="智能体专题配的前置",
        )
        data = svc.create_template(req)
        assert data.status == "active"


# ===== ConfigAppSvc: update =====


class TestConfigAppSvcUpdate:
    def test_update_name_success(self, db_session):
        t = _make_template(db_session, name="旧名")
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateUpdateRequest(name="新名")
        data = svc.update_template(t.id, req)
        assert data.name == "新名"

    def test_update_description_success(self, db_session):
        t = _make_template(db_session, description="old")
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateUpdateRequest(description="new desc")
        data = svc.update_template(t.id, req)
        assert data.description == "new desc"

    def test_update_status_to_inactive(self, db_session):
        t = _make_template(db_session, status="active")
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateUpdateRequest(status="inactive")
        data = svc.update_template(t.id, req)
        assert data.status == "inactive"

    def test_update_name_conflict_returns_3001(self, db_session):
        scope_id = str(uuid4())
        _make_template(db_session, scope_id=scope_id, type="前置", name="模板A")
        t_b = _make_template(db_session, scope_id=scope_id, type="前置", name="模板B")
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateUpdateRequest(name="模板A")  # 冲突
        with pytest.raises(TemplateExistsError) as exc_info:
            svc.update_template(t_b.id, req)
        assert exc_info.value.code == 3001

    def test_update_name_same_as_self_no_conflict(self, db_session):
        """更新为同名（自身）不触发 3001。"""
        t = _make_template(db_session, name="原名")
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateUpdateRequest(name="原名")
        data = svc.update_template(t.id, req)
        assert data.name == "原名"

    def test_update_not_found(self, db_session):
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateUpdateRequest(name="x")
        with pytest.raises(NotFoundError):
            svc.update_template("nonexistent-id", req)

    def test_update_invalid_status(self, db_session):
        t = _make_template(db_session)
        svc = ConfigAppSvc(db_session)
        req = SubtaskTemplateUpdateRequest(status="deleted")  # 非法
        with pytest.raises(BadRequestError):
            svc.update_template(t.id, req)


# ===== ConfigAppSvc: delete =====


class TestConfigAppSvcDelete:
    def test_delete_marks_inactive(self, db_session):
        t = _make_template(db_session, status="active")
        svc = ConfigAppSvc(db_session)
        data = svc.delete_template(t.id)
        assert data.status == "inactive"
        # 非物理删除
        assert db_session.get(SubtaskTemplate, t.id) is not None

    def test_delete_idempotent(self, db_session):
        """已 inactive 的再删不报错（幂等）。"""
        t = _make_template(db_session, status="inactive")
        svc = ConfigAppSvc(db_session)
        data = svc.delete_template(t.id)
        assert data.status == "inactive"

    def test_delete_recoverable(self, db_session):
        """删除后可恢复（status 改回 active）。"""
        t = _make_template(db_session, status="active")
        svc = ConfigAppSvc(db_session)
        svc.delete_template(t.id)
        assert t.status == "inactive"
        # 恢复
        svc.update_template(t.id, SubtaskTemplateUpdateRequest(status="active"))
        assert t.status == "active"

    def test_delete_not_found(self, db_session):
        svc = ConfigAppSvc(db_session)
        with pytest.raises(NotFoundError):
            svc.delete_template("nonexistent-id")


# ===== 合并规则（doc/02 2.18）=====


class TestMergeRule:
    def test_phase_priority_over_theme(self, db_session):
        """阶段级优先于专题级，同名以阶段级为准。"""
        goal, themes, phases = make_tree(db_session, phases_per_theme=1)
        phase_id = phases[0].id
        theme_id = themes[0].id

        # 阶段级 + 专题级同名模板
        _make_template(
            db_session,
            scope_type="phase",
            scope_id=phase_id,
            type="前置",
            name="准备题目",
            description="阶段级描述",
        )
        _make_template(
            db_session,
            scope_type="theme",
            scope_id=theme_id,
            type="前置",
            name="准备题目",
            description="专题级描述",
        )
        svc = ConfigAppSvc(db_session)
        result = svc.list_merged(phase_id=phase_id, theme_id=theme_id, type="前置")
        assert len(result.templates) == 1
        # 阶段级优先
        assert result.templates[0].description == "阶段级描述"

    def test_merge_dedup_same_name_different_type_both_kept(self, db_session):
        """同名不同 type 不去重（前置和后置是不同模板）。"""
        goal, themes, phases = make_tree(db_session, phases_per_theme=1)
        phase_id = phases[0].id
        theme_id = themes[0].id

        _make_template(
            db_session, scope_type="phase", scope_id=phase_id, type="前置", name="笔记归档"
        )
        _make_template(
            db_session, scope_type="theme", scope_id=theme_id, type="后置", name="笔记归档"
        )
        svc = ConfigAppSvc(db_session)
        result = svc.list_merged(phase_id=phase_id, theme_id=theme_id)
        assert len(result.templates) == 2

    def test_merge_no_overlap(self, db_session):
        """阶段级和专题级无同名 -> 全部返回。"""
        goal, themes, phases = make_tree(db_session, phases_per_theme=1)
        phase_id = phases[0].id
        theme_id = themes[0].id

        _make_template(
            db_session, scope_type="phase", scope_id=phase_id, type="前置", name="阶段前置"
        )
        _make_template(
            db_session, scope_type="theme", scope_id=theme_id, type="前置", name="专题前置"
        )
        svc = ConfigAppSvc(db_session)
        result = svc.list_merged(phase_id=phase_id, theme_id=theme_id, type="前置")
        assert len(result.templates) == 2

    def test_merge_excludes_inactive(self, db_session):
        """合并查询只返回 active 模板。"""
        goal, themes, phases = make_tree(db_session, phases_per_theme=1)
        phase_id = phases[0].id
        theme_id = themes[0].id

        _make_template(
            db_session, scope_type="phase", scope_id=phase_id, type="前置", name="active"
        )
        _make_template(
            db_session,
            scope_type="phase",
            scope_id=phase_id,
            type="前置",
            name="inactive",
            status="inactive",
        )
        svc = ConfigAppSvc(db_session)
        result = svc.list_merged(phase_id=phase_id, theme_id=theme_id, type="前置")
        assert len(result.templates) == 1
        assert result.templates[0].name == "active"

    def test_merge_by_task(self, db_session):
        """list_merged_by_task：task_id -> phase_id -> theme_id 链路。"""
        goal, themes, phases = make_tree(db_session, tasks_per_phase=1)
        phase_id = phases[0].id
        theme_id = themes[0].id
        task = db_session.query(Task).filter_by(phase_id=phase_id).first()

        _make_template(
            db_session, scope_type="phase", scope_id=phase_id, type="后置", name="阶段后置"
        )
        _make_template(
            db_session, scope_type="theme", scope_id=theme_id, type="后置", name="专题后置"
        )
        svc = ConfigAppSvc(db_session)
        result = svc.list_merged_by_task(task.id, type="后置")
        assert len(result.templates) == 2

    def test_merge_by_task_not_found(self, db_session):
        svc = ConfigAppSvc(db_session)
        with pytest.raises(NotFoundError):
            svc.list_merged_by_task("nonexistent-task")

    def test_merge_no_ordering(self, db_session):
        """合并结果无顺序性（doc/02 2.18）。多次查询结果集一致（集合相等）。"""
        goal, themes, phases = make_tree(db_session, phases_per_theme=1)
        phase_id = phases[0].id
        theme_id = themes[0].id

        _make_template(db_session, scope_type="phase", scope_id=phase_id, type="前置", name="A")
        _make_template(db_session, scope_type="theme", scope_id=theme_id, type="前置", name="B")
        svc = ConfigAppSvc(db_session)
        r1 = svc.list_merged(phase_id=phase_id, theme_id=theme_id, type="前置")
        r2 = svc.list_merged(phase_id=phase_id, theme_id=theme_id, type="前置")
        assert {t.name for t in r1.templates} == {t.name for t in r2.templates} == {"A", "B"}
