"""Repository 基类：通用 CRUD 原语。

纯数据访问：不管理事务（commit 由 AppSvc 负责）、不含业务逻辑、不调用 LLM、不发 HTTP。
子类按表覆写 __model__ 即可继承 create / get / get_multi。
"""

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """单表 CRUD 基类。子类设 __model__。"""

    __model__: type[ModelT]

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, instance: ModelT) -> ModelT:
        """加入 session（不提交）。主键由调用方生成（str(uuid4())）。"""
        self.db.add(instance)
        self.db.flush()  # 触发默认值/约束，便于拿 server_default 列
        return instance

    def get(self, id_: str) -> ModelT | None:
        return self.db.get(self.__model__, id_)

    def get_multi(self) -> list[ModelT]:
        return list(self.db.scalars(select(self.__model__)))
