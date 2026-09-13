"""設定値の型変換。

経路によって型が違うのが要点である。環境変数由来は常に ``str``、TOML 由来は TOML の型。
同じ設定が「TOML では動くが管理画面で設定すると壊れる」事故を防ぐ。
"""

from __future__ import annotations

import pytest
from vcenter_event_assistant_plugin_api import config as cfg
from vcenter_event_assistant_plugin_api.config import ConfigError

# 同じ設定を 2 つの経路で与えたもの。すべて同じ結果にならなければならない。
FROM_TOML = {"sensor": "cpu", "interval": 60, "ratio": 1.5, "enabled": True, "tags": ["a", "b"]}
FROM_ENV = {"sensor": "cpu", "interval": "60", "ratio": "1.5", "enabled": "true", "tags": "a,b"}


@pytest.mark.parametrize("source", [FROM_TOML, FROM_ENV], ids=["toml", "env"])
def test_values_read_the_same_from_either_source(source) -> None:
    assert cfg.get_str(source, "sensor") == "cpu"
    assert cfg.get_int(source, "interval") == 60
    assert cfg.get_float(source, "ratio") == 1.5
    assert cfg.get_bool(source, "enabled") is True
    assert cfg.get_str_list(source, "tags") == ("a", "b")


def test_defaults_apply_when_the_key_is_absent() -> None:
    assert cfg.get_str({}, "sensor", "system-board") == "system-board"
    assert cfg.get_int({}, "interval", 30) == 30
    assert cfg.get_float({}, "ratio", 0.5) == 0.5
    assert cfg.get_bool({}, "enabled", True) is True
    assert cfg.get_str_list({}, "tags", ("x",)) == ("x",)


def test_an_explicit_none_is_treated_as_absent() -> None:
    assert cfg.get_str({"sensor": None}, "sensor", "default") == "default"


def test_get_str_accepts_choices() -> None:
    assert cfg.get_str({"mode": "fast"}, "mode", choices=("fast", "slow")) == "fast"
    with pytest.raises(ConfigError, match="must be one of"):
        cfg.get_str({"mode": "turbo"}, "mode", choices=("fast", "slow"))


def test_require_str_rejects_missing_and_empty() -> None:
    assert cfg.require_str({"sensor": "cpu"}, "sensor") == "cpu"
    for source in ({}, {"sensor": ""}, {"sensor": None}):
        with pytest.raises(ConfigError, match="is required"):
            cfg.require_str(source, "sensor")


@pytest.mark.parametrize("text", ["1", "true", "TRUE", " yes ", "on"])
def test_truthy_strings(text: str) -> None:
    assert cfg.get_bool({"flag": text}, "flag") is True


@pytest.mark.parametrize("text", ["0", "false", "No", "off"])
def test_falsy_strings(text: str) -> None:
    assert cfg.get_bool({"flag": text}, "flag") is False


def test_an_unparseable_boolean_is_an_error() -> None:
    with pytest.raises(ConfigError):
        cfg.get_bool({"flag": "maybe"}, "flag")


def test_bounds_are_enforced() -> None:
    assert cfg.get_int({"n": 10}, "n", minimum=1, maximum=100) == 10
    with pytest.raises(ConfigError, match=">= 10"):
        cfg.get_int({"n": 5}, "n", minimum=10)
    with pytest.raises(ConfigError, match="<= 10"):
        cfg.get_float({"n": 11.0}, "n", maximum=10.0)


def test_booleans_are_not_silently_read_as_numbers() -> None:
    """``bool`` は ``int`` の派生。先に弾かないと ``True`` が 1 として通る。"""
    with pytest.raises(ConfigError):
        cfg.get_int({"n": True}, "n")
    with pytest.raises(ConfigError):
        cfg.get_str({"s": True}, "s")


def test_a_non_numeric_string_is_an_error() -> None:
    with pytest.raises(ConfigError, match="must be an integer"):
        cfg.get_int({"n": "abc"}, "n")


def test_error_messages_name_the_key_but_not_the_value() -> None:
    """設定に機密を置くことは推奨していないが、事故があっても漏らさない。"""
    with pytest.raises(ConfigError) as excinfo:
        cfg.get_int({"token": "super-secret-value"}, "token")
    assert "token" in str(excinfo.value)
    assert "super-secret-value" not in str(excinfo.value)


def test_str_list_drops_empty_parts() -> None:
    assert cfg.get_str_list({"tags": "a, ,b,"}, "tags") == ("a", "b")
