"""chat_event_time_buckets.build_chat_event_time_buckets の集計テスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from vcenter_event_assistant.db.models import EventRecord, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.chat_event_time_buckets import (
    build_chat_event_time_buckets,
)


@pytest.mark.asyncio
async def test_build_chat_event_time_buckets_sparse_buckets_and_by_type() -> None:
    """同一バケットに複数種別があるとき件数と by_type を返す。空バケットは含めない。"""
    vid = uuid.uuid4()
    from_utc = datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc)
    to_utc = from_utc + timedelta(hours=2)
    bucket_sec = 15 * 60
    # 15 分バケット: [10:00,10:15), [10:15,10:30), … — 2 バケットにだけイベントを置く
    t1 = from_utc + timedelta(minutes=5)
    t2 = from_utc + timedelta(minutes=6)
    t3 = from_utc + timedelta(minutes=20)
    t4 = from_utc + timedelta(minutes=22)

    async with session_scope() as session:
        session.add(
            VCenter(
                id=vid,
                name="vc",
                host="h",
                port=443,
                username="u",
                password="p",
                is_enabled=True,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=t1,
                event_type="VmPoweredOnEvent",
                message="",
                vmware_key=1,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=t2,
                event_type="VmPoweredOffEvent",
                message="",
                vmware_key=2,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=t3,
                event_type="VmPoweredOnEvent",
                message="",
                vmware_key=3,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=t4,
                event_type="OtherEvent",
                message="",
                vmware_key=4,
            )
        )

    async with session_scope() as session:
        out = await build_chat_event_time_buckets(
            session,
            from_utc,
            to_utc,
            vcenter_id=None,
            bucket_sec=bucket_sec,
        )

    assert out.bucket_minutes == 15
    assert len(out.buckets) == 2
    b0 = out.buckets[0]
    assert b0.total == 2
    assert b0.by_type["VmPoweredOnEvent"] == 1
    assert b0.by_type["VmPoweredOffEvent"] == 1
    b1 = out.buckets[1]
    assert b1.total == 2
    assert b1.by_type["VmPoweredOnEvent"] == 1
    assert b1.by_type["OtherEvent"] == 1
    assert b1.bucket_start_utc == from_utc + timedelta(minutes=15)


@pytest.mark.asyncio
async def test_build_chat_event_time_buckets_other_when_many_types() -> None:
    """種別が max_types_per_bucket を超えるとき残りを _other にまとめる。"""
    vid = uuid.uuid4()
    from_utc = datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc)
    to_utc = from_utc + timedelta(hours=1)
    bucket_sec = 3600

    async with session_scope() as session:
        session.add(
            VCenter(
                id=vid,
                name="vc",
                host="h",
                port=443,
                username="u",
                password="p",
                is_enabled=True,
            )
        )
        for i, et in enumerate(["A", "B", "C", "D"]):
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=from_utc + timedelta(minutes=i),
                    event_type=et,
                    message="",
                    vmware_key=100 + i,
                )
            )

    async with session_scope() as session:
        out = await build_chat_event_time_buckets(
            session,
            from_utc,
            to_utc,
            vcenter_id=None,
            bucket_sec=bucket_sec,
            max_types_per_bucket=2,
        )

    assert len(out.buckets) == 1
    row = out.buckets[0]
    assert row.total == 4
    # 件数降順: D=1, C=1, B=1, A=1 → タイブレークは種別名で A,B が先頭2つ
    assert "_other" in row.by_type
    assert row.by_type["_other"] == 2


@pytest.mark.asyncio
async def test_build_chat_event_time_buckets_filters_by_vcenter_id() -> None:
    """vcenter_id 指定時はその vCenter の行のみ。"""
    v1 = uuid.uuid4()
    v2 = uuid.uuid4()
    from_utc = datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc)
    to_utc = from_utc + timedelta(hours=1)

    async with session_scope() as session:
        for vid in (v1, v2):
            session.add(
                VCenter(
                    id=vid,
                    name=f"vc-{vid.hex[:8]}",
                    host="h",
                    port=443,
                    username="u",
                    password="p",
                    is_enabled=True,
                )
            )
        session.add(
            EventRecord(
                vcenter_id=v1,
                occurred_at=from_utc + timedelta(minutes=1),
                event_type="E1",
                message="",
                vmware_key=1,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=v2,
                occurred_at=from_utc + timedelta(minutes=2),
                event_type="E2",
                message="",
                vmware_key=2,
            )
        )

    async with session_scope() as session:
        out = await build_chat_event_time_buckets(
            session,
            from_utc,
            to_utc,
            vcenter_id=v1,
            bucket_sec=3600,
        )

    assert len(out.buckets) == 1
    assert out.buckets[0].total == 1
    assert out.buckets[0].by_type == {"E1": 1}
