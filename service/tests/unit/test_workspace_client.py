"""workspace client 单元测试：init_workspace_dir / is_path_valid。"""

from app.clients.workspace import init_workspace_dir, is_path_valid


def test_init_workspace_dir_creates_dir_and_skeleton(tmp_path):
    path = tmp_path / "ws-1"
    init_workspace_dir(str(path))
    assert path.is_dir()
    assert (path / "README.md").is_file()
    assert (path / ".gitkeep").is_file()


def test_init_workspace_dir_idempotent(tmp_path):
    path = tmp_path / "ws-2"
    init_workspace_dir(str(path))
    init_workspace_dir(str(path))  # 重复不报错
    assert (path / "README.md").is_file()


def test_is_path_valid_true_for_existing_dir(tmp_path):
    assert is_path_valid(str(tmp_path)) is True


def test_is_path_valid_false_for_missing(tmp_path):
    assert is_path_valid(str(tmp_path / "no-such")) is False


def test_is_path_valid_false_for_file(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    assert is_path_valid(str(f)) is False
