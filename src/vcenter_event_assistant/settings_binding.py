"""プロセス内 Settings 参照（main / deps / scheduler が bind する）。"""

from __future__ import annotations

import os

from vcenter_event_assistant.settings import Settings

_bound: Settings | None = None


def bind_settings(settings: Settings) -> None:
    """アプリ起動またはテストセットアップ時に Settings を登録する。"""
    global _bound
    _bound = settings


def require_settings() -> Settings:
    """bind 済み Settings を返す。未 bind なら RuntimeError。"""
    if _bound is None:
        msg = (
            "Settings が bind されていません。"
            " main.create_app またはテスト conftest で bind_settings を呼んでください。"
        )
        raise RuntimeError(msg)
    return _bound


def resolve_vea_secret_key() -> str | None:
    """
    vCenter パスワード暗号化用の秘密鍵を解決する。

    bind 済み ``Settings.vea_secret_key`` を優先し、未 bind または空のときは
    環境変数 ``VEA_SECRET_KEY`` を参照する（Alembic・単発スクリプト向け）。
    """
    if _bound is not None:
        secret = _bound.vea_secret_key
        if secret:
            return secret
    raw = os.environ.get("VEA_SECRET_KEY", "").strip()
    return raw or None


def clear_settings_binding() -> None:
    """テスト teardown 用。"""
    global _bound
    _bound = None
