"""登録済みの vCenter とアプリの DB から PDL・APD のイベントの形を確認する。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import re
import secrets
import sys
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pyVmomi import vim
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.collectors.connection import connect_vcenter, disconnect
from vcenter_event_assistant.db.models import EventRecord, VCenter
from vcenter_event_assistant.settings import Settings, get_settings
from vcenter_event_assistant.settings_binding import bind_settings
from vcenter_event_assistant_plugin_api.timeutils import ensure_aware

if __package__:
    from .probe_inventory_config import _read_only_settings
else:
    from probe_inventory_config import _read_only_settings  # type: ignore[no-redef]

PDL_TYPES = (
    "esx.problem.scsi.device.state.permanentloss",
    "esx.problem.psastor.device.state.permanentloss",
)
EVENT_TYPES = (
    *PDL_TYPES,
    "esx.problem.storage.apd.start",
    "esx.problem.storage.apd.timeout",
    "esx.clear.storage.apd.exit",
)
_QUERY_LIMIT = 1000
_MAX_SPLIT_DEPTH = 5
_MAX_SIBLING_TYPES = 10
_CLOCK_MARGIN = timedelta(minutes=5)
_PAIR_LIMIT = timedelta(seconds=60)
_SIMULTANEOUS = timedelta(seconds=1)
_TOP = 5
_OMITTED = "伏せきれない値があったので省略"
_CATALOG_OUTPUT = ("key", "category", "fullFormat", "formatOnHost")
_CATALOG_FIELDS = (*_CATALOG_OUTPUT, "formatOnVm", "description", "longDescription")
_CATALOG_FORMATS = ("fullFormat", "formatOnHost", "formatOnVm")
_WORDS = frozenset(
    """a affected all any apd are as at became been by cannot datastore datastores
    device devices disk due entered exited for from gone has have host if in inaccessible
    is lost loss no of on or path paths pdl permanent permanently removed
    restored state storage the timed timeout to unavailable was were with
    after be being down failed fast filesystem identifier now seconds will""".split()
)
_EVENT_REFS = {
    "host": "host",
    "ds": "datastore",
    "vm": "vm",
    "computeResource": "computeResource",
    "datacenter": "datacenter",
    "dvs": "dvs",
    "net": "network",
}
_ARGUMENT_KEYS = frozenset(
    {
        "addr",
        "detail",
        "device",
        "disk",
        "host",
        "lun",
        "path",
        "retry",
        "vendor",
        "datastore",
    }
)
_TYPES = frozenset(
    {
        "EventEx",
        "ExtendedEvent",
        "HostSystem",
        "Datastore",
        "VirtualMachine",
        "ComputeResource",
        "ClusterComputeResource",
        "Datacenter",
        "Network",
        "DistributedVirtualSwitch",
        "VmwareDistributedVirtualSwitch",
        "DistributedVirtualPortgroup",
        "ResourcePool",
        "Folder",
        "str",
        "int",
        "long",
        "float",
        "bool",
        "list",
        "dict",
        "tuple",
        "datetime",
        "NoneType",
    }
)
_DEVICE = re.compile(
    r"(?<![\w.])(?:(?:naa|eui|vml)\.[0-9a-f]+|"
    r"t10\.[\w+.-]*[\w+-]|mpx\.[\w.-]*[\w-](?::C\d+:T\d+:L\d+)?)"
    r"(?![\w+-]|\.[\w])",
    re.IGNORECASE,
)
_HOST_MOID = re.compile(r"host-\d+", re.I)
_MOID = re.compile(
    r"(?<![\w.-])(?:domain-[cs]|(?:host|datastore|vm|datacenter|resgroup|group|"
    r"network|dvs|dvportgroup)-)\d+(?![\w-]|\.[\w])",
    re.I,
)
_STORAGE_PATH = re.compile(r"/vmfs/volumes/[^/\s'\"<>]+")
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_WORD = re.compile(r"[A-Za-z]+")
_TOKEN_CHAR = r"(?:[A-Za-z0-9_]|[^\x00-\x7f\s“”‘’「」『』])"
_TOKEN = rf"{_TOKEN_CHAR}+(?:[./:@%+\\'-]+{_TOKEN_CHAR}+)*"
_QUOTES = (
    r""""(?:\\(?:.|$)|[^"\\])*(?:"|$)|(?<!\w)'(?:\\(?:.|$)|[^'\\])*(?:'|$)"""
    r"|“[^”]*(?:”|$)|‘[^’]*(?:’|$)|「[^」]*(?:」|$)|『[^』]*(?:』|$)"
)
_SYMBOLS = frozenset(" .,;:!?()[]{}<>-+/_=*%&@#|\\")
_UNKNOWN = "{値}"
_AFFECTED_DATASTORES = re.compile(
    r"(\bAffected[ \t]+datastores(?:[ \t]*\([ \t]*if[ \t]+any[ \t]*\))?[ \t]*:)"
    r"[^\r\n\v\f\x85\u2028\u2029]*",
    re.IGNORECASE,
)
_RESIDUAL = re.compile(
    rf"{_DEVICE.pattern}|{_MOID.pattern}|{_STORAGE_PATH.pattern}|"
    r"\b(?:vmhba\d*|iqn[.:]|naa[.:]|eui[.:]|t10[.:]|mpx[.:]|vml[.:])|"
    r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9][a-z0-9-]*\b|"
    r"(?<!\w)(?:[a-f0-9]{1,4}:){2,}[a-f0-9:]*|"
    r"(?<!\w)(?:[a-f0-9]{1,4})?::[a-f0-9:]+|"
    r"\b[0-9a-f]{8}-(?:(?:[0-9a-f]{4}-){3}|[0-9a-f]{8}-[0-9a-f]{4}-)[0-9a-f]{12}\b",
    re.I,
)
_VMOMI_DUMP = re.compile(r"^\([\w.]+\)\s*\{")
# 値の区切りを崩す制御文字も、表示時にエスケープする。
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


