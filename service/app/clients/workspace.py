"""工作空间初始化件（managed 分支）。

与 app/clients/fileio.py（Obsidian daily/weekly 快照，S5/6）不同，本件负责
managed=1 工作空间的目录初始化（mkdir + git init + 骨架含规范文件）。

事务外异步调用（铁律 §3#3：事务内禁止 IO/HTTP）。
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

# 骨架规范文件（managed=1 初始化时写入，注明内容）
_README_TEMPLATE = """\
# 工作空间

本目录由目标管理系统自动初始化（managed=托管）。

- 专题相关阶段任务在此推进。
- 已纳入 git 版本控制，请将产出提交到此仓库。
- 规范文件由系统生成，请勿删除 .gitkeep。
"""

_GITKEEP = ""  # 占位文件，使 git 跟踪空目录


def init_workspace_dir(path: str) -> None:
    """managed=1 初始化：mkdir -p + git init + 骨架文件（README.md / .gitkeep）。

    幂等：目录已存在不报错；git init 在已有仓库上是安全的 no-op。
    事务外异步调用，失败抛异常（由调用方记录日志，不影响已提交的事务）。
    """
    os.makedirs(path, exist_ok=True)

    readme = os.path.join(path, "README.md")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as f:
            f.write(_README_TEMPLATE)

    gitkeep = os.path.join(path, ".gitkeep")
    if not os.path.exists(gitkeep):
        with open(gitkeep, "w", encoding="utf-8") as f:
            f.write(_GITKEEP)

    # git init（已有仓库时 no-op）。失败仅记日志，不阻断初始化（目录与骨架已就绪）
    try:
        subprocess.run(  # noqa: S603, S607 -- 本地受控环境
            ["git", "init", path],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("git init 失败（%s），目录与骨架已就绪，跳过 git: %s", path, e)


def is_path_valid(path: str) -> bool:
    """managed=0 校验：path 必须是已存在的目录。不创建任何文件。"""
    return os.path.isdir(path)
