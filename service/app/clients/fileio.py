"""Obsidian Vault 读写：daily.md / weekly.md 快照写入。

"用户确认版快照"（8.7），确认时写入；日终总结不再执行级联（级联已即时）。
Story5 实现 write_daily_md；write_weekly_md 留 Story6。
"""

import logging
from datetime import date
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def write_daily_md(user_id: str, date_: date, summary_data: dict) -> str:
    """写日终总结快照到 Obsidian Vault。

    纯文件 IO，由 confirm 服务事务提交后异步调用，不在事务内（铁律 §3#3）。
    快照内容：日期、完成/未完成任务、阶段健康度、summary 文本（如有）。
    DB 唯一真相源（铁律 §3#5）：daily.md 是快照，不反向同步。

    Args:
        user_id: 用户 ID（预留多用户，当前 vault 不分用户）。
        date_: 日期。
        summary_data: 统计数据（completed_tasks, incomplete_tasks, phase_health 等）。

    Returns:
        写入的文件相对路径，如 "daily/2026-07-06.md"。
    """
    vault = Path(settings.vault_root)
    daily_dir = vault / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{date_.isoformat()}.md"
    filepath = daily_dir / filename
    rel_path = f"daily/{filename}"

    lines: list[str] = []
    lines.append(f"# 日终总结 {date_.isoformat()}")
    lines.append("")

    completed = summary_data.get("completed_tasks", [])
    incomplete = summary_data.get("incomplete_tasks", [])

    lines.append(f"## 今日任务（{len(completed)}/{len(completed) + len(incomplete)}）")
    lines.append("")
    lines.append("### 已完成")
    for t in completed:
        name = t.get("name", "")
        theme = t.get("theme_name", "")
        lines.append(f"- [x] {name}（{theme}）")
    lines.append("")

    lines.append("### 未完成")
    for t in incomplete:
        name = t.get("name", "")
        theme = t.get("theme_name", "")
        lines.append(f"- [ ] {name}（{theme}）")
    lines.append("")

    phase_health = summary_data.get("phase_health", [])
    if phase_health:
        lines.append("## 阶段健康度")
        lines.append("")
        lines.append("| 阶段 | 完成 | 总数 | 进度 | 状态 |")
        lines.append("|------|------|------|------|------|")
        for p in phase_health:
            name = p.get("name", "")
            completed_n = p.get("completed", 0)
            total = p.get("total", 0)
            rate = p.get("rate", 0)
            status = p.get("status", "")
            pct = f"{rate * 100:.0f}%"
            lines.append(f"| {name} | {completed_n} | {total} | {pct} | {status} |")
        lines.append("")

    summary_text = summary_data.get("summary")
    if summary_text:
        lines.append("## 总结")
        lines.append("")
        lines.append(summary_text)
        lines.append("")

    content = "\n".join(lines)
    filepath.write_text(content, encoding="utf-8")
    logger.info("write_daily_md: %s (user=%s)", rel_path, user_id)
    return rel_path
