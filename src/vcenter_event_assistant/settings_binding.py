"""プロセス内 Settings 参照（main / deps / scheduler が bind する）。"""

from __future__ import annotations

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


def clear_settings_binding() -> None:
    """テスト teardown 用。"""
    global _bound
    _bound = None
