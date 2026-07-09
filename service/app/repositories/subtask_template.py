"""subtask_templates 表 Repository（纯 CRUD + 按条件查询）。

纯数据访问：不管理事务（commit 由 AppSvc 负责）、不含业务逻辑、不调用 LLM、不发 HTTP。
合并规则（阶段优先专题、同名去重）在 ConfigAppSvc 层实现，本类只提供查询原语。
"""

from sqlalchemy import select

from app.models.subtask_template import SubtaskTemplate
from app.repositories.base import BaseRepository


class SubtaskTemplateRepository(BaseRepository[SubtaskTemplate]):
    __model__ = SubtaskTemplate

    def list_templates(
        self,
        *,
        scope_type: str | None = None,
        scope_id: str | None = None,
        type: str | None = None,
        status: str | None = None,
    ) -> list[SubtaskTemplate]:
        """按条件查询模板列表（支持任意组合过滤）。"""
        stmt = select(SubtaskTemplate)
        if scope_type is not None:
            stmt = stmt.where(SubtaskTemplate.scope_type == scope_type)
        if scope_id is not None:
            stmt = stmt.where(SubtaskTemplate.scope_id == scope_id)
        if type is not None:
            stmt = stmt.where(SubtaskTemplate.type == type)
        if status is not None:
            stmt = stmt.where(SubtaskTemplate.status == status)
        return list(self.db.scalars(stmt))

    def find_existing(
        self,
        *,
        scope_id: str,
        type: str,
        name: str,
        exclude_id: str | None = None,
    ) -> SubtaskTemplate | None:
        """查同 scope_id+type+name 的模板（UNIQUE 冲突预检）。

        exclude_id：更新时排除自身。
        """
        stmt = select(SubtaskTemplate).where(
            SubtaskTemplate.scope_id == scope_id,
            SubtaskTemplate.type == type,
            SubtaskTemplate.name == name,
        )
        if exclude_id is not None:
            stmt = stmt.where(SubtaskTemplate.id != exclude_id)
        return self.db.scalars(stmt).first()

    def list_active_by_scope(
        self,
        *,
        scope_type: str,
        scope_id: str,
        type: str | None = None,
    ) -> list[SubtaskTemplate]:
        """查 active 模板（合并规则用：分别查 phase 级和 theme 级）。"""
        stmt = select(SubtaskTemplate).where(
            SubtaskTemplate.scope_type == scope_type,
            SubtaskTemplate.scope_id == scope_id,
            SubtaskTemplate.status == "active",
        )
        if type is not None:
            stmt = stmt.where(SubtaskTemplate.type == type)
        return list(self.db.scalars(stmt))
