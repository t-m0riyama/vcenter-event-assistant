"""プロジェクト Skill を各 AI エージェントの実行時配置へ公開する。"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOT = REPOSITORY_ROOT / "skills"
ALIAS_ROOTS = (
    REPOSITORY_ROOT / ".cursor" / "skills",
    REPOSITORY_ROOT / ".agents" / "skills",
    REPOSITORY_ROOT / ".claude" / "skills",
)
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")


@dataclass(frozen=True)
class AliasPlan:
    """1つの実行時エイリアスに対する適用計画。"""

    alias: Path
    canonical: Path
    action: str
    legacy_target: str | None = None


class SkillAliasError(RuntimeError):
    """Skill エイリアスを安全に作成できない場合の例外。"""


def _lexists(path: Path) -> bool:
    """壊れた symlink を含めてパスの存在を判定する。"""
    return os.path.lexists(path)


def _is_junction(path: Path) -> bool:
    """Python 3.12以降の Windows Junction 判定を安全に呼び出す。"""
    checker = getattr(path, "is_junction", None)
    return bool(checker and checker())


def _is_alias(path: Path) -> bool:
    """パスがsymlinkまたはWindows Junctionかを返す。"""
    return path.is_symlink() or _is_junction(path)


def _uses_windows_junction() -> bool:
    """現在のOSでDirectory Junctionを使うかを返す。"""
    return os.name == "nt"


def _resolved(path: Path) -> Path | None:
    """パスを厳密に解決し、解決不能ならNoneを返す。"""
    try:
        return path.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError):
        return None


def _discover_skills() -> list[Path]:
    """正本ディレクトリ直下から有効なプロジェクトSkillを列挙する。"""
    if not CANONICAL_ROOT.is_dir():
        raise SkillAliasError(f"Skill 正本ディレクトリが見つかりません: {CANONICAL_ROOT}")

    skills: list[Path] = []
    for candidate in sorted(CANONICAL_ROOT.iterdir(), key=lambda path: path.name):
        if not candidate.is_dir() or not (candidate / "SKILL.md").is_file():
            continue
        if not SKILL_NAME_PATTERN.fullmatch(candidate.name):
            raise SkillAliasError(
                "Skill ディレクトリ名は小文字英数字とハイフンだけを使用してください: "
                f"{candidate}"
            )
        if candidate.is_symlink() or _is_junction(candidate):
            raise SkillAliasError(f"Skill 正本は実ディレクトリである必要があります: {candidate}")
        skills.append(candidate)

    if not skills:
        raise SkillAliasError(f"SKILL.md を持つSkillが見つかりません: {CANONICAL_ROOT}")
    return skills


def _expected_relative_target(alias: Path, canonical: Path) -> str:
    """macOS/Linux向けの相対symlink先を返す。"""
    return os.path.relpath(canonical, start=alias.parent)


def _legacy_target(alias: Path, canonical: Path) -> str:
    """直前の正本配置を指していた既知の旧symlink先を返す。"""
    legacy = REPOSITORY_ROOT / ".cursor" / "skills" / canonical.name
    return os.path.relpath(legacy, start=alias.parent)


def _classify_alias(alias: Path, canonical: Path, *, allow_legacy: bool = True) -> AliasPlan:
    """エイリアスを変更不要・新規・旧リンク移行・衝突に分類する。"""
    if not _lexists(alias):
        return AliasPlan(alias=alias, canonical=canonical, action="create")

    if _is_alias(alias) and _resolved(alias) == canonical.resolve(strict=True):
        return AliasPlan(alias=alias, canonical=canonical, action="keep")

    if allow_legacy and alias.is_symlink():
        raw_target = os.readlink(alias)
        if raw_target == _legacy_target(alias, canonical):
            return AliasPlan(
                alias=alias,
                canonical=canonical,
                action="migrate",
                legacy_target=raw_target,
            )

    if _is_alias(alias):
        reason = "別の場所または解決不能な場所を指すエイリアス"
    elif alias.is_dir():
        reason = "実ディレクトリ"
    else:
        reason = "通常ファイル"
    raise SkillAliasError(
        f"実行時Skillに{reason}が存在します。上書き・削除・移動しません: {alias}"
    )


def _build_plan(skills: list[Path]) -> list[AliasPlan]:
    """全対象を事前検査し、変更前に衝突を検出する。"""
    plans: list[AliasPlan] = []
    failures: list[str] = []
    for canonical in skills:
        for alias_root in ALIAS_ROOTS:
            alias = alias_root / canonical.name
            try:
                plans.append(_classify_alias(alias, canonical))
            except SkillAliasError as exc:
                failures.append(str(exc))
    if failures:
        raise SkillAliasError("\n".join(failures))
    return plans


def _create_alias(alias: Path, canonical: Path) -> None:
    """現在のOSに合うsymlinkまたはDirectory Junctionを作成する。"""
    alias.parent.mkdir(parents=True, exist_ok=True)
    if not _uses_windows_junction():
        alias.symlink_to(
            _expected_relative_target(alias, canonical),
            target_is_directory=canonical.is_dir(),
        )
        return

    result = subprocess.run(
        [
            "cmd.exe",
            "/d",
            "/c",
            "mklink",
            "/J",
            str(alias),
            str(canonical.resolve(strict=True)),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "詳細なし"
        raise SkillAliasError(f"Windows Junctionを作成できません: {alias}: {detail}")


def _remove_alias(alias: Path) -> None:
    """実データを辿らずsymlinkまたはJunctionそのものだけを削除する。"""
    if alias.is_symlink():
        alias.unlink()
        return
    if _is_junction(alias):
        os.rmdir(alias)
        return
    raise SkillAliasError(f"エイリアス以外は削除しません: {alias}")


def _restore_legacy_alias(plan: AliasPlan) -> None:
    """置換に失敗した既知の旧symlinkを復元する。"""
    if plan.legacy_target is None:
        return
    plan.alias.parent.mkdir(parents=True, exist_ok=True)
    plan.alias.symlink_to(plan.legacy_target, target_is_directory=True)


def _rollback_plan(plan: AliasPlan) -> None:
    """1件の変更を安全に取り消し、必要なら旧symlinkを復元する。"""
    if _lexists(plan.alias):
        _remove_alias(plan.alias)
    if plan.action == "migrate":
        _restore_legacy_alias(plan)


def _apply_plan(plans: list[AliasPlan]) -> None:
    """計画を適用し、失敗時はこの実行が行った変更だけを戻す。"""
    applied: list[AliasPlan] = []
    try:
        for plan in plans:
            if plan.action == "keep":
                continue
            if plan.action == "migrate":
                _remove_alias(plan.alias)
            try:
                _create_alias(plan.alias, plan.canonical)
                if not _is_alias(plan.alias) or _resolved(plan.alias) != plan.canonical.resolve(
                    strict=True
                ):
                    raise SkillAliasError(
                        f"作成した実行時Skillが正本を指していません: {plan.alias}"
                    )
            except Exception as create_exc:
                try:
                    _rollback_plan(plan)
                except Exception as rollback_exc:
                    raise SkillAliasError(
                        f"{create_exc}\n変更中のエイリアスをロールバックできません: "
                        f"{plan.alias}: {rollback_exc}"
                    ) from create_exc
                raise
            applied.append(plan)
    except Exception as exc:
        rollback_failures: list[str] = []
        for plan in reversed(applied):
            try:
                _rollback_plan(plan)
            except Exception as rollback_exc:  # pragma: no cover - OS障害時の最終防衛
                rollback_failures.append(f"{plan.alias}: {rollback_exc}")
        if rollback_failures:
            raise SkillAliasError(
                f"{exc}\nロールバックにも失敗しました:\n" + "\n".join(rollback_failures)
            ) from exc
        if isinstance(exc, SkillAliasError):
            raise
        raise SkillAliasError(str(exc)) from exc


def _verify(plans: list[AliasPlan]) -> None:
    """全公開先が同じ正本へ解決されることを確認する。"""
    failures: list[str] = []
    for plan in plans:
        if not _is_alias(plan.alias):
            failures.append(f"実行時Skillのエイリアスがありません: {plan.alias}")
            continue
        resolved = _resolved(plan.alias)
        canonical = plan.canonical.resolve(strict=True)
        if resolved != canonical:
            failures.append(
                f"実行時Skillの参照先が正本と違います: {plan.alias} → {resolved} "
                f"(正本: {canonical})"
            )
    if failures:
        raise SkillAliasError("\n".join(failures))


def synchronize(*, check_only: bool = False) -> int:
    """Skill公開先を同期または検査し、プロセス終了コードを返す。"""
    try:
        skills = _discover_skills()
        plans = _build_plan(skills)
        if check_only:
            missing = [plan for plan in plans if plan.action != "keep"]
            if missing:
                details = "\n".join(
                    f"実行時Skillのエイリアスが未整備です: {plan.alias} ({plan.action})"
                    for plan in missing
                )
                raise SkillAliasError(details)
        else:
            _apply_plan(plans)
        verified_plans = _build_plan(skills)
        _verify(verified_plans)
    except SkillAliasError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    mode = "検査" if check_only else "公開"
    print(f"OK: Project Skill {len(skills)}件 / 公開先 {len(ALIAS_ROOTS)}系統 ({mode})")
    return 0


def main() -> int:
    """CLI引数を解釈してSkillエイリアスを同期する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="エイリアスを変更せず、すべて正本を指すか検査する",
    )
    args = parser.parse_args()
    return synchronize(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
