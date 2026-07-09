"""fileio 单元测试：write_daily_md 路径/内容。

验证 Obsidian 风格 markdown 快照写入正确（日期、完成/未完成任务、阶段健康度）。
"""

from datetime import date

from app.clients import fileio
from app.config import settings


def test_write_daily_md_creates_file(tmp_path, monkeypatch):
    """write_daily_md 写入 vault/daily/{date}.md，返回相对路径。"""
    monkeypatch.setattr(settings, "vault_root", str(tmp_path))

    summary_data = {
        "completed_tasks": [
            {"name": "优化器专题", "theme_name": "深度学习"},
            {"name": "手写 MLP", "theme_name": "深度学习"},
        ],
        "incomplete_tasks": [
            {"name": "数组专题 2 题", "theme_name": "面试准备"},
        ],
        "phase_health": [
            {"name": "MLP", "completed": 3, "total": 6, "rate": 0.5, "status": "进行中"},
        ],
        "summary": "MLP 进度过半，保持节奏。",
    }

    rel_path = fileio.write_daily_md("user_001", date(2026, 7, 6), summary_data)

    assert rel_path == "daily/2026-07-06.md"
    filepath = tmp_path / "daily" / "2026-07-06.md"
    assert filepath.exists()
    content = filepath.read_text(encoding="utf-8")
    assert "# 日终总结 2026-07-06" in content
    assert "优化器专题" in content
    assert "手写 MLP" in content
    assert "数组专题 2 题" in content
    assert "MLP 进度过半" in content
    assert "MLP" in content
    assert "3/6" in content or "3" in content  # 阶段健康度表


def test_write_daily_md_empty_tasks(tmp_path, monkeypatch):
    """空任务列表也能正常写入。"""
    monkeypatch.setattr(settings, "vault_root", str(tmp_path))

    rel_path = fileio.write_daily_md("user_001", date(2026, 7, 6), {})

    assert rel_path == "daily/2026-07-06.md"
    filepath = tmp_path / "daily" / "2026-07-06.md"
    assert filepath.exists()
    content = filepath.read_text(encoding="utf-8")
    assert "# 日终总结 2026-07-06" in content


def test_write_daily_md_idempotent(tmp_path, monkeypatch):
    """重复写入同一日期覆盖文件（幂等）。"""
    monkeypatch.setattr(settings, "vault_root", str(tmp_path))

    summary_data = {"completed_tasks": [{"name": "t1", "theme_name": "th"}]}
    fileio.write_daily_md("u1", date(2026, 7, 6), summary_data)

    # 第二次写入（覆盖）
    summary_data2 = {"completed_tasks": [{"name": "t2", "theme_name": "th"}]}
    fileio.write_daily_md("u1", date(2026, 7, 6), summary_data2)

    filepath = tmp_path / "daily" / "2026-07-06.md"
    content = filepath.read_text(encoding="utf-8")
    assert "t2" in content
    assert "t1" not in content


def test_write_daily_md_creates_directory(tmp_path, monkeypatch):
    """vault/daily 目录不存在时自动创建。"""
    vault = tmp_path / "nested" / "vault"
    monkeypatch.setattr(settings, "vault_root", str(vault))

    rel_path = fileio.write_daily_md("u1", date(2026, 7, 6), {})
    assert rel_path == "daily/2026-07-06.md"
    assert (vault / "daily" / "2026-07-06.md").exists()
