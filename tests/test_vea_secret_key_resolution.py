"""``resolve_vea_secret_key`` のユニットテスト。"""

from __future__ import annotations

import pytest

from vcenter_event_assistant.db.encrypted_string import ENC_PREFIX, EncryptedString
from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant.settings_binding import (
    bind_settings,
    clear_settings_binding,
    resolve_vea_secret_key,
)


def test_resolve_vea_secret_key_prefers_bound_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEA_SECRET_KEY", "from-env")
    bind_settings(Settings(vea_secret_key="from-bind"))
    try:
        assert resolve_vea_secret_key() == "from-bind"
    finally:
        clear_settings_binding()


def test_resolve_vea_secret_key_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_binding()
    monkeypatch.setenv("VEA_SECRET_KEY", "from-env")
    try:
        assert resolve_vea_secret_key() == "from-env"
    finally:
        monkeypatch.delenv("VEA_SECRET_KEY", raising=False)


def test_encrypted_string_uses_env_secret_without_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_binding()
    monkeypatch.setenv("VEA_SECRET_KEY", "env-only-key")
    col = EncryptedString(2048)
    try:
        stored = col.process_bind_param("plain-secret", None)
        assert stored is not None
        assert stored.startswith(ENC_PREFIX)
        assert col.process_result_value(stored, None) == "plain-secret"
    finally:
        monkeypatch.delenv("VEA_SECRET_KEY", raising=False)
