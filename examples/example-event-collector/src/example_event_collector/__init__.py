"""Sample event collector plugin for vCenter Event Assistant.

vCenter のイベントのうち、仮想マシンの電源操作だけを取り込む最小のコレクタである。

**イベント側はメトリクス側より罠が多い。** カーソルの前進、``vmware_key`` の一意性と
2^31 の上限、列長、``data_kinds`` のいずれもここで効く。正解の形を 1 つ置いておく。

``EventCollector`` を継承すると、実装するのは :meth:`PowerEventCollector.fetch` だけに
なる。以下はすべて基底が引き受ける。

- クラス属性からの ``CollectorManifest`` の生成（``data_kinds`` の導出を含む）
- vCenter 接続の open / close
- ブロッキング処理のスレッド退避（キャンセルされてもセッションを取り残さない）
- カーソルの decode と前進（**空のバッチでも前進する**）と、取得範囲の 1 秒オーバーラップ
- ``CollectionBatch`` の組み立て

依存は ``vcenter-event-assistant-plugin-api`` だけであり、アプリ本体は import しない。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from vcenter_event_assistant_plugin_api import (
    CollectionContext,
    EventCollector,
    EventInput,
    TimestampCursor,
    config,
    get_plugin_logger,
    limits,
    timeutils,
)

PLUGIN_ID = "example.vcenter.power_events"

#: 既定で拾うイベント種別。``event_types`` 設定で上書きできる。
DEFAULT_EVENT_TYPES = (
    "VmPoweredOnEvent",
    "VmPoweredOffEvent",
    "VmSuspendedEvent",
)

#: 1 回の収集で読むページ数の上限。無制限にすると、長期停止からの復帰で
#: 1 回の収集が終わらなくなる。
MAX_PAGES = 20
#: 1 ページあたりの件数。
PAGE_SIZE = 500

logger = get_plugin_logger(PLUGIN_ID)


class PowerEventCollector(EventCollector):
    """仮想マシンの電源イベントを取り込むコレクタ。"""

    id = PLUGIN_ID
    display_name = "Example VM Power Events"
    version = "0.1.0"
    default_interval_seconds = 120

    #: 取得範囲の開始を 1 秒だけ戻す。収集の実行時刻とイベントの発生時刻には差が
    #: あり、前回の最大時刻と同一秒のイベントが後から現れうるためである。再読した分は
    #: ``vmware_key`` による重複排除で落ちる。
    cursor = TimestampCursor()

    def fetch(
        self, si: Any, context: CollectionContext, *, since: datetime | None
    ) -> Iterator[EventInput]:
        """``since`` 以降のイベントを返す。**同期でよい。**

        ``since`` が ``None`` なら、まだカーソルが無い（初回、またはカーソルが
        読めなかった）ことを意味する。ここでは vCenter 側の既定の範囲に任せる。
        """
        # pyVmomi はアプリのワーカーの sys.path に見えているので、プラグイン側で
        # インストールする必要はない。import は関数の中に置く。
        from pyVmomi import vim

        event_types = config.get_str_list(
            context.config, "event_types", DEFAULT_EVENT_TYPES
        )

        spec = vim.event.EventFilterSpec()
        spec.time = vim.event.EventFilterSpec.ByTime()
        spec.time.endTime = timeutils.now_utc()
        if since is not None:
            # naive な datetime を渡すと、pyVmomi 側の解釈がずれる。
            spec.time.beginTime = timeutils.ensure_aware(since)
        spec.eventTypeId = list(event_types)

        collector = si.RetrieveContent().eventManager.CreateCollectorForEvents(spec)
        try:
            yielded = 0
            for _ in range(MAX_PAGES):
                page = collector.ReadNextEvents(PAGE_SIZE)
                if not page:
                    break
                for raw in page:
                    event = _to_event_input(raw)
                    if event is not None:
                        yielded += 1
                        yield event
            else:
                logger.warning(
                    "hit MAX_PAGES=%s; more events may remain in vCenter", MAX_PAGES
                )
            logger.info("fetched %d power event(s) since=%s", yielded, since)
        finally:
            # 呼ばないとコレクタが vCenter 側に残り続ける。
            collector.DestroyCollector()


def _to_event_input(raw: Any) -> EventInput | None:
    """pyVmomi のイベントを :class:`EventInput` にする。

    ``vmware_key`` には vCenter が振る**自然キー** ``Event.key`` をそのまま使う。
    重複排除は ``(vcenter_id, collector_id, vmware_key)`` の
    ``ON CONFLICT DO NOTHING`` なので、ハッシュで作ると衝突したイベントが
    **エラーもログもなく捨てられる**。
    """
    key = getattr(raw, "key", None)
    if key is None:
        # key の無いイベントを 0 に潰すと、重複排除で 1 件しか残らない。捨てる方が安全。
        logger.warning("event without a key, skipping: %s", type(raw).__name__)
        return None

    key = int(key)
    if not limits.VMWARE_KEY_MIN <= key <= limits.VMWARE_KEY_MAX:
        # `EventRecord.vmware_key` は 32 bit である。範囲外は DB で失敗する。
        logger.warning("event key out of range, skipping: %s", key)
        return None

    entity = getattr(raw, "entity", None)
    severity = getattr(raw, "severity", None)
    message = getattr(raw, "fullFormattedMessage", None) or str(raw)
    return EventInput(
        # naive な datetime はバッチ全体の拒否になる。
        occurred_at=timeutils.ensure_aware(raw.createdTime),
        # アプリはイベント種別をクラス名から取る。
        event_type=type(raw).__name__,
        message=message,
        vmware_key=key,
        severity=str(severity).lower() if severity is not None else None,
        user_name=getattr(raw, "userName", None),
        # 列長を超えると DB で落ちる。表示名なので切り詰めてよい。
        entity_name=limits.truncate(
            getattr(entity, "name", "") or "", limits.MAX_ENTITY_NAME
        )
        or None,
        entity_type=type(entity).__name__ if entity is not None else None,
        chain_id=int(raw.chainId) if getattr(raw, "chainId", None) else None,
    )


#: entry point から呼ばれる引数なしファクトリ。クラス自体がそのまま使える。
build_collector = PowerEventCollector