class _Report:
    def __init__(self) -> None:
        self.salt = secrets.token_bytes(32)
        self.private: set[str] = set()
        self.lines: list[tuple[str, str | None, bool, frozenset[str]]] = []

    def remember(self, *values: str | None) -> None:
        for value in values:
            if value:
                self.private.update(
                    part.casefold()
                    for raw in [value, *value.splitlines()]
                    if len(part := raw.strip()) >= 4 and not _NUMBER.fullmatch(part)
                )

    def remember_host(self, value: str | None) -> None:
        if value:
            self.remember(value, value.partition(".")[0])

    def alias(self, value: str) -> str:
        return (
            "h:"
            + hashlib.blake2s(value.encode(), key=self.salt, digest_size=5).hexdigest()
        )

    def add(
        self,
        line: str,
        *,
        original: str | None = None,
        template: bool = False,
        allowed_words: frozenset[str] = frozenset(),
    ) -> None:
        self.lines.append((line, original, template, allowed_words))

    def emit(self) -> None:
        # 全節を組み立ててから照合する。後で見つかった値や表示幅で切れた値も調べる。
        for line, original, template, allowed_words in self.lines:
            rendered = _CONTROL.sub(lambda m: ascii(m[0])[1:-1], line)
            candidate = (
                "\n".join((line, rendered, original)).casefold()
                if original is not None
                else ""
            )
            if original is not None and (
                (template and _RESIDUAL.search(original))
                or any(value in candidate for value in self.private - allowed_words)
            ):
                print(_OMITTED)
            else:
                print(rendered)


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _type_text(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "_wsdlName", value))


def _metadata(value: str, allowed: frozenset[str], report: _Report) -> str:
    if value in allowed or not value:
        return value or "-"
    report.remember(value)
    return report.alias(value)


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _catalog(manager: Any, report: _Report) -> tuple[dict[str, set[str]], list[str]]:
    report.add("[カタログ]")
    try:
        entries = manager.description.eventInfo or ()
    except Exception as exc:
        report.add(f"eventInfo 読み取り失敗={type(exc).__name__}")
        return {}, []

    by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
    siblings: dict[str, set[str]] = defaultdict(set)
    for index, entry in enumerate(entries):
        fields = {}
        for name in _CATALOG_FIELDS:
            try:
                fields[name] = _type_text(getattr(entry, name, None))
            except Exception as exc:
                report.add(
                    f"eventInfo[{index}].{name} 読み取り失敗={type(exc).__name__}"
                )
        prefix, separator, _ = fields.get("fullFormat", "").partition("|")
        ids = {fields.get("key", ""), prefix.strip() if separator else ""}
        for kind in EVENT_TYPES:
            if kind in ids:
                by_type[kind].append(fields)
            siblings[kind].update(
                event_id
                for event_id in ids
                if re.fullmatch(re.escape(kind) + r"(?:\.[a-z][a-z0-9_]*)+", event_id)
            )

    found = sorted(set().union(*siblings.values()))
    selected = found[:_MAX_SIBLING_TYPES]
    words: dict[str, set[str]] = defaultdict(set)
    for kind in EVENT_TYPES:
        matches = by_type[kind]
        report.add(f"{kind} 一致={len(matches)}")
        for entry_fields in matches:
            for name in _CATALOG_FORMATS:
                value = entry_fields.get(name, "")
                if name == "fullFormat" and value.partition("|")[0].strip() == kind:
                    value = value.partition("|")[2]
                words[kind].update(
                    token[0].lower()
                    for token in re.finditer(
                        rf"(?:{_QUOTES})|\{{[^}}]*\}}|{_TOKEN}", value
                    )
                    if _WORD.fullmatch(token[0])
                )
            fields_to_show = {
                name: entry_fields.get(name, "") for name in _CATALOG_OUTPUT
            }
            report.add(
                "  "
                + " ".join(
                    f"{name}={_quoted(value[:300])}"
                    for name, value in fields_to_show.items()
                ),
                original="\n".join(fields_to_show.values()),
            )
        selected_for_kind = siblings[kind].intersection(selected)
        if selected_for_kind:
            sibling_ids = " ".join(sorted(selected_for_kind))
            report.add(f"  兄弟 ID {sibling_ids}", original=sibling_ids)
    if len(found) > len(selected):
        report.add(f"  問い合わせ上限で省いた兄弟 ID 数={len(found) - len(selected)}")
    return words, selected


