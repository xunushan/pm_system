"""智能体进程接口（Story4A）。详见《服务API文档 v2.0》智能体进程节 + 《系统架构文档》五。

首次下发智能体任务时启动 opencode serve；阶段级常驻；端口动态分配 10000-20000；
心跳每 5 分钟；3 次重试不通过退出，用户"/pm 确认完成"后重启（不同端口）。
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_agents() -> dict:
    """TODO(Story4A)。"""
    return {"todo": "implement Story4A - 见 doc/04 智能体进程节"}
