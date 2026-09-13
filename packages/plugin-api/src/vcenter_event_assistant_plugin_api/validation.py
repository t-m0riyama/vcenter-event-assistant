"""Validation rules shared by the application and plugin authors.

アプリはこれらの規則でバッチと manifest を検査する。違反したバッチは**丸ごと**拒否され、
部分保存もカーソル前進も起こらない。しかし失敗の詳細は既定で外へ出ないため、作者からは
「何かに落ちた」ことしか見えない。

そこで規則そのものをここに置き、アプリと作者が**同じ関数**を呼ぶ形にした。作者は
:func:`check_batch` を自分のテストで呼べば、本番で潰される前に理由を読める。

severity の区別:

- ``"error"`` は**アプリが実際に拒否するもの**。この集合は増やさない。
- ``"warning"`` はアプリが拒否しないが、放置すると**静かにデータが失われる**もの
  （列長超過で DB エラー、``vmware_key`` の範囲外、バッチ内の重複排除キー衝突）。
  作者のテストでは既定で落とし、本番ではログに出すだけにする。

**error のメッセージには vCenter 由来のデータを含めない。** error だけがワーカー越しに
親へ渡りうるためである（warning はワーカーの stderr に留まる）。エンティティ名や
値を出したいものは warning に置くこと。
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from vcenter_event_assistant_plugin_api import (
    PLUGIN_API_VERSION,
    CollectionBatch,
    CollectorManifest,
)
from vcenter_event_assistant_plugin_api import limits as _limits

Severity = Literal["error", "warning"]
IssueKind = Literal["event", "metric", "manifest"]

#: ``registry._validate_plugin`` と同じプラグイン ID の形。
PLUGIN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

_MAX_METRIC_KEY = 256


@dataclass(frozen=True, slots=True)
class Issue:
    """検査で見つかった 1 件の問題。"""

    code: str
    message: str
    severity: Severity = "error"
    kind: IssueKind | None = None
    #: バッチ内の位置（``events`` / ``metrics`` のインデックス）。
    index: int | None = None
    field: str | None = None

    def __str__(self) -> str:
        return self.message


class ManifestValidationError(ValueError):
    """manifest が契約を満たしていない。"""

    def __init__(self, issues: tuple[Issue, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


class BatchValidationError(ValueError):
    """バッチがアプリに受理されない。

    ``ValueError`` の派生なので、アプリ側の既存の扱い（例外を捕まえて failed として
    記録する経路）は変わらない。
    """

    def __init__(self, issues: tuple[Issue, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


def _errors(issues: tuple[Issue, ...]) -> tuple[Issue, ...]:
    return tuple(issue for issue in issues if issue.severity == "error")


# --- manifest ---------------------------------------------------------------


def iter_manifest_issues(manifest: CollectorManifest) -> Iterator[Issue]:
    """manifest の問題を 1 件ずつ返す。

    ``registry._validate_plugin`` の純粋な部分と同じ判定であり、メッセージも一致させて
    いる。``builtin.*`` の予約だけはプラグインの出自に依存するのでアプリ側に残る。
    """
    if not PLUGIN_ID_PATTERN.fullmatch(manifest.id):
        yield Issue("invalid_plugin_id", "invalid plugin id", kind="manifest", field="id")
        return
    if manifest.api_version != PLUGIN_API_VERSION:
        yield Issue(
            "unsupported_api_version",
            f"unsupported plugin API version {manifest.api_version}",
            kind="manifest",
            field="api_version",
        )
        return
    if manifest.default_interval_seconds < 10:
        yield Issue(
            "interval_too_small",
            "default interval must be at least 10 seconds",
            kind="manifest",
            field="default_interval_seconds",
        )
        return
    if not manifest.data_kinds or not manifest.data_kinds <= {"event", "metric"}:
        yield Issue(
            "invalid_data_kinds",
            "data_kinds must contain event and/or metric",
            kind="manifest",
            field="data_kinds",
        )
        return

    keys = [definition.key for definition in manifest.metric_definitions]
    if len(keys) != len(set(keys)):
        yield Issue(
            "duplicate_metric_key",
            "duplicate metric key in manifest",
            kind="manifest",
            field="metric_definitions",
        )
        return
    if "metric" in manifest.data_kinds and not keys:
        yield Issue(
            "missing_metric_definitions",
            "metric collector must declare metric definitions",
            kind="manifest",
            field="metric_definitions",
        )
        return
    if any(not key or len(key) > _MAX_METRIC_KEY for key in keys):
        yield Issue(
            "metric_key_length",
            "metric keys must be 1..256 characters",
            kind="manifest",
            field="metric_definitions",
        )
        return

    # --- ここから warning。アプリは拒否しない。 ---
    if len(manifest.id) > _limits.MAX_PLUGIN_ID:
        yield Issue(
            "plugin_id_too_long",
            f"plugin id exceeds {_limits.MAX_PLUGIN_ID} characters",
            severity="warning",
            kind="manifest",
            field="id",
        )
    if keys and "metric" not in manifest.data_kinds:
        # 宣言はしているが metric を出さない。キーは使われず、
        # 実際にメトリクスを返した瞬間に undeclared_metric_kind で拒否される。
        yield Issue(
            "unused_metric_definitions",
            "metric definitions are declared but metric is not in data_kinds",
            severity="warning",
            kind="manifest",
            field="metric_definitions",
        )
    for definition in manifest.metric_definitions:
        if len(definition.entity_type) > _limits.MAX_METRIC_ENTITY_TYPE:
            yield Issue(
                "field_too_long",
                f"entity_type is {len(definition.entity_type)} characters, "
                f"over the {_limits.MAX_METRIC_ENTITY_TYPE} the database allows",
                severity="warning",
                kind="manifest",
                field="entity_type",
            )


def check_manifest(manifest: CollectorManifest) -> tuple[Issue, ...]:
    """manifest を検査し、見つかった問題を返す（送出しない）。"""
    return tuple(iter_manifest_issues(manifest))


def validate_manifest(manifest: CollectorManifest) -> None:
    """error が 1 件でもあれば :class:`ManifestValidationError` を送出する。"""
    errors = _errors(check_manifest(manifest))
    if errors:
        raise ManifestValidationError(errors)


def manifest_error_message(manifest: CollectorManifest) -> str | None:
    """最初の error のメッセージ。無ければ ``None``。

    ``registry._validate_plugin`` が文字列を返す形のままでいられるようにするための
    互換ヘルパである。
    """
    errors = _errors(check_manifest(manifest))
    return errors[0].message if errors else None


# --- batch ------------------------------------------------------------------


def iter_batch_issues(
    manifest: CollectorManifest, batch: CollectionBatch
) -> Iterator[Issue]:
    """バッチの問題を 1 件ずつ返す。error を先に、warning を後に出す。"""
    yield from _batch_errors(manifest, batch)
    yield from _batch_warnings(batch)


def _batch_errors(
    manifest: CollectorManifest, batch: CollectionBatch
) -> Iterator[Issue]:
    if batch.events and "event" not in manifest.data_kinds:
        yield Issue(
            "undeclared_event_kind",
            "collector emitted undeclared event data",
            kind="event",
        )
    if batch.metrics and "metric" not in manifest.data_kinds:
        yield Issue(
            "undeclared_metric_kind",
            "collector emitted undeclared metric data",
            kind="metric",
        )
    declared = {definition.key for definition in manifest.metric_definitions}
    for index, sample in enumerate(batch.metrics):
        if sample.metric_key not in declared:
            yield Issue(
                "undeclared_metric_key",
                f"undeclared metric key: {sample.metric_key}",
                kind="metric",
                index=index,
                field="metric_key",
            )
        if not math.isfinite(sample.value):
            yield Issue(
                "non_finite_value",
                f"non-finite metric value: {sample.metric_key}",
                kind="metric",
                index=index,
                field="value",
            )
        if sample.sampled_at.tzinfo is None:
            yield Issue(
                "naive_sampled_at",
                "metric sampled_at must be timezone-aware",
                kind="metric",
                index=index,
                field="sampled_at",
            )
    for index, event in enumerate(batch.events):
        if event.occurred_at.tzinfo is None:
            yield Issue(
                "naive_occurred_at",
                "event occurred_at must be timezone-aware",
                kind="event",
                index=index,
                field="occurred_at",
            )


def _too_long(
    kind: IssueKind, index: int, name: str, value: str | None, limit: int
) -> Issue | None:
    if value is not None and len(value) > limit:
        return Issue(
            "field_too_long",
            f"{name} is {len(value)} characters, over the {limit} the database allows",
            severity="warning",
            kind=kind,
            index=index,
            field=name,
        )
    return None


def _batch_warnings(batch: CollectionBatch) -> Iterator[Issue]:
    """アプリは拒否しないが、放置すると静かにデータが失われるもの。"""
    metric_seen: set[tuple[object, str, str]] = set()
    for index, sample in enumerate(batch.metrics):
        for issue in (
            _too_long("metric", index, "metric_key", sample.metric_key, _limits.MAX_METRIC_KEY),
            _too_long("metric", index, "entity_type", sample.entity_type, _limits.MAX_METRIC_ENTITY_TYPE),
            _too_long("metric", index, "entity_moid", sample.entity_moid, _limits.MAX_ENTITY_MOID),
            _too_long("metric", index, "entity_name", sample.entity_name, _limits.MAX_ENTITY_NAME),
        ):
            if issue is not None:
                yield issue
        if not sample.entity_moid:
            yield Issue(
                "empty_entity_moid",
                "entity_moid is empty; it is part of the metric deduplication key",
                severity="warning",
                kind="metric",
                index=index,
                field="entity_moid",
            )
        # DB は (vcenter_id, sampled_at, entity_moid, metric_key) で一意。
        # バッチ内で衝突すると 1 件だけ残り、残りは黙って捨てられる。
        point = (sample.sampled_at, sample.entity_moid, sample.metric_key)
        if point in metric_seen:
            yield Issue(
                "duplicate_dedup_key",
                "two samples share (sampled_at, entity_moid, metric_key); "
                "only one will be stored",
                severity="warning",
                kind="metric",
                index=index,
            )
        metric_seen.add(point)

    event_seen: set[int] = set()
    for index, event in enumerate(batch.events):
        for issue in (
            _too_long("event", index, "event_type", event.event_type, _limits.MAX_EVENT_TYPE),
            _too_long("event", index, "severity", event.severity, _limits.MAX_SEVERITY),
            _too_long("event", index, "user_name", event.user_name, _limits.MAX_USER_NAME),
            _too_long("event", index, "entity_name", event.entity_name, _limits.MAX_ENTITY_NAME),
            _too_long("event", index, "entity_type", event.entity_type, _limits.MAX_EVENT_ENTITY_TYPE),
        ):
            if issue is not None:
                yield issue
        if not _limits.VMWARE_KEY_MIN <= event.vmware_key <= _limits.VMWARE_KEY_MAX:
            yield Issue(
                "vmware_key_out_of_int32_range",
                f"vmware_key {event.vmware_key} does not fit the Integer column; "
                "PostgreSQL will reject it",
                severity="warning",
                kind="event",
                index=index,
                field="vmware_key",
            )
        # DB は (vcenter_id, collector_id, vmware_key) で一意。
        if event.vmware_key in event_seen:
            yield Issue(
                "duplicate_dedup_key",
                f"vmware_key {event.vmware_key} appears more than once; "
                "only one event will be stored",
                severity="warning",
                kind="event",
                index=index,
                field="vmware_key",
            )
        event_seen.add(event.vmware_key)


def check_batch(
    manifest: CollectorManifest, batch: CollectionBatch
) -> tuple[Issue, ...]:
    """バッチを検査し、見つかった問題を返す（送出しない）。"""
    return tuple(iter_batch_issues(manifest, batch))


def validate_batch(manifest: CollectorManifest, batch: CollectionBatch) -> None:
    """アプリが拒否する条件に当たれば :class:`BatchValidationError` を送出する。

    warning では送出しない。アプリの受理・拒否の境界をここで変えないためである。
    """
    errors = _errors(tuple(_batch_errors(manifest, batch)))
    if errors:
        raise BatchValidationError(errors)


def raise_for_issues(issues: tuple[Issue, ...]) -> None:
    """すでに :func:`check_batch` した結果から送出する。

    error と warning の両方を使う呼び出し側（アプリは warning をログに出す）が、
    バッチを二度走査しなくて済むようにするための入口である。イベントは 1 回の収集で
    数万件になりうるため、走査の回数は数えるに値する。
    """
    errors = _errors(issues)
    if errors:
        raise BatchValidationError(errors)
