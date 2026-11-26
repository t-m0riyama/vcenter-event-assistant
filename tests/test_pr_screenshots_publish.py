"""scripts/pr_screenshots/run.py の公開の部品（push の手前まで）を確かめる。"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

RUN = Path(__file__).resolve().parents[1] / "scripts" / "pr_screenshots" / "run.py"
_spec = importlib.util.spec_from_file_location("pr_screenshots_run", RUN)
assert _spec and _spec.loader
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo.git",
        "https://github.com/owner/repo",
        "git@github.com:owner/repo.git",
        "ssh://git@github.com/owner/repo.git",
    ],
)
def test_github_slug_accepts_https_and_ssh(url: str) -> None:
    assert run.github_slug(url) == "owner/repo"


def test_github_slug_rejects_other_hosts() -> None:
    with pytest.raises(ValueError):
        run.github_slug("https://gitlab.com/owner/repo.git")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_screenshot_commit_holds_only_the_pngs_and_leaves_the_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "base")
    (repo / "tracked.txt").write_text("x", encoding="utf-8")
    head = _git(repo, "rev-parse", "HEAD")
    shots = tmp_path / "shots"
    shots.mkdir()
    for name in ("light-a.png", "dark-a.png"):
        (shots / name).write_bytes(b"\x89PNG" + name.encode())
    (shots / "notes.txt").write_text("skip", encoding="utf-8")

    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "t@example.invalid")
    commit, names = run.screenshot_commit(shots, cwd=repo)

    assert names == ["dark-a.png", "light-a.png"]
    assert _git(repo, "ls-tree", "--name-only", commit).splitlines() == names
    assert _git(repo, "rev-list", "--parents", "-n", "1", commit) == commit  # 親が無い
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "status", "--porcelain") == "?? tracked.txt"


def test_screenshot_commit_requires_pngs(tmp_path: Path) -> None:
    with pytest.raises(run.PublishError):
        run.screenshot_commit(tmp_path)


def test_image_markdown_pairs_each_scene_and_quotes_names() -> None:
    names = ["dark-a.png", "dark-b c.png", "light-a.png", "light-b c.png"]
    assert run.image_markdown("owner/repo", "abc123", names).splitlines() == [
        "![light-a](https://raw.githubusercontent.com/owner/repo/abc123/light-a.png)",
        "![dark-a](https://raw.githubusercontent.com/owner/repo/abc123/dark-a.png)",
        "![light-b c](https://raw.githubusercontent.com/owner/repo/abc123/light-b%20c.png)",
        "![dark-b c](https://raw.githubusercontent.com/owner/repo/abc123/dark-b%20c.png)",
    ]


@pytest.fixture
def repo_with_origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """作業用のリポジトリと、origin にした bare リポジトリ。"""
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "t@example.invalid")
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    # origin は手元の bare リポジトリなので、GitHub の URL の判定だけを差し替える。
    monkeypatch.setattr(run, "github_slug", lambda url: "owner/repo")
    return repo, origin


def _shots(tmp_path: Path, name: str = "shots") -> Path:
    out = tmp_path / name
    out.mkdir()
    (out / "light-a.png").write_bytes(b"\x89PNG light")
    (out / "dark-a.png").write_bytes(b"\x89PNG dark")
    return out


def test_publish_pushes_a_new_branch_and_refuses_to_overwrite(repo_with_origin, tmp_path: Path) -> None:
    repo, origin = repo_with_origin
    head = _git(repo, "rev-parse", "HEAD")
    assert run.prepare_publish("demo", tmp_path / "empty", cwd=repo) == "owner/repo"

    text = run.publish(_shots(tmp_path), "demo", "owner/repo", cwd=repo)
    pushed = _git(origin, "rev-parse", "refs/heads/screenshots/demo")
    assert f"/owner/repo/{pushed}/light-a.png" in text
    assert _git(origin, "ls-tree", "--name-only", pushed).splitlines() == ["dark-a.png", "light-a.png"]
    assert _git(repo, "rev-parse", "HEAD") == head

    # 撮る前の確認で止まり、後からできた場合も + 無しの push が拒まれて上書きしない。
    with pytest.raises(run.PublishError, match="既にあります"):
        run.prepare_publish("demo", tmp_path / "empty", cwd=repo)
    with pytest.raises(run.PublishError, match="push に失敗"):
        run.publish(_shots(tmp_path, "again"), "demo", "owner/repo", cwd=repo)
    assert _git(origin, "rev-parse", "refs/heads/screenshots/demo") == pushed


def test_prepare_publish_rejects_bad_names_and_used_output(repo_with_origin, tmp_path: Path) -> None:
    repo, _origin = repo_with_origin
    with pytest.raises(run.PublishError, match="使えません"):
        run.prepare_publish("bad..name", tmp_path / "empty", cwd=repo)
    with pytest.raises(run.PublishError, match="空ではありません"):
        run.prepare_publish("demo", _shots(tmp_path), cwd=repo)
    file = tmp_path / "file.png"
    file.write_bytes(b"x")
    with pytest.raises(run.PublishError, match="ディレクトリではありません"):
        run.prepare_publish("demo", file, cwd=repo)


def test_prepare_publish_stops_when_origin_is_unreachable(repo_with_origin, tmp_path: Path) -> None:
    repo, _origin = repo_with_origin
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    with pytest.raises(run.PublishError, match="確かめられませんでした"):
        run.prepare_publish("demo", tmp_path / "empty", cwd=repo)
