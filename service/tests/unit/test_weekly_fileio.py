"""fileio 单元测试：write_weekly_md 路径/内容。

验证 Obsidian 风格周总结 markdown 快照写入正确
（周、日期范围、每日完成趋势、阶段健康度、智能体产出、子任务统计、summary）。
"""

from app.clients import fileio
from app.config import settings


def test_write_weekly_md_creates_file(tmp_path, monkeypatch):
    """write_weekly_md 写入 vault/weekly/{week}.md，返回相对路径。"""
    monkeypatch.setattr(settings, "vault_root", str(tmp_path))

    stats_data = {
        "week": "2026-W27",
        "date_range": {"start": "2026-06-29", "end": "2026-07-05"},
        "daily_stats": [
            {
                "date": "2026-06-29",
                "is_confirmed": True,
                "completed_count": 2,
                "incomplete_count": 1,
            },
            {
                "date": "2026-06-30",
                "is_confirmed": False,
                "completed_count": 0,
                "incomplete_count": 0,
            },
        ],
        "phase_health": [
            {"name": "MLP", "completed": 3, "total": 6, "rate": 0.5, "status": "进行中"},
        ],
        "agent_output_stats": {"total_files": 5, "by_type": {"note": 3, "code": 2}},
        "subtask_stats": {
            "pre": {"total": 2, "completed": 1, "pending": 1},
            "post": {"total": 1, "completed": 0, "pending": 1},
        },
        "summary": "本周进展顺利。",
    }

    rel_path = fileio.write_weekly_md("user_001", "2026-W27", stats_data)

    assert rel_path == "weekly/2026-W27.md"
    filepath = tmp_path / "weekly" / "2026-W27.md"
    assert filepath.exists()
    content = filepath.read_text(encoding="utf-8")
    assert "# 周总结 2026-W27" in content
    assert "2026-06-29 ~ 2026-07-05" in content
    assert "每日完成趋势" in content
    assert "阶段健康度" in content
    assert "MLP" in content
    assert "总文件数：5" in content
    assert "note" in content
    assert "code" in content
    assert "前置" in content
    assert "后置" in content
    assert "本周进展顺利" in content


def test_write_weekly_md_empty_stats(tmp_path, monkeypatch):
    """空统计数据也能正常写入。"""
    monkeypatch.setattr(settings, "vault_root", str(tmp_path))

    rel_path = fileio.write_weekly_md("user_001", "2026-W27", {})

    assert rel_path == "weekly/2026-W27.md"
    filepath = tmp_path / "weekly" / "2026-W27.md"
    assert filepath.exists()
    content = filepath.read_text(encoding="utf-8")
    assert "# 周总结 2026-W27" in content


def test_write_weekly_md_creates_directory(tmp_path, monkeypatch):
    """vault/weekly 目录不存在时自动创建。"""
    vault = tmp_path / "nested" / "vault"
    monkeypatch.setattr(settings, "vault_root", str(vault))

    rel_path = fileio.write_weekly_md("u1", "2026-W27", {})
    assert rel_path == "weekly/2026-W27.md"
    assert (vault / "weekly" / "2026-W27.md").exists()


def test_write_weekly_md_idempotent(tmp_path, monkeypatch):
    """重复写入同一周覆盖文件（幂等）。"""
    monkeypatch.setattr(settings, "vault_root", str(tmp_path))

    fileio.write_weekly_md("u1", "2026-W27", {"summary": "v1"})
    fileio.write_weekly_md("u1", "2026-W27", {"summary": "v2"})

    filepath = tmp_path / "weekly" / "2026-W27.md"
    content = filepath.read_text(encoding="utf-8")
    assert "v2" in content
    assert "v1" not in content
