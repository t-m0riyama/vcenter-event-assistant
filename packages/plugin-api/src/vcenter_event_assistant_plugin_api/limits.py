"""Field limits imposed by the application's database schema.

これらは ``vcenter_event_assistant.db.models`` の列定義を写したものである。アプリは
長さを検証しないため、超過は収集時に DB エラーとして初めて現れる。あらかじめ知って
おけば避けられるので、作者向けに公開する。

``tests/test_plugin_api_limits_match_models.py`` が models との一致を検証しており、
片方だけ変えるとテストが落ちる。
"""

from __future__ import annotations

import hashlib

#: ``EventRecord.collector_id`` / ``MetricSample.collector_id``（= プラグイン ID）。
MAX_PLUGIN_ID = 64

#: ``MetricSample.metric_key``。
MAX_METRIC_KEY = 256
#: ``MetricSample.entity_type``。**イベント側とは値が違う**。
MAX_METRIC_ENTITY_TYPE = 128
#: ``MetricSample.entity_moid``。
MAX_ENTITY_MOID = 256
#: ``MetricSample.entity_name`` / ``EventRecord.entity_name``。
MAX_ENTITY_NAME = 1024

#: ``EventRecord.event_type``。
MAX_EVENT_TYPE = 512
#: ``EventRecord.severity``。
MAX_SEVERITY = 64
#: ``EventRecord.user_name``。
MAX_USER_NAME = 512
#: ``EventRecord.entity_type``。**メトリクス側とは値が違う**。
MAX_EVENT_ENTITY_TYPE = 256

#: ``EventRecord.vmware_key`` は ``Integer`` である。PostgreSQL では範囲外で失敗する。
VMWARE_KEY_MIN = -(2**31)
VMWARE_KEY_MAX = 2**31 - 1

_ELLIPSIS = "…"


def truncate(value: str, limit: int, *, ellipsis: str = _ELLIPSIS) -> str:
    """``limit`` 文字に収める。切り詰めたことが分かるよう末尾に記号を付ける。

    黙って値を変える操作なので、呼ぶかどうかは作者が決める。``MetricDefinition.at()``
    などのヘルパは自動では切り詰めない（代わりに ``validation.check_batch`` が
    warning として報告する）。
    """
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit <= len(ellipsis):
        return value[:limit]
    return value[: limit - len(ellipsis)] + ellipsis


def stable_int63(*parts: object) -> int:
    """引数から決定的な 63 bit 正整数を作る。

    再実行しても同じ値になるので、情報源に自然な一意キーがない場合の
    ``EventInput.vmware_key`` の材料に使える。

    警告: ``EventRecord.vmware_key`` は現在 ``Integer``（32 bit）なので、この値は
    **そのままでは入らない**。64 bit 化されるまでは、自然キー（vCenter の
    ``Event.key`` など）を使うこと。:func:`stable_int31` も参照。
    """
    digest = hashlib.sha256("\x1f".join(map(repr, parts)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") >> 1


def stable_int31(*parts: object) -> int:
    """引数から決定的な 31 bit 正整数を作る。**推奨しない。**

    ``vmware_key`` の重複排除は ``(vcenter_id, collector_id, vmware_key)`` の
    ``ON CONFLICT DO NOTHING`` である。31 bit しかない空間にハッシュを押し込むと、
    同一 ``(vcenter, collector)`` で **約 4.6 万件で 50% の確率で誕生日衝突**が起き、
    衝突したイベントは**エラーもログもなく捨てられる**。

    使ってよいのは、総件数が数万件未満であると保証できる小規模なコレクタだけである。
    それ以外では自然キーを使うこと。
    """
    return stable_int63(*parts) >> 32
