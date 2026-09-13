"""Declarative base classes for collectors.

``CollectorPlugin`` Protocol を直接実装しても動くが、その場合は接続の開閉・スレッドへの
退避・``mock_mode`` の分岐・タイムスタンプ・カーソルを毎回自分で組み立てることになる。
どれも間違えると**静かに壊れる**。

ここの基底クラスを使うと、実装するのは**同期のジェネレータ 1 つ**だけになる。

```python
TEMPERATURE = MetricDefinition(
    key="example.host.temperature_c",
    display_name="Host temperature",
    unit="C",
    entity_type="HostSystem",
)


class TemperatureCollector(MetricCollector):
    id = "example.host.temperature"
    display_name = "Example Host Temperature"
    description = "ESXi ホストごとの温度を 1 点ずつ収集する。"  # 管理画面の詳細行に出る
    version = "0.1.0"
    metrics = (TEMPERATURE,)

    def sample(self, si, context):
        for moid, name in _read_hosts(si):
            yield TEMPERATURE.at(entity_moid=moid, entity_name=name, value=_read(moid))


build_collector = TemperatureCollector   # クラス自体が引数なしファクトリになる
```

基底が引き受けること:

============================== =========================================================
基底が持つ                      使わないと踏む罠
============================== =========================================================
クラス属性からの manifest 生成    ``frozenset({...})`` と 1 要素タプルの末尾カンマ
``data_kinds`` の自動導出        書き忘れるとバッチが**丸ごと**拒否される
``mock_mode`` の分岐            ``MOCK_MODE=true`` でプラグインが動かない
接続の open / close             ``async with`` の書き忘れ、接続リーク
``run_blocking`` での実行        素の ``to_thread`` がタイムアウト時にセッションを取り残す
スレッド内での ``tuple()`` 確定   ジェネレータ本体がイベントループ上で回る
カーソルの decode / encode       空バッチで前進せず同じ範囲を読み続ける、境界の取りこぼし
============================== =========================================================

既に ``manifest`` を明示的に書いているクラスはそのまま尊重する。宣言的な書き方へ
一度に移行する必要はない。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, ClassVar

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectionContext,
    CollectorManifest,
    DataKind,
    EventInput,
    MetricDefinition,
    MetricSampleInput,
)
from vcenter_event_assistant_plugin_api.blocking import run_blocking
from vcenter_event_assistant_plugin_api.cursors import TimestampCursor
from vcenter_event_assistant_plugin_api.validation import (
    ManifestValidationError,
    validate_manifest,
)


#: これらのいずれかを自クラスで宣言すると、マニフェストは組み立て直される。
_MANIFEST_ATTRIBUTES = frozenset(
    {
        "id",
        "display_name",
        "description",
        "version",
        "default_interval_seconds",
        "data_kinds",
        "metrics",
    }
)


class CollectorBase:
    """任意の基底クラス。``start`` / ``stop`` は何もしない実装を持つ。

    具象クラスは :attr:`id` / :attr:`display_name` / :attr:`version` を定義する。
    :attr:`description` は任意だが、書いておくと管理画面の詳細行に表示され、運用者が
    「このコレクタを無効にすると何が止まるのか」を判断できる。
    中間の抽象クラスを自分で作る場合は ``abstract = True`` を置くこと。
    """

    #: ``True`` のクラスは manifest を組み立てない（中間の抽象クラス）。
    #: 継承されないよう、判定は必ずそのクラス自身の ``__dict__`` だけを見る。
    abstract: ClassVar[bool] = True

    id: ClassVar[str]
    display_name: ClassVar[str]
    #: 運用者向けの説明。管理画面の詳細行に出る。空なら何も表示されない。
    description: ClassVar[str] = ""
    version: ClassVar[str]
    default_interval_seconds: ClassVar[int] = 300
    #: サブクラスが宣言する。:class:`MetricCollector` などが設定する。
    data_kinds: ClassVar[frozenset[DataKind]] = frozenset()
    #: マニフェスト。``__init_subclass__`` が組み立てる（明示定義があればそちらを使う）。
    manifest: ClassVar[CollectorManifest]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("abstract", False):
            return
        # 明示的に manifest を書いたクラス（従来の書き方）はそのまま使う。
        if "manifest" in cls.__dict__:
            validate_manifest(cls.manifest)
            return
        # 具象クラスを継承して、マニフェストに関わる宣言を一切足さずに振る舞いだけ
        # 差し替えた場合（テストでよく書く形）は、親のマニフェストをそのまま引き継ぐ。
        # 1 つでも宣言を足していれば作り直す。さもないと、`display_name` だけ変えた
        # サブクラスがその変更を黙って失う。
        if not _MANIFEST_ATTRIBUTES & cls.__dict__.keys() and (
            getattr(cls, "manifest", None) is not None
        ):
            return
        cls.manifest = cls._build_manifest()
        # クラス定義の時点で落とす。テストを 1 回走らせれば manifest の誤りに気づく。
        validate_manifest(cls.manifest)

    @classmethod
    def _build_manifest(cls) -> CollectorManifest:
        for attribute in ("id", "display_name", "version"):
            if not getattr(cls, attribute, None):
                raise ManifestValidationError(
                    (
                        _missing_attribute_issue(cls.__name__, attribute),
                    )
                )
        return CollectorManifest(
            id=cls.id,
            display_name=cls.display_name,
            version=cls.version,
            data_kinds=cls.data_kinds,
            default_interval_seconds=cls.default_interval_seconds,
            metric_definitions=cls._metric_definitions(),
            description=cls.description,
        )

    @classmethod
    def _metric_definitions(cls) -> tuple[MetricDefinition, ...]:
        return ()

    async def start(self) -> None:
        """ワーカー起動後、最初の収集の前に 1 度だけ呼ばれる。"""
        return None

    async def stop(self) -> None:
        """無効化・リロード・アンインストール時に呼ばれる。"""
        return None

    async def collect(self, context: CollectionContext) -> CollectionBatch:
        raise NotImplementedError(
            f"{type(self).__name__} must implement collect(); or subclass "
            "MetricCollector / EventCollector and implement sample() / fetch()"
        )


def _missing_attribute_issue(class_name: str, attribute: str) -> Any:
    from vcenter_event_assistant_plugin_api.validation import Issue

    return Issue(
        code="missing_class_attribute",
        message=(
            f"{class_name} must define {attribute!r} "
            "(or set abstract = True if it is an intermediate base class)"
        ),
        kind="manifest",
        field=attribute,
    )


class MetricCollector(CollectorBase):
    """メトリクスを返すコレクタ。実装するのは :meth:`sample` だけ。"""

    abstract = True
    data_kinds = frozenset({"metric"})

    #: このコレクタが出すメトリクスの宣言。manifest に自動で載る。
    metrics: ClassVar[tuple[MetricDefinition, ...]] = ()

    @classmethod
    def _metric_definitions(cls) -> tuple[MetricDefinition, ...]:
        return cls.metrics

    def sample(
        self, si: Any, context: CollectionContext
    ) -> Iterable[MetricSampleInput]:
        """接続済みの vCenter から 1 回分のサンプルを返す。**同期でよい。**

        基底が :func:`run_blocking` でスレッドへ逃がし、戻り値をスレッド内で確定させる。
        ``si`` は pyVmomi の ``ServiceInstance`` で、接続の開閉は基底が行う。

        :class:`MetricDefinition` の ``at()`` を使うと、メトリクスキーと ``entity_type``
        を宣言から補い、timezone-aware なタイムスタンプを入れてくれる。
        """
        raise NotImplementedError(f"{type(self).__name__} must implement sample()")

    def sample_mock(self, context: CollectionContext) -> Iterable[MetricSampleInput]:
        """``MOCK_MODE=true`` のときに返す合成データ。

        既定では、宣言された各メトリクスについて 2 つの仮想エンティティ分の決定的な値を
        返す。vCenter に繋がらない環境でも画面に何か出るので、そのまま使ってよい。
        """
        for definition in self._metric_definitions():
            for index in (1, 2):
                moid = f"mock-{definition.entity_type.lower()}-{index}"
                yield definition.at(
                    entity_moid=moid,
                    entity_name=f"mock-{definition.entity_type}-{index}",
                    value=_mock_value(definition.key, index),
                )

    async def collect(self, context: CollectionContext) -> CollectionBatch:
        if context.mock_mode:
            samples = tuple(self.sample_mock(context))
        else:
            async with context.open_vcenter_connection() as si:
                samples = await run_blocking(self._sample_blocking, si, context)
        return CollectionBatch(metrics=samples)

    def _sample_blocking(
        self, si: Any, context: CollectionContext
    ) -> tuple[MetricSampleInput, ...]:
        # スレッドの中で消費し切る。ここで tuple にしないと、ジェネレータの本体が
        # イベントループ上で回ってしまい、退避した意味がなくなる。
        return tuple(self.sample(si, context))


class EventCollector(CollectorBase):
    """イベントを返すコレクタ。実装するのは :meth:`fetch` だけ。

    カーソルは基底が管理する。空のバッチでも必ず前進し、取得範囲の開始は
    :attr:`cursor` の ``overlap`` だけ戻る。
    """

    abstract = True
    data_kinds = frozenset({"event"})

    #: カーソルの規則。既定は 1 秒のオーバーラップ付き。
    cursor: ClassVar[TimestampCursor] = TimestampCursor()

    def fetch(
        self, si: Any, context: CollectionContext, *, since: datetime | None
    ) -> Iterable[EventInput]:
        """``since`` 以降のイベントを返す。**同期でよい。**

        ``since`` が ``None`` なら、まだカーソルが無い（初回、またはカーソルが読めなかった）
        ことを意味する。取得側の既定の範囲を使うこと。

        ``vmware_key`` は情報源が持つ**自然キー**を使うこと。重複排除は
        ``(vcenter_id, collector_id, vmware_key)`` で行われ、衝突したイベントは
        エラーもログもなく捨てられる。
        """
        raise NotImplementedError(f"{type(self).__name__} must implement fetch()")

    def fetch_mock(
        self, context: CollectionContext, *, since: datetime | None
    ) -> Iterable[EventInput]:
        """``MOCK_MODE=true`` のときに返す合成データ。既定では空。"""
        return ()

    async def collect(self, context: CollectionContext) -> CollectionBatch:
        since = self.cursor.window_start(context.previous_cursor)
        if context.mock_mode:
            events = tuple(self.fetch_mock(context, since=since))
        else:
            async with context.open_vcenter_connection() as si:
                events = await run_blocking(self._fetch_blocking, si, context, since)
        max_seen = max((event.occurred_at for event in events), default=None)
        return CollectionBatch(
            events=events,
            next_cursor=self.cursor.advance(context.previous_cursor, max_seen),
        )

    def _fetch_blocking(
        self, si: Any, context: CollectionContext, since: datetime | None
    ) -> tuple[EventInput, ...]:
        return tuple(self.fetch(si, context, since=since))


def _mock_value(key: str, index: int) -> float:
    """キーから決まる決定的な値。

    単位ごとの現実的な範囲は分からないので、0〜100 に収める。百分率にも温度にも
    それらしく見え、桁違いの値で画面を驚かせない範囲である。あくまで
    ``MOCK_MODE=true`` の埋め草であり、意味のある値ではない。
    """
    seed = sum(ord(character) for character in key) + index * 7
    return round(seed % 100 + (seed % 10) / 10.0, 2)
