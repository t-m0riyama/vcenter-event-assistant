"""Typed access to ``CollectionContext.config``.

設定値は TOML・データベース・環境変数のどこからでも来る。**経路によって型が違う。**
環境変数由来の値はアプリの実装上つねに ``str`` であり、TOML 由来は TOML の型のままである。

つまり ``config.get("interval", 60) > 30`` のようなコードは、TOML に書いたときは動き、
管理画面や環境変数で設定したときだけ壊れる。ここのヘルパは常に同じ型を返す。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

_NumberT = TypeVar("_NumberT", int, float)

#: 真と解釈する文字列。アプリ側の ``plugins/config.py`` と一致させている
#: （ズレると管理画面での設定と挙動が食い違う）。
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


class ConfigError(ValueError):
    """設定値が期待する型・範囲でない。

    メッセージにはキー名と受け取った値の**型**だけを含め、値そのものは含めない。
    設定に機密を置くことは推奨していないが、事故があっても漏らさないためである。
    """


def _fail(key: str, value: object, expected: str) -> ConfigError:
    return ConfigError(
        f"config key {key!r} must be {expected}, got {type(value).__name__}"
    )


def get_str(
    config: Mapping[str, Any],
    key: str,
    default: str | None = None,
    *,
    choices: tuple[str, ...] | None = None,
) -> str | None:
    """文字列として読む。数値が来た場合も文字列にする。"""
    if key not in config or config[key] is None:
        value = default
    else:
        raw = config[key]
        if isinstance(raw, bool):
            raise _fail(key, raw, "a string")
        value = raw if isinstance(raw, str) else str(raw)
    if value is not None and choices is not None and value not in choices:
        raise ConfigError(
            f"config key {key!r} must be one of {', '.join(sorted(choices))}"
        )
    return value


def require_str(
    config: Mapping[str, Any], key: str, *, choices: tuple[str, ...] | None = None
) -> str:
    """必須の文字列。未設定なら :class:`ConfigError`。"""
    value = get_str(config, key, None, choices=choices)
    if value is None or value == "":
        raise ConfigError(f"config key {key!r} is required")
    return value


def get_bool(config: Mapping[str, Any], key: str, default: bool = False) -> bool:
    """真偽値として読む。``"1"`` / ``"true"`` / ``"yes"`` / ``"on"`` を真とする。"""
    if key not in config or config[key] is None:
        return default
    raw = config[key]
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in TRUE_VALUES:
            return True
        if text in FALSE_VALUES:
            return False
    raise _fail(key, raw, "a boolean")


def get_int(
    config: Mapping[str, Any],
    key: str,
    default: int | None = None,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    """整数として読む。"""
    value = _number(config, key, default, int, "an integer")
    return _bounded(key, value, minimum, maximum)


def get_float(
    config: Mapping[str, Any],
    key: str,
    default: float | None = None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    """浮動小数として読む。"""
    value = _number(config, key, default, float, "a number")
    return _bounded(key, value, minimum, maximum)


def get_str_list(
    config: Mapping[str, Any],
    key: str,
    default: tuple[str, ...] = (),
    *,
    separator: str = ",",
) -> tuple[str, ...]:
    """文字列の並びとして読む。

    環境変数では列を表せないので、区切り文字で分割した文字列も受ける。TOML 側では
    配列で書ける。空要素は落とす。
    """
    if key not in config or config[key] is None:
        return default
    raw = config[key]
    if isinstance(raw, str):
        return tuple(part.strip() for part in raw.split(separator) if part.strip())
    if isinstance(raw, (list, tuple)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    raise _fail(key, raw, "a list or a separated string")


def _number(
    config: Mapping[str, Any],
    key: str,
    default: _NumberT | None,
    caster: Callable[[Any], _NumberT],
    expected: str,
) -> _NumberT | None:
    if key not in config or config[key] is None:
        return default
    raw = config[key]
    # bool は int の派生なので、先に弾かないと True が 1 として通ってしまう。
    if isinstance(raw, bool):
        raise _fail(key, raw, expected)
    try:
        return caster(raw)
    except (TypeError, ValueError) as exc:
        raise _fail(key, raw, expected) from exc


def _bounded(
    key: str,
    value: _NumberT | None,
    minimum: _NumberT | None,
    maximum: _NumberT | None,
) -> _NumberT | None:
    if value is None:
        return None
    if minimum is not None and value < minimum:
        raise ConfigError(f"config key {key!r} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"config key {key!r} must be <= {maximum}")
    return value
