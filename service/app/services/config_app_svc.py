"""ConfigAppSvc：子任务模板配置 CRUD + 合并查询。

纯 CRUD（doc/05 §1.3：模板配置 CRUD），走 H5 页面，不建 Skill（doc/03 §8.13）。
事务由本类管理：写 DB -> commit。无 IO/HTTP（事务内禁止，铁律 #3）。

合并规则（doc/02 2.18）：
  查询条件：task_id -> phase_id -> theme_id
  Step 1: 查阶段级模板（scope_type='phase'）
  Step 2: 查专题级模板（scope_type='theme'）
  Step 3: 合并去重（阶段级优先，同名以阶段级为准，无顺序）

配置时不校验专题 type（doc/01 S7 AC：配置时不校验专题类型，智能体专题配了也不提示）。
删除标记 inactive（非物理删除，可恢复，doc/01 S7 AC：删除可恢复）。
"""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, NotFoundError, TemplateExistsError
from app.models.phase import Phase
from app.models.subtask_template import SubtaskTemplate
from app.models.task import Task
from app.repositories.subtask_template import SubtaskTemplateRepository
from app.schemas.subtask_template import (
    SubtaskTemplateCreateRequest,
    SubtaskTemplateData,
    SubtaskTemplateDeleteData,
    SubtaskTemplateListData,
    SubtaskTemplateUpdateRequest,
)

_SCOPE_TYPES = {"theme", "phase"}
_TYPES = {"前置", "后置"}
_STATUSES = {"active", "inactive"}