@dataclass
class _Message:
    text: str
    replacements: dict[str, str] = field(default_factory=dict)

    def replace(self, value: str | None, label: str, report: _Report) -> None:
        if value and value.strip():
            if label == "host":
                report.remember_host(value)
                short, dot, _ = value.partition(".")
                if dot and short:
                    self.replacements.setdefault(short, label)
            else:
                report.remember(value)
            self.replacements.setdefault(value, label)

    def template(self, report: _Report, words: set[str]) -> str | None:
        report.remember(*_device_ids(self.text))
        if _VMOMI_DUMP.match(self.text):
            return None
        # 長い値を先に照合し、置換後のプレースホルダーを再置換しない。
        values = sorted(self.replacements, key=len, reverse=True)
        literals = "|".join(map(re.escape, values))
        pattern = re.compile(
            rf"(?P<quote>{_QUOTES})|"
            + (
                rf"(?P<value>(?<![\w.-])(?:{literals})(?![\w-]|\.[\w]))|"
                if literals
                else ""
            )
            + rf"(?P<device>{_DEVICE.pattern})|(?P<moid>{_MOID.pattern})|"
            rf"(?P<path>{_STORAGE_PATH.pattern})|(?P<token>{_TOKEN})|.",
            re.IGNORECASE | re.DOTALL,
        )
        labels = {value.casefold(): label for value, label in self.replacements.items()}

        def substitution(match: re.Match[str]) -> str:
            value = match[0]
            group = match.lastgroup
            if group in {"value", "device", "moid", "path"}:
                report.remember(value)
                label = (
                    labels.get(value.casefold())
                    or {
                        "value": "arg",
                        "device": "device",
                        "moid": "moid",
                        "path": "datastore",
                    }[group]
                )
                return "{" + label + "}"
            if group == "quote":
                return _UNKNOWN
            if value in _SYMBOLS or (_WORD.fullmatch(value) and value.lower() in words):
                return value
            if value.isspace():
                return " "
            return _UNKNOWN

        # 句点やカンマは名前にも入る。行末までを字句処理で「値」になる 1 文字にする。
        body = _AFFECTED_DATASTORES.sub(lambda match: match[1] + " \0", self.text)
        return re.sub(
            r"\{値\}(?:\s*\{値\})+", _UNKNOWN, pattern.sub(substitution, body)
        )


def _device_ids(value: str) -> set[str]:
    return {match[0] for match in _DEVICE.finditer(value)}


def _device_key(device: str) -> str:
    prefix, suffix = device.split(".", 1)
    prefix = prefix.lower()
    return (
        prefix + "." + (suffix.lower() if prefix in {"naa", "eui", "vml"} else suffix)
    )


def _shape(value: str | None) -> str:
    if not value:
        return "empty"
    candidate = value.strip()
    if _DEVICE.fullmatch(candidate):
        prefix, suffix = candidate.lower().split(".", 1)
        return (
            f"{prefix}.+{len(suffix)}hex" if prefix in {"naa", "eui"} else f"{prefix}."
        )
    if _NUMBER.fullmatch(candidate):
        return "number"
    try:
        return f"IPv{ipaddress.ip_address(candidate).version}"
    except ValueError:
        return "other"


def _argument_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [item for nested in value for item in _argument_values(nested)]
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _argument_values(nested)]
    if hasattr(value, "_moId"):
        return [str(value._moId)]
    if hasattr(value, "_GetPropertyList"):
        return [
            item
            for prop in value._GetPropertyList()
            for item in _argument_values(getattr(value, prop.name, None))
        ]
    return [str(value)]


