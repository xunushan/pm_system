"""冒烟测试：应用启动、/health、OpenAPI schema 路由注册。"""


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_openapi_routes_registered(client):
    """确认业务 router 均已挂载（框架完整性）。

    实现后的 router（drafts/plans）用真实子路径，桩 router 仍是 GET /。
    断言：每个前缀下至少注册了一条路径。
    """
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    for prefix in (
        "/api/v1/plans",
        "/api/v1/drafts",
        "/api/v1/schedules",
        "/api/v1/tasks",
        "/api/v1/daily",
        "/api/v1/weekly",
        "/api/v1/workspaces",
        "/api/v1/subtasks",
        "/api/v1/subtask-templates",
        "/api/v1/agents",
        "/api/v1/board",
    ):
        assert any(p == prefix or p.startswith(prefix + "/") for p in paths), f"缺失路由 {prefix}"
