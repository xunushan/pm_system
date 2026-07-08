"""SQLAlchemy 声明式基类。Alembic autogenerate 据此检测表结构变更。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