@dataclass
class _Occurrence:
    kind: str
    time: datetime | None
    host: str | None
    device: str | None
    device_candidates: int


@dataclass
class _Event(_Occurrence):
    wire_type: str
    message: _Message
    arguments: set[tuple[str, str, str]]
    refs: dict[str, tuple[str | None, str | None]]
    object_type: str
    object_id: str | None
    object_name: str | None
    body_matches: bool


def _observe(event: Any, report: _Report) -> _Event:
    wire_type = _type_text(type(event))
    kind = getattr(event, "eventTypeId", None) or wire_type
    message = _Message(getattr(event, "fullFormattedMessage", None) or "")
    report.remember(_str_or_none(getattr(event, "userName", None)))
    refs = {}
    for role, property_name in _EVENT_REFS.items():
        argument = getattr(event, role, None)
        if argument is None:
            continue
        name = _str_or_none(getattr(argument, "name", None))
        ref = getattr(argument, property_name, None)
        moid = _str_or_none(getattr(ref, "_moId", None))
        refs[role] = name, moid
        message.replace(name, role, report)
        message.replace(moid, role, report)

    object_type = _type_text(getattr(event, "objectType", None)).removeprefix("vim.")
    object_id = _str_or_none(getattr(event, "objectId", None))
    object_name = _str_or_none(getattr(event, "objectName", None))
    is_host_object = object_type == "HostSystem" or (
        not object_type and _HOST_MOID.fullmatch(object_id or "") is not None
    )
    object_label = (
        "host" if is_host_object else {"Datastore": "ds"}.get(object_type, "object")
    )
    message.replace(object_name, object_label, report)
    message.replace(object_id, object_label, report)
    host = refs.get("host", (None, None))[1]
    if host is None and is_host_object:
        host = object_id
    extended_ref = getattr(event, "managedObject", None)
    extended_id = _str_or_none(getattr(extended_ref, "_moId", None))
    is_host_ref = isinstance(extended_ref, vim.HostSystem)
    message.replace(extended_id, "host" if is_host_ref else "moid", report)
    if host is None and is_host_ref:
        host = extended_id

    arguments: set[tuple[str, str, str]] = set()
    argument_devices = set()
    for argument in (
        getattr(event, "arguments", None) or getattr(event, "data", None) or ()
    ):
        key = argument.key or "arg"
        if not re.fullmatch(r"[1-9][0-9]?", key):
            key = _metadata(key, _ARGUMENT_KEYS, report)
        label = "arg" if key.startswith("h:") else key
        values = _argument_values(argument.value)
        shapes = {_shape(value) for value in values} or {"empty"}
        value_type = _metadata(type(argument.value).__name__, _TYPES, report)
        arguments.update((key, value_type, shape) for shape in shapes)
        for value in values:
            message.replace(value, label, report)
            argument_devices.update(_device_ids(value))

    body_devices = _device_ids(message.text)
    report.remember(*argument_devices, *body_devices)
    # arguments を優先する。複数候補があれば本文との共通部分で絞る。
    argument_keys = {_device_key(device) for device in argument_devices}
    body_keys = {_device_key(device) for device in body_devices}
    devices = (
        (argument_keys & body_keys or argument_keys) if argument_keys else body_keys
    )
    device = next(iter(devices)) if len(devices) == 1 else None
    created = getattr(event, "createdTime", None)
    return _Event(
        kind=kind,
        time=ensure_aware(created) if created is not None else None,
        host=host,
        device=device,
        device_candidates=len(devices),
        wire_type=_metadata(wire_type, _TYPES, report),
        message=message,
        arguments=arguments,
        refs=refs,
        object_type=_metadata(object_type, _TYPES, report),
        object_id=object_id,
        object_name=object_name,
        body_matches=len(body_keys) == 1 and body_keys == argument_keys,
    )


def _query(
    manager: Any,
    kind: str,
    begin: datetime,
    end: datetime,
    now: datetime,
    report: _Report,
    depth: int = 0,
) -> list[Any]:
    # eventTypeId は EventEx と ExtendedEvent の ID も照合する。非推奨の type は指定しない。
    spec = vim.event.EventFilterSpec(
        eventTypeId=[kind],
        time=vim.event.EventFilterSpec.ByTime(beginTime=begin, endTime=end),
        disableFullMessage=False,
        maxCount=_QUERY_LIMIT,
    )
    rows = list(manager.QueryEvents(spec) or ())
    if len(rows) < _QUERY_LIMIT:
        return rows
    middle = begin + (end - begin) / 2
    if depth >= _MAX_SPLIT_DEPTH or not begin < middle < end:
        report.add(
            f"{kind} QueryEvents の上限 {_QUERY_LIMIT} 件に達した範囲 "
            f"{_days_ago(begin, now):.6f}〜"
            f"{_days_ago(end, now):.6f}日前"
        )
        return rows
    left = _query(manager, kind, begin, middle, now, report, depth + 1)
    right = _query(manager, kind, middle, end, now, report, depth + 1)
    # ByTime の両端を含む検索で、境界にある同じイベントが重複して返る。
    keys = {getattr(event, "key", None) for event in left}
    return left + [
        event
        for event in right
        if (key := getattr(event, "key", None)) is None or key not in keys
    ]


