"""Skill 実行時エイリアスを安全に作るスクリプトのテスト。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import scripts.link_skills as link_skills


ALIAS_ROOT_NAMES = (".cursor", ".agents", ".claude")
WINDOWS = os.name == "nt"


def _configure_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, names=("sample-skill",)):
    """一時リポジトリへ正本と実行時公開先を設定する。"""
    canonical_root = tmp_path / "skills"
    canonical_root.mkdir()
    for name in names:
        skill = canonical_root / name
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test\n---\n", encoding="utf-8"
        )

    alias_roots = tuple(tmp_path / name / "skills" for name in ALIAS_ROOT_NAMES)
    monkeypatch.setattr(link_skills, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(link_skills, "CANONICAL_ROOT", canonical_root)
    monkeypatch.setattr(link_skills, "ALIAS_ROOTS", alias_roots)
    return canonical_root, alias_roots


def test_synchronize_creates_every_alias_for_every_project_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """複数の Project Skill を 3 系統すべてへ相対 symlink で公開する。"""
    canonical_root, alias_roots = _configure_repository(
        tmp_path, monkeypatch, names=("alpha", "beta")
    )

    result = link_skills.synchronize()

    assert result == 0
    for name in ("alpha", "beta"):
        for alias_root in alias_roots:
            alias = alias_root / name
            assert link_skills._is_alias(alias)
            if not WINDOWS:
                assert os.readlink(alias) == f"../../skills/{name}"
            assert alias.resolve() == (canonical_root / name).resolve()


def test_synchronize_keeps_correct_aliases_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正しいエイリアスがある環境で再実行しても作り直さない。"""
    _, alias_roots = _configure_repository(tmp_path, monkeypatch)
    assert link_skills.synchronize() == 0
    aliases = [root / "sample-skill" for root in alias_roots]
    inodes_before = [os.lstat(alias).st_ino for alias in aliases]

    result = link_skills.synchronize()

    assert result == 0
    assert [os.lstat(alias).st_ino for alias in aliases] == inodes_before


def test_check_reports_missing_aliases_without_creating_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """check モードは不足を報告するだけでファイルを変更しない。"""
    _, alias_roots = _configure_repository(tmp_path, monkeypatch)

    result = link_skills.synchronize(check_only=True)

    assert result == 1
    assert "エイリアスが未整備" in capsys.readouterr().err
    assert all(not root.exists() for root in alias_roots)


def test_synchronize_fails_without_a_canonical_skill_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正本ディレクトリが無ければ公開先を作らず失敗する。"""
    alias_roots = tuple(tmp_path / name / "skills" for name in ALIAS_ROOT_NAMES)
    monkeypatch.setattr(link_skills, "CANONICAL_ROOT", tmp_path / "skills")
    monkeypatch.setattr(link_skills, "ALIAS_ROOTS", alias_roots)

    result = link_skills.synchronize()

    assert result == 1
    assert all(not root.exists() for root in alias_roots)


@pytest.mark.parametrize("conflict_type", ["directory", "file", "wrong_symlink"])
def test_conflict_preserves_existing_path_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conflict_type: str
) -> None:
    """衝突がある公開先を上書きせず、処理全体を失敗させる。"""
    canonical_root, alias_roots = _configure_repository(tmp_path, monkeypatch)
    conflict = alias_roots[0] / "sample-skill"
    conflict.parent.mkdir(parents=True)
    if conflict_type == "directory":
        conflict.mkdir()
        (conflict / "SKILL.md").write_text("local\n", encoding="utf-8")
    elif conflict_type == "file":
        conflict.write_text("local\n", encoding="utf-8")
    else:
        other = tmp_path / "other-skill"
        other.mkdir()
        conflict.symlink_to(other, target_is_directory=True)

    result = link_skills.synchronize()

    assert result == 1
    if conflict_type == "directory":
        assert conflict.is_dir() and not conflict.is_symlink()
        assert (conflict / "SKILL.md").read_text(encoding="utf-8") == "local\n"
    elif conflict_type == "file":
        assert conflict.is_file() and not conflict.is_symlink()
        assert conflict.read_text(encoding="utf-8") == "local\n"
    else:
        assert conflict.is_symlink()
        assert conflict.resolve() == other.resolve()
    assert all(not os.path.lexists(root / "sample-skill") for root in alias_roots[1:])
    assert (canonical_root / "sample-skill" / "SKILL.md").is_file()
