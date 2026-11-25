"""診断コマンドの雛形の確認と引数の組み立て。"""

import re
import shlex
import unicodedata
from collections.abc import Mapping, Sequence
from ipaddress import IPv4Address

_PARAMETER_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
_PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
_PARAMETER_PATTERNS = {
    "vmnic": re.compile(r"vmnic[0-9]{1,3}"),
    "vmk": re.compile(r"vmk[0-9]{1,3}"),
    "device": re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"),
}
PARAMETER_TYPES = ("vmnic", "vmk", "ipv4", "device")


class TemplateError(ValueError):
    def __init__(self, reason: str, parameter: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.parameter = parameter


class ParameterError(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("引数を確認してください。")
        self.errors = errors


def validate_template(
    template: str, param_definitions: Sequence[Mapping[str, str]]
) -> None:
    if any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in template):
        raise TemplateError("control_character")
    if len(param_definitions) > 8:
        raise TemplateError("too_many_parameters")

    names: set[str] = set()
    for definition in param_definitions:
        name = definition["name"]
        if not _PARAMETER_NAME.fullmatch(name):
            raise TemplateError("invalid_parameter_name", name)
        if name in names:
            raise TemplateError("duplicate_parameter", name)
        if definition["type"] not in PARAMETER_TYPES:
            raise TemplateError("unknown_parameter_type", name)
        names.add(name)

    used: set[str] = set()
    for match in _PLACEHOLDER.finditer(template):
        name = match[1]
        if name not in names:
            raise TemplateError("undefined_parameter", name)
        prefix = template[match.start() - 1] if match.start() else ""
        if prefix == "$":
            raise TemplateError("dollar_prefix", name)
        if prefix == "\\":
            raise TemplateError("backslash_prefix", name)
        used.add(name)
    for definition in param_definitions:
        if definition["name"] not in used:
            raise TemplateError("unused_parameter", definition["name"])


def normalize_parameter(kind: str, value: str) -> str:
    if kind == "ipv4":
        return str(IPv4Address(value))
    pattern = _PARAMETER_PATTERNS.get(kind)
    if pattern is None or not pattern.fullmatch(value):
        raise ValueError("引数の値を確認してください。")
    return value


def render_command(
    template: str,
    param_definitions: Sequence[Mapping[str, str]],
    params: Mapping[str, str],
) -> str:
    """保存済みの雛形を再検証し、照合・正規化した引数を差し込む。"""
    validate_template(template, param_definitions)
    types = {definition["name"]: definition["type"] for definition in param_definitions}
    errors = {name: "unknown" for name in params.keys() - types.keys()}
    quoted: dict[str, str] = {}
    for name, kind in types.items():
        if name not in params:
            errors[name] = "missing"
            continue
        try:
            quoted[name] = shlex.quote(normalize_parameter(kind, params[name]))
        except ValueError:
            errors[name] = "invalid_value"
    if errors:
        raise ParameterError(errors)
    return _PLACEHOLDER.sub(lambda match: quoted[match[1]], template)