def _days_ago(when: datetime, now: datetime) -> float:
    return max(0, (now - when).total_seconds() / 86400)


def _period(times: list[datetime], now: datetime) -> str:
    if not times:
        return "最古=- 最新=-"
    oldest = _days_ago(min(times), now)
    newest = _days_ago(max(times), now)
    return f"最古={oldest:.2f}日前 最新={newest:.2f}日前"


def _messages(messages: list[_Message], report: _Report, words: set[str]) -> None:
    allowed_words = frozenset(word.casefold() for word in words)
    templates = Counter(message.template(report, words) for message in messages)
    if templates.pop(None, 0):
        report.add(_OMITTED)
    for template, count in templates.most_common(_TOP):
        if template is not None:
            report.add(
                f"  本文 件数={count} {_quoted(template[:300])}"
                if template
                else f"  本文 件数={count} (なし)",
                original=template,
                template=True,
                allowed_words=allowed_words,
            )
    if len(templates) > _TOP:
        report.add(f"  ほかの本文の型={len(templates) - _TOP}")


def _query_summary(
    events: list[_Event],
    now: datetime,
    report: _Report,
    catalog_words: dict[str, set[str]],
) -> None:
    for kind in EVENT_TYPES:
        rows = [event for event in events if event.kind == kind]
        period = _period([row.time for row in rows if row.time is not None], now)
        report.add(f"{kind} 件数={len(rows)} {period}")
        if not rows:
            continue
        for wire, count in sorted(Counter(row.wire_type for row in rows).items()):
            report.add(f"  API型={wire} 件数={count}")
        for object_type, count in sorted(
            Counter(row.object_type for row in rows).items()
        ):
            report.add(f"  objectType={object_type or '-'} 件数={count}")
        presence = " ".join(
            f"{role}あり={sum(role in row.refs for row in rows)}"
            for role in _EVENT_REFS
        )
        report.add(
            f"  objectIdあり={sum(row.object_id is not None for row in rows)} {presence}"
        )
        report.add(
            f"  本文と引数のデバイス一致={sum(row.body_matches for row in rows)}"
        )
        shapes = Counter(argument for row in rows for argument in row.arguments)
        for (key, value_type, shape), count in sorted(shapes.items()):
            report.add(f"  argument key={key} 型={value_type} 形={shape} 件数={count}")

        samples = Counter(_reference_sample(row, report) for row in rows)
        for sample, count in samples.most_common(_TOP):
            if sample:
                report.add(f"  対象 件数={count} {sample}")
        _messages(
            [row.message for row in rows],
            report,
            set(_WORDS) | catalog_words.get(kind, set()),
        )


def _reference_sample(row: _Event, report: _Report) -> str:
    refs = {
        "objectId": row.object_id,
        "objectName": row.object_name,
        "host.id": row.host,
        "device": row.device,
    }
    for role, (name, moid) in row.refs.items():
        if name:
            refs[f"{role}.name"] = name
        if moid:
            refs[f"{role}.id"] = moid
    return " ".join(
        f"{key}={report.alias(value)}" for key, value in refs.items() if value
    )


_GAP_BINS = (
    ("0", lambda gap: gap == 0),
    ("0超〜1", lambda gap: 0 < gap <= 1),
    ("1超〜10", lambda gap: 1 < gap <= 10),
    ("10超〜60", lambda gap: 10 < gap <= 60),
    ("60超〜600", lambda gap: 60 < gap <= 600),
    ("600超〜3600", lambda gap: 600 < gap <= 3600),
    ("3600超", lambda gap: gap > 3600),
)


