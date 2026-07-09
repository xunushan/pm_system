"""pytest fixtures：内存 SQLite + 复用 session 的 TestClient。

- 内存 SQLite 用 StaticPool 共享单连接，保证建表对后续请求可见。
- client fixture 覆盖 get_db 依赖，使请求落到测试 session。
- autouse fixture 禁用 Supervisor 定时巡检（测试不依赖真实 Redis/线程）。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture(autouse=True)
def _disable_supervisor_scheduler(monkeypatch):
    """禁用 Supervisor 定时巡检 + 事件分发（测试不依赖真实 Redis/线程时序）。

    - supervisor_enabled=False：scheduler 不启动（lifespan 检查此开关）
    - dispatch_func=no-op：dispatcher 线程即使启动也不调真实 handler
    - 事件端到端测试用 dispatch_sync() 直接同步分发，不受此影响
    """
    monkeypatch.setattr("app.config.settings.supervisor_enabled", False)
    from app.supervisor.event_bus import set_dispatch_func

    set_dispatch_func(lambda _event: None)
    yield
    set_dispatch_func(None)


@pytest.fixture()
def fake_redis():
    """fakeredis 客户端（Supervisor 巡检去重测试用）。"""
    import fakeredis

    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # 与生产 session.py 一致：显式开启外键约束（SQLite 默认关闭）
    @event.listens_for(eng, "connect")
    def _enable_sqlite_fk(dbapi_conn, _connection_record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture()
def db_session(engine):
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
