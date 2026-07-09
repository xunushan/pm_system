"""规划确认请求/响应模型。详见《服务API文档 v2.0》3.2。

draft.content 在 story_type='plan' 时的结构（嵌套，自包含，无需引用 ID）：

  {
    "goal": {
      "name", "description"?, "time_range_start"?,
      "time_range_end"?, "scheduled_start_date"?
    },
    "themes": [
      {
        "name", "description"?, "type"?, "phases": [
          {
            "name", "description"?, "sort_order", "tasks": [
              { "name", "description"?, "sort_order" }
            ]
          }
        ]
      }
    ]
  }

规划态铁律（doc/02 2.14 / doc/03 铁律）：
  - tasks.executor 不填（NULL，pm-daily 按专题 type 推断）
  - phases.deadline 不填（NULL，激活时填，Story2）
  - goals/themes/phases 初始 '未开始'，tasks 初始 '待执行'
"""

from datetime import date

from pydantic import BaseModel, Field


class PlanGoalContent(BaseModel):
    name: str
    description: str | None = None
    time_range_start: date | None = None
    time_range_end: date | None = None
    scheduled_start_date: date | None = None


class PlanTaskContent(BaseModel):
    name: str
    description: str | None = None
    sort_order: int


class PlanPhaseContent(BaseModel):
    name: str
    description: str | None = None
    sort_order: int
    tasks: list[PlanTaskContent] = Field(default_factory=list)


class PlanThemeContent(BaseModel):
    name: str
    description: str | None = None
    type: str = "learning"
    phases: list[PlanPhaseContent] = Field(default_factory=list)


class PlanContent(BaseModel):
    """draft.content 在 story_type='plan' 时的结构。"""

    goal: PlanGoalContent
    themes: list[PlanThemeContent]


class PlanConfirmRequest(BaseModel):
    draft_id: str = Field(..., description="确认按钮回调只传 draft_id（规避飞书 30KB 限制）")


class PlanConfirmData(BaseModel):
    goal_id: str
    goal_name: str
    themes_created: int
    phases_created: int
    tasks_created: int
    draft_deleted: bool
    h5_url: str