def _gap_summary(
    label: str,
    gaps: Counter[float],
    report: _Report,
    *,
    sign_label: str = "psastor−scsi",
) -> None:
    if not gaps:
        return
    absolute = " ".join(
        f"{bucket}秒={sum(count for gap, count in gaps.items() if contains(abs(gap)))}"
        for bucket, contains in _GAP_BINS
    )
    report.add(f"  {label} 絶対差 {absolute}")
    report.add(f"  {label} {sign_label} 最小={min(gaps):g}秒 最大={max(gaps):g}秒")
    for sign, polarity in (("負", -1), ("正", 1)):
        signed = " ".join(
            f"{bucket}秒={sum(count for gap, count in gaps.items() if contains(polarity * gap))}"
            for bucket, contains in _GAP_BINS[1:]
        )
        report.add(f"  {label} {sign} {signed}")


def _simultaneous_devices(moments: dict[datetime, set[str]]) -> int:
    # 各時刻から 1 秒先までのデバイスを数え、起点の時刻ごとに一度だけ集計する。
    times = sorted(moments)
    active: Counter[str] = Counter()
    end = count = 0
    for start in times:
        while end < len(times) and times[end] - start <= _SIMULTANEOUS:
            active.update(moments[times[end]])
            end += 1
        count += len(active) > 1
        for device in moments[start]:
            active[device] -= 1
            if not active[device]:
                del active[device]
    return count


def _nearest_gaps(
    origins: list[datetime], targets: list[datetime], *, polarity: int = 1
) -> Counter[float]:
    if not targets:
        return Counter()
    ordered = sorted(targets)
    gaps: Counter[float] = Counter()
    for origin in origins:
        position = bisect_left(ordered, origin)
        closest = min(
            ordered[max(0, position - 1) : position + 1], key=lambda t: abs(t - origin)
        )
        gaps[polarity * (closest - origin).total_seconds()] += 1
    return gaps


def _pdl_pairs(events: Sequence[_Occurrence], report: _Report, *, source: str) -> None:
    report.add(f"[PDL の組（{source}）]")
    by_target: dict[tuple[str, str], dict[str, list[datetime]]] = defaultdict(
        lambda: defaultdict(list)
    )
    by_host: dict[str, dict[datetime, set[str]]] = defaultdict(lambda: defaultdict(set))
    host_times: dict[str, dict[str, list[datetime]]] = defaultdict(
        lambda: defaultdict(list)
    )
    missing_device = ambiguous_device = missing_host = missing_time = 0
    for row in events:
        if row.kind not in PDL_TYPES:
            continue
        missing_device += row.device_candidates == 0
        ambiguous_device += row.device_candidates > 1
        missing_host += row.host is None
        missing_time += row.time is None
        if row.host is not None and row.time is not None:
            host_times[row.host][row.kind].append(row.time)
        if row.device is not None and row.host is not None and row.time is not None:
            by_target[row.host, row.device][row.kind].append(row.time)
            by_host[row.host][row.time].add(row.device)

    gaps: Counter[float] = Counter()
    nearest: Counter[float] = Counter()
    nearest_reverse: Counter[float] = Counter()
    unmatched: Counter[str] = Counter()
    duplicates: Counter[str] = Counter()
    min_intervals: dict[str, timedelta] = {}
    windows: list[timedelta] = []
    for kinds in by_target.values():
        scsi, psastor = (sorted(kinds[kind]) for kind in PDL_TYPES)
        windows_by_time = dict.fromkeys(scsi, _PAIR_LIMIT)
        for kind, times in zip(PDL_TYPES, (scsi, psastor), strict=True):
            unique_times = sorted(set(times))
            duplicates[kind] += len(times) - len(unique_times)
            for before, after in zip(unique_times, unique_times[1:]):
                interval = after - before
                min_intervals[kind] = min(interval, min_intervals.get(kind, interval))
                if kind == PDL_TYPES[0]:
                    for when in (before, after):
                        windows_by_time[when] = min(windows_by_time[when], interval / 2)
        nearest.update(_nearest_gaps(scsi, psastor))
        nearest_reverse.update(_nearest_gaps(psastor, scsi, polarity=-1))
        candidates = []
        for i, a in enumerate(scsi):
            window = windows_by_time[a]
            windows.append(window)
            start = bisect_left(psastor, a - window)
            end = bisect_right(psastor, a + window)
            for j in range(start, end):
                gap = (psastor[j] - a).total_seconds()
                candidates.append((abs(gap), i, j, gap))

        # 時刻差が小さい順に、どちらのイベントも一度だけ使う。
        used_scsi: set[int] = set()
        used_psastor: set[int] = set()
        for _, i, j, gap in sorted(candidates):
            if i not in used_scsi and j not in used_psastor:
                gaps[gap] += 1
                used_scsi.add(i)
                used_psastor.add(j)
        unmatched[PDL_TYPES[0]] += len(scsi) - len(used_scsi)
        unmatched[PDL_TYPES[1]] += len(psastor) - len(used_psastor)

    if windows:
        report.add(
            f"  組の窓 最小={min(windows).total_seconds():g}秒 最大={max(windows).total_seconds():g}秒"
        )
    for kind in PDL_TYPES:
        shortest = min_intervals.get(kind)
        shown = "-" if shortest is None else f"{shortest.total_seconds():g}秒"
        report.add(f"  {kind} 同種別の最小間隔={shown} 相手なし={unmatched[kind]}")
        report.add(f"  {kind} 同じ時刻の重複={duplicates[kind]}")
    report.add(f"  両種別の組={gaps.total()}")
    _gap_summary("組の時刻差", gaps, report)
    _gap_summary("各 scsi に最も近い psastor の時刻差", nearest, report)
    _gap_summary("各 psastor に最も近い scsi の時刻差", nearest_reverse, report)
    host_nearest: Counter[float] = Counter()
    host_reverse: Counter[float] = Counter()
    for types in host_times.values():
        scsi, psastor = (types[kind] for kind in PDL_TYPES)
        host_nearest.update(_nearest_gaps(scsi, psastor))
        host_reverse.update(_nearest_gaps(psastor, scsi, polarity=-1))
    _gap_summary(
        "同じホストで各 scsi に最も近い psastor の時刻差", host_nearest, report
    )
    _gap_summary(
        "同じホストで各 psastor に最も近い scsi の時刻差", host_reverse, report
    )
    simultaneous = sum(_simultaneous_devices(moments) for moments in by_host.values())
    report.add(f"  同じホストの1秒以内に別デバイスあり={simultaneous}")
    report.add(
        f"  デバイスなし={missing_device} デバイス候補複数={ambiguous_device}"
        f" ホスト不明={missing_host} 時刻不明={missing_time}"
    )