class ConfigAppSvc:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = SubtaskTemplateRepository(db)

    # ===== 查询 =====

    def list_templates(
        self,
        *,
        scope_type: str | None = None,
        scope_id: str | None = None,
        type: str | None = None,
        status: str | None = None,
    ) -> SubtaskTemplateListData:
        """查询模板列表（H5 页面用，支持任意组合过滤）。

        不做合并（合并查询走 list_merged / list_merged_by_task）。
        """
        self._validate_query_params(scope_type, type, status)
        templates = self.repo.list_templates(
            scope_type=scope_type, scope_id=scope_id, type=type, status=status
        )
        return SubtaskTemplateListData(templates=[self._to_data(t) for t in templates])

    def list_merged(
        self,
        *,
        phase_id: str,
        theme_id: str,
        type: str | None = None,
    ) -> SubtaskTemplateListData:
        """合并查询：阶段级优先专题级，同名去重（doc/02 2.18）。

        供 pm-subtask Skill 调用（GET /subtask-templates?type=前置|后置）。
        只返回 active 模板。去重键：(type, name)，阶段级优先。
        """
        phase_templates = self.repo.list_active_by_scope(
            scope_type="phase", scope_id=phase_id, type=type
        )
        theme_templates = self.repo.list_active_by_scope(
            scope_type="theme", scope_id=theme_id, type=type
        )
        merged = self._merge_dedup(phase_templates, theme_templates)
        return SubtaskTemplateListData(templates=[self._to_data(t) for t in merged])

    def list_merged_by_task(self, task_id: str, type: str | None = None) -> SubtaskTemplateListData:
        """按 task_id 合并查询（task -> phase_id -> theme_id，doc/02 2.18）。

        type 若提供则校验合法性（非前置/后置 -> 400）。
        """
        if type is not None:
            self._validate_type(type)
        task = self.db.get(Task, task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {task_id}")
        phase = self.db.get(Phase, task.phase_id)
        if phase is None:
            raise NotFoundError(f"阶段不存在: {task.phase_id}")
        return self.list_merged(phase_id=phase.id, theme_id=phase.theme_id, type=type)

    # ===== CRUD =====

    def create_template(self, req: SubtaskTemplateCreateRequest) -> SubtaskTemplateData:
        """创建模板。UNIQUE(scope_id,type,name) 冲突 -> 3001。

        配置时不校验专题 type（doc/01 S7 AC：配置时不校验专题类型）。
        """
        self._validate_scope_type(req.scope_type)
        self._validate_type(req.type)

        existing = self.repo.find_existing(scope_id=req.scope_id, type=req.type, name=req.name)
        if existing is not None:
            raise TemplateExistsError(
                f"模板已存在: scope_id={req.scope_id}, type={req.type}, name={req.name}"
            )

        template = SubtaskTemplate(
            id=str(uuid4()),
            scope_type=req.scope_type,
            scope_id=req.scope_id,
            type=req.type,
            name=req.name,
            description=req.description,
            status="active",
        )
        self.repo.create(template)
        self.db.commit()
        return self._to_data(template)

    def update_template(
        self, template_id: str, req: SubtaskTemplateUpdateRequest
    ) -> SubtaskTemplateData:
        """更新模板。name 变更触发 UNIQUE 冲突检查 -> 3001。"""
        template = self._require(template_id)

        if req.status is not None:
            self._validate_status(req.status)
            template.status = req.status
        if req.name is not None:
            # name 变更需检查 UNIQUE（排除自身）
            if template.name != req.name:
                existing = self.repo.find_existing(
                    scope_id=template.scope_id,
                    type=template.type,
                    name=req.name,
                    exclude_id=template_id,
                )
                if existing is not None:
                    raise TemplateExistsError(
                        f"模板已存在: scope_id={template.scope_id}, "
                        f"type={template.type}, name={req.name}"
                    )
            template.name = req.name
        if req.description is not None:
            template.description = req.description

        self.db.commit()
        return self._to_data(template)

    def delete_template(self, template_id: str) -> SubtaskTemplateDeleteData:
        """删除模板：标记 inactive（非物理删除，可恢复）。

        幂等：已 inactive 的再删不报错（doc/01 S7 AC：删除可恢复）。
        """
        template = self._require(template_id)
        if template.status != "inactive":
            template.status = "inactive"
            self.db.commit()
        return SubtaskTemplateDeleteData(id=template.id, status=template.status)

    # ---- 内部 ----

    def _require(self, template_id: str) -> SubtaskTemplate:
        template = self.repo.get(template_id)
        if template is None:
            raise NotFoundError(f"模板不存在: {template_id}")
        return template

    @staticmethod
    def _merge_dedup(
        phase_templates: list[SubtaskTemplate],
        theme_templates: list[SubtaskTemplate],
    ) -> list[SubtaskTemplate]:
        """合并去重：阶段级优先，同名以阶段级为准（doc/02 2.18）。

        去重键：(type, name)。无顺序性。
        """
        # 阶段级先入，建立 (type, name) 索引
        merged: list[SubtaskTemplate] = list(phase_templates)
        seen = {(t.type, t.name) for t in phase_templates}
        for t in theme_templates:
            key = (t.type, t.name)
            if key not in seen:
                merged.append(t)
                seen.add(key)
        return merged

    @staticmethod
    def _validate_query_params(
        scope_type: str | None, type_: str | None, status: str | None
    ) -> None:
        if scope_type is not None and scope_type not in _SCOPE_TYPES:
            raise BadRequestError(f"scope_type 非法: {scope_type!r}（仅 theme/phase）")
        if type_ is not None and type_ not in _TYPES:
            raise BadRequestError(f"type 非法: {type_!r}（仅 前置/后置）")
        if status is not None and status not in _STATUSES:
            raise BadRequestError(f"status 非法: {status!r}（仅 active/inactive）")

    @staticmethod
    def _validate_scope_type(scope_type: str) -> None:
        if scope_type not in _SCOPE_TYPES:
            raise BadRequestError(f"scope_type 非法: {scope_type!r}（仅 theme/phase）")

    @staticmethod
    def _validate_type(type_: str) -> None:
        if type_ not in _TYPES:
            raise BadRequestError(f"type 非法: {type_!r}（仅 前置/后置）")

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in _STATUSES:
            raise BadRequestError(f"status 非法: {status!r}（仅 active/inactive）")

    @staticmethod
    def _to_data(t: SubtaskTemplate) -> SubtaskTemplateData:
        return SubtaskTemplateData(
            id=t.id,
            scope_type=t.scope_type,
            scope_id=t.scope_id,
            type=t.type,
            name=t.name,
            description=t.description,
            status=t.status,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
