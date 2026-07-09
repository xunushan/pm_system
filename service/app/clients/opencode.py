"""OpenCode 客户端：HTTP POST 下发任务到 opencode serve 端口。

端口动态分配（10000-20000，见《系统架构文档》五）。
启动时机：首次下发智能体任务时（Story3 确认后），非 Story2 激活时。

S4A 真实现（替换 S3 桩）：
  - dispatch_task：HTTP POST 下发任务到 opencode serve。
  - dispatch_pre_subtasks：异步执行前置子任务（opencode run）。
  - dispatch_post_subtasks：异步执行后置子任务（opencode run，Story4B 调用）。
  - start_agent_serve：启动 opencode serve 接管智能体任务（动态端口 + agent_processes 管理）。
  - health / shutdown：健康检查 / 停止 serve。
  opencode 是外部服务，所有 HTTP 调用用 httpx，测试 mock httpx。
  agent_processes 表记录进程信息（端口/PID/状态/心跳）。
"""

import logging
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import InternalError
from app.core.times import now_utc_naive
from app.db.session import SessionLocal
from app.models.agent_process import AgentProcess
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


class OpenCodeClient:
    """按 workspace 的 opencode serve 端口下发任务。

    事务外异步调用（铁律 §3#3：事务内禁止 IO/HTTP）。
    DB 操作用传入 session 或自建 SessionLocal（async 场景）。
    """

    def __init__(self, db: Session | None = None) -> None:
        self.base_url = settings.opencode_base_url
        self.db = db

    # ---- 端口管理 ----

    @staticmethod
    def _parse_port_range() -> tuple[int, int]:
        """解析 settings.agent_port_range（如 '10000-20000'）。"""
        parts = settings.agent_port_range.split("-")
        return int(parts[0]), int(parts[1])

    @staticmethod
    def _allocate_port(db: Session) -> int:
        """在 10000-20000 范围内分配空闲端口。

        查 agent_processes 中 running 进程已占用端口，选第一个空闲的。
        """
        lo, hi = OpenCodeClient._parse_port_range()
        used = set(db.scalars(select(AgentProcess.port).where(AgentProcess.status == "running")))
        for port in range(lo, hi + 1):
            if port not in used:
                return port
        raise InternalError("无可用端口（10000-20000 均被占用）")

    # ---- 启动 / 重启 ----

    def start_agent_serve(self, workspace_id: str, task: dict[str, Any] | None = None) -> int:
        """启动 opencode serve 接管智能体任务（动态端口）。

        逻辑（doc/03 五 §5.1-5.3）：
          1. 查 workspace 路径
          2. 查该 workspace 是否已有 running 进程 -> 是则复用端口
          3. 否则分配端口 + 创建/更新 agent_processes 记录
          4. HTTP POST 下发首个智能体任务（如有）

        Args:
            workspace_id: 工作空间 ID。
            task: 触发启动的智能体任务（含 task_id/name/phase_id）。

        Returns:
            分配/复用的端口号。
        """
        own_session = self.db is None
        db = self.db or SessionLocal()
        try:
            ws = db.get(Workspace, workspace_id)
            if ws is None:
                logger.warning("start_agent_serve: workspace 不存在 %s", workspace_id)
                return -1

            ap = db.scalar(
                select(AgentProcess).where(
                    AgentProcess.workspace_id == workspace_id,
                    AgentProcess.status == "running",
                )
            )
            if ap is not None:
                port = ap.port  # 复用现有进程端口
                logger.info("start_agent_serve: 复用进程 ws=%s port=%d", workspace_id, port)
            else:
                port = self._allocate_port(db)
                # UNIQUE(workspace_id)：已有 stopped/crashed 记录则更新，否则新建
                existing = db.scalar(
                    select(AgentProcess).where(AgentProcess.workspace_id == workspace_id)
                )
                now = now_utc_naive()
                if existing:
                    existing.port = port
                    existing.status = "running"
                    existing.started_at = now
                    existing.last_heartbeat = now
                    existing.task_queue = None
                    ap = existing
                else:
                    ap = AgentProcess(
                        id=str(uuid4()),
                        workspace_id=workspace_id,
                        port=port,
                        status="running",
                        last_heartbeat=now,
                    )
                    db.add(ap)
                db.flush()
                logger.info("start_agent_serve: 新进程 ws=%s port=%d", workspace_id, port)

            # 下发首个任务（HTTP POST，事务外 IO）
            if task:
                self.dispatch_task(workspace_id, task, port)

            db.commit()
            return port
        except Exception:
            db.rollback()
            logger.exception("start_agent_serve 失败: ws=%s", workspace_id)
            return -1
        finally:
            if own_session:
                db.close()

    # ---- 任务下发 ----

    def dispatch_task(self, workspace_id: str, task: dict[str, Any], port: int) -> dict[str, Any]:
        """HTTP POST 下发任务到 opencode serve。

        Args:
            workspace_id: 工作空间 ID。
            task: 任务载荷（含 task_id/name/phase_id 等）。
            port: opencode serve 端口。

        Returns:
            opencode 响应。
        """
        url = f"http://localhost:{port}/task"
        resp = httpx.post(url, json=task, timeout=30)
        resp.raise_for_status()
        logger.info("dispatch_task: ws=%s port=%d task=%s", workspace_id, port, task.get("task_id"))
        return resp.json()

    def dispatch_pre_subtasks(self, subtasks: list[dict[str, Any]]) -> None:
        """异步执行前置子任务（opencode run，一次性非 serve）。

        S4A 真实现：逐个 HTTP POST 到 opencode base_url/run。
        事务后异步调用（由 daily_app_svc.trigger_async 触发）。

        Args:
            subtasks: 前置子任务列表，每项含 id/name/task_id 等。
        """
        for sub in subtasks:
            try:
                resp = httpx.post(
                    f"{self.base_url}/run",
                    json={"subtask_id": sub.get("id"), "name": sub.get("name")},
                    timeout=30,
                )
                resp.raise_for_status()
            except Exception:
                logger.exception("dispatch_pre_subtasks 失败: %s", sub.get("id"))

    def dispatch_post_subtasks(self, subtasks: list[dict[str, Any]]) -> None:
        """异步执行后置子任务（opencode run，一次性非 serve）。

        S4A 真实现：逐个 HTTP POST 到 opencode base_url/run（与前置同 opencode run 通道）。
        事务后异步调用（由 task_app_svc.post_confirm 触发，Story4B）。

        Args:
            subtasks: 后置子任务列表，每项含 id/name/task_id 等。
        """
        for sub in subtasks:
            try:
                resp = httpx.post(
                    f"{self.base_url}/run",
                    json={"subtask_id": sub.get("id"), "name": sub.get("name")},
                    timeout=30,
                )
                resp.raise_for_status()
            except Exception:
                logger.exception("dispatch_post_subtasks 失败: %s", sub.get("id"))

    # ---- 健康检查 / 关闭 ----

    def health(self, workspace_id: str) -> bool:
        """健康检查 opencode serve（GET /health）。

        Returns:
            True 如果 serve 响应 200，False 如果进程不存在或不可达。
        """
        own_session = self.db is None
        db = self.db or SessionLocal()
        try:
            ap = db.scalar(
                select(AgentProcess).where(
                    AgentProcess.workspace_id == workspace_id,
                    AgentProcess.status == "running",
                )
            )
            if ap is None:
                return False
            resp = httpx.get(f"http://localhost:{ap.port}/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            logger.warning("health 检查失败: ws=%s", workspace_id)
            return False
        finally:
            if own_session:
                db.close()

    def shutdown(self, workspace_id: str) -> bool:
        """停止 opencode serve（3 次重试不通过时调用）。

        HTTP POST /shutdown（best effort），更新 agent_processes.status='stopped'。

        Returns:
            True 如果成功停止，False 如果进程不存在。
        """
        own_session = self.db is None
        db = self.db or SessionLocal()
        try:
            ap = db.scalar(
                select(AgentProcess).where(
                    AgentProcess.workspace_id == workspace_id,
                    AgentProcess.status == "running",
                )
            )
            if ap is None:
                return False
            # HTTP POST /shutdown（best effort，失败不阻断状态更新）
            try:
                httpx.post(f"http://localhost:{ap.port}/shutdown", timeout=5)
            except Exception:
                logger.warning("shutdown HTTP 调用失败（best effort）: ws=%s", workspace_id)
            ap.status = "stopped"
            db.commit()
            logger.info("shutdown: ws=%s port=%d stopped", workspace_id, ap.port)
            return True
        except Exception:
            db.rollback()
            logger.exception("shutdown 失败: ws=%s", workspace_id)
            return False
        finally:
            if own_session:
                db.close()