def _sibling_summary(
    kind: str, events: list[_Event], pdl: Sequence[_Occurrence], report: _Report
) -> None:
    report.add(f"{kind} 兄弟イベント件数={len(events)}")
    pdl_times: dict[str, list[datetime]] = defaultdict(list)
    for row in pdl:
        if row.kind in PDL_TYPES and row.host is not None and row.time is not None:
            pdl_times[row.host].append(row.time)
    sibling_times: dict[str, list[datetime]] = defaultdict(list)
    for row in events:
        if row.host is not None and row.time is not None:
            sibling_times[row.host].append(row.time)
    gaps: Counter[float] = Counter()
    for host, times in sibling_times.items():
        gaps.update(_nearest_gaps(times, pdl_times[host], polarity=-1))
    _gap_summary(
        "同じホストで最も近い PDL との時刻差", gaps, report, sign_label="兄弟−PDL"
    )


async def _read_database(
    name: str, settings: Settings
) -> tuple[VCenter | None, list[EventRecord]]:
    url = _read_only_settings(settings).database_url
    if make_url(url).drivername == "postgresql+asyncpg":
        engine = create_async_engine(
            url,
            connect_args={"server_settings": {"default_transaction_read_only": "on"}},
        )
    else:
        engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, autoflush=False)() as session:
            if session.get_bind().dialect.name == "postgresql":
                await session.execute(text("SET TRANSACTION READ ONLY"))
            center = await session.scalar(select(VCenter).where(VCenter.name == name))
            if center is None:
                return None, []
            rows = await session.scalars(
                select(EventRecord)
                .where(
                    EventRecord.vcenter_id == center.id,
                    EventRecord.event_type.in_(EVENT_TYPES),
                )
                .options(selectinload(EventRecord.entities))
                .order_by(EventRecord.id)
            )
            return center, list(rows)
    finally:
        await engine.dispose()


