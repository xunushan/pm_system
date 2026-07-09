"""Obsidian Vault 读写：daily.md / weekly.md 快照写入。

"用户确认版快照"（8.7），确认时写入；日终/周总结不执行级联（级联已即时）。
Story5 实现 write_daily_md；Story6 实现 write_weekly_md。
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


def write_weekly_md(user_id: str, week: str, stats_data: dict) -> str:
    """写周总结快照到 Obsidian Vault。

    纯文件 IO，由 confirm 服务事务提交后异步调用，不在事务内（铁律 §3#3）。
    快照内容：周、日期范围、每日完成趋势、阶段健康度、智能体产出、子任务统计、summary。
    DB 唯一真相源（铁律 §3#5）：weekly.md 是快照，不反向同步。

    Args:
        user_id: 用户 ID（预留多用户，当前 vault 不分用户）。
        week: ISO 周字符串，如 "2026-W27"。
        stats_data: 统计数据（date_range, daily_stats, phase_health, agent_output_stats,
            subtask_stats, summary 等）。

    Returns:
        写入的文件相对路径，如 "weekly/2026-W27.md"。
    """
    vault = Path(settings.vault_root)
    weekly_dir = vault / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{week}.md"
    filepath = weekly_dir / filename
    rel_path = f"weekly/{filename}"

    lines: list[str] = []
    lines.append(f"# 周总结 {week}")
    lines.append("")

    dr = stats_data.get("date_range", {})
    start = dr.get("start", "")
    end = dr.get("end", "")
    lines.append(f"周期：{start} ~ {end}")
    lines.append("")

    daily_stats = stats_data.get("daily_stats", [])
    if daily_stats:
        lines.append("## 每日完成趋势")
        lines.append("")
        lines.append("| 日期 | 已完成 | 未完成 | 确认 |")
        lines.append("|------|--------|--------|------|")
        for d in daily_stats:
            d_date = d.get("date", "")
            completed = d.get("completed_count", 0)
            incomplete = d.get("incomplete_count", 0)
            confirmed = "是" if d.get("is_confirmed") else "否"
            lines.append(f"| {d_date} | {completed} | {incomplete} | {confirmed} |")
        lines.append("")

    phase_health = stats_data.get("phase_health", [])
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

    agent_stats = stats_data.get("agent_output_stats", {})
    if agent_stats:
        total_files = agent_stats.get("total_files", 0)
        by_type = agent_stats.get("by_type", {})
        lines.append("## 智能体产出")
        lines.append("")
        lines.append(f"总文件数：{total_files}")
        if by_type:
            lines.append("")
            lines.append("| 类型 | 数量 |")
            lines.append("|------|------|")
            for t, n in by_type.items():
                lines.append(f"| {t} | {n} |")
        lines.append("")

    subtask_stats = stats_data.get("subtask_stats", {})
    if subtask_stats:
        lines.append("## 子任务统计")
        lines.append("")
        lines.append("| 类别 | 总数 | 已完成 | 待执行 |")
        lines.append("|------|------|--------|--------|")
        pre = subtask_stats.get("pre", {})
        post = subtask_stats.get("post", {})
        lines.append(
            f"| 前置 | {pre.get('total', 0)} | "
            f"{pre.get('completed', 0)} | {pre.get('pending', 0)} |"
        )
        lines.append(
            f"| 后置 | {post.get('total', 0)} | "
            f"{post.get('completed', 0)} | {post.get('pending', 0)} |"
        )
        lines.append("")

    summary_text = stats_data.get("summary")
    if summary_text:
        lines.append("## 总结")
        lines.append("")
        lines.append(summary_text)
        lines.append("")

    content = "\n".join(lines)
    filepath.write_text(content, encoding="utf-8")
    logger.info("write_weekly_md: %s (user=%s)", rel_path, user_id)
    return rel_path