def _database_summary(
    rows: list[EventRecord],
    now: datetime,
    report: _Report,
    catalog_words: dict[str, set[str]],
) -> None:
    report.add("[アプリの DB]")
    occurrences = []
    allowed_roles = frozenset((*_EVENT_REFS, "object", "managedObject", "entity"))
    for kind in EVENT_TYPES:
        selected = [row for row in rows if row.event_type == kind]
        times = [ensure_aware(row.occurred_at) for row in selected]
        report.add(f"{kind} 行数={len(selected)} {_period(times, now)}")
        roles: Counter[tuple[str, str]] = Counter()
        messages = []
        for row in selected:
            message = _Message(row.message)
            report.remember(row.user_name)
            host = None
            object_host = None
            for entity in row.entities:
                if entity.vcenter_id != row.vcenter_id:
                    continue
                role = _metadata(entity.role, allowed_roles, report)
                entity_type = _metadata(entity.entity_type or "", _TYPES, report)
                roles[role, entity_type] += 1
                is_untyped_host_object = (
                    entity.role == "object"
                    and not entity.entity_type
                    and _HOST_MOID.fullmatch(entity.entity_moid or "") is not None
                )
                if is_untyped_host_object and object_host is None:
                    object_host = entity.entity_moid
                if entity.entity_moid and (
                    entity.role == "host"
                    or (host is None and entity_type == "HostSystem")
                ):
                    host = entity.entity_moid
                label = (
                    "host"
                    if entity.role == "host" or is_untyped_host_object
                    else {
                        "HostSystem": "host",
                        "Datastore": "ds",
                    }.get(entity_type, role if role in allowed_roles else "entity")
                )
                message.replace(entity.entity_name, label, report)
                message.replace(entity.entity_moid, label, report)
            label = {"HostSystem": "host", "Datastore": "ds"}.get(
                row.entity_type or "", "entity"
            )
            message.replace(row.entity_name, label, report)
            message.replace(row.entity_moid, label, report)
            messages.append(message)
            if kind in PDL_TYPES:
                devices = {_device_key(device) for device in _device_ids(message.text)}
                occurrences.append(
                    _Occurrence(
                        kind,
                        ensure_aware(row.occurred_at),
                        host
                        or (row.entity_moid if label == "host" else None)
                        or object_host,
                        next(iter(devices)) if len(devices) == 1 else None,
                        len(devices),
                    )
                )
        for (role, entity_type), count in sorted(roles.items()):
            report.add(f"  role={role} entityType={entity_type} 件数={count}")
        _messages(messages, report, set(_WORDS) | catalog_words.get(kind, set()))
    _pdl_pairs(occurrences, report, source="DB")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, exit_on_error=False)
    parser.add_argument("vcenter_name", help="登録済みの vCenter の名前")
    parser.add_argument(
        "--days", type=int, default=30, help="vCenter でさかのぼる日数（既定 30）"
    )
    try:
        args, extra = parser.parse_known_args(argv)
    except argparse.ArgumentError:
        parser.error("引数を確認してください。")
    if extra:
        parser.error("引数を確認してください。")
    if args.days < 1:
        parser.error("--days は 1 以上にしてください。")
    now = utcnow()
    try:
        begin = now - timedelta(days=args.days)
    except OverflowError:
        parser.error("--days が大きすぎます。")
    report = _Report()
    report.remember(args.vcenter_name)
    try:
        settings = get_settings()
        bind_settings(settings)
        center, rows = asyncio.run(_read_database(args.vcenter_name, settings))
    except Exception as exc:
        print(f"DB 読み取り失敗={type(exc).__name__}", file=sys.stderr)
        return 1
    if center is None:
        print("登録済みの vCenter が見つかりません。", file=sys.stderr)
        return 1

    report.remember_host(center.host)
    report.remember(center.username, center.password)
    status = 0
    catalog_words: dict[str, set[str]] = {}
    try:
        si = connect_vcenter(
            host=center.host,
            protocol=center.protocol,
            port=center.port,
            username=center.username,
            password=center.password,
            verify_ssl=center.verify_ssl,
            proxy_url=settings.vcenter_http_proxy,
            ca_bundle_path=settings.vcenter_ca_bundle,
            http_connection_timeout=settings.inventory_sync_timeout_seconds,
        )
        try:
            manager = si.RetrieveContent().eventManager
            catalog_words, sibling_ids = _catalog(manager, report)
            report.add(f"[QueryEvents 直近 {args.days} 日]")
            events = [
                _observe(event, report)
                for kind in EVENT_TYPES
                for event in _query(
                    manager, kind, begin, now + _CLOCK_MARGIN, now, report
                )
            ]
            _query_summary(events, now, report, catalog_words)
            _pdl_pairs(events, report, source="vCenter")
            if sibling_ids:
                report.add("[兄弟イベント（vCenter）]")
                for kind in sibling_ids:
                    siblings = [
                        _observe(event, report)
                        for event in _query(
                            manager, kind, begin, now + _CLOCK_MARGIN, now, report
                        )
                    ]
                    _sibling_summary(kind, siblings, events, report)
        finally:
            disconnect(si)
    except Exception as exc:
        report.add(f"vCenter 読み取り失敗={type(exc).__name__}")
        status = 1

    try:
        _database_summary(rows, now, report, catalog_words)
    except Exception as exc:
        report.add(f"DB 集計失敗={type(exc).__name__}")
        status = 1
    try:
        report.emit()
    except Exception as exc:
        print(f"出力失敗={type(exc).__name__}", file=sys.stderr)
        return 1
    return status


if __name__ == "__main__":
    sys.exit(main())
