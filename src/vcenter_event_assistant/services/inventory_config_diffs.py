"""記録した構成の差分を一覧とタイムラインのカードに返す。"""

import json
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.api.schemas.inventory import (
    IncidentTimelineConfigDiff,
    InventoryConfigDiffResponse,
    InventoryTarget,
)
from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.db.models import (
    InventoryConfigDiff,
    InventoryObject,
    InventorySyncState,
    VCenter,
)
from vcenter_event_assistant.settings import Settings

_CATEGORY_LABELS = {
    "host_build": "ESXi のバージョンとビルド",
    "host_vswitch": "標準 vSwitch",
    "host_portgroup": "標準ポートグループ",
    "cluster_ha": "クラスタの HA",
    "cluster_drs": "クラスタの DRS",
    "vm_config": "VM の構成",
}
_ATTRIBUTE_LABELS = {
    "version": "バージョン",
    "build": "ビルド",
    "mtu": "MTU",
    "uplinks": "アップリンク",
    "teaming_policy": "NIC チーミングポリシー",
    "active_nics": "アクティブ NIC",
    "standby_nics": "スタンバイ NIC",
    "allow_promiscuous": "無差別モード",
    "mac_changes": "MAC アドレス変更",
    "forged_transmits": "偽装転送",
    "vlan_id": "VLAN ID",
    "vswitch": "標準 vSwitch",
    "enabled": "有効",
    "host_monitoring": "ホスト監視",
    "vm_monitoring": "VM 監視",
    "admission_control_enabled": "アドミッションコントロールの有効化",
    "admission_control_policy": "アドミッションコントロールポリシー",
    "failover_level": "許容するホスト障害数",
    "auto_compute": "フェイルオーバー容量の自動計算",
    "cpu_failover_percent": "CPU フェイルオーバー容量（%）",
    "memory_failover_percent": "メモリフェイルオーバー容量（%）",
    "failover_hosts": "フェイルオーバーホスト",
    "restart_priority": "再起動の優先順位",
    "isolation_response": "ホスト隔離時の対応",
    "default_vm_behavior": "既定の VM 自動化レベル",
    "vmotion_rate": "移行しきい値",
    "num_cpu": "CPU の数",
    "cores_per_socket": "ソケットあたりのコア数",
    "memory_mb": "メモリ（MB）",
    "hardware_version": "仮想ハードウェアのバージョン",
    "guest_id": "ゲスト OS ID",
    "cpu_reservation_mhz": "CPU 予約（MHz）",
    "cpu_limit_mhz": "CPU 制限（MHz）",
    "cpu_shares": "CPU シェア",
    "memory_reservation_mb": "メモリ予約（MB）",
    "memory_limit_mb": "メモリ制限（MB）",
    "memory_shares": "メモリシェア",
    "label": "装置のラベル",
    "uuid": "ディスクの UUID",
    "capacity_kb": "ディスク容量（KB）",
    "thin": "シンプロビジョニング",
    "disk_mode": "ディスクモード",
    "adapter": "NIC の種類",
    "network": "ネットワーク",
    "start_connected": "起動時に接続",
    "mac_address": "MAC アドレス",
}
_LIST_LIMIT = 200
CARD_DIFF_LIMIT = 10


def inventory_config_enabled(settings: Settings) -> bool:
    return (
        settings.scheduler_enabled
        and settings.inventory_sync_enabled
        and settings.inventory_config_enabled
    )


def config_recorded_since(
    first_success: datetime | None, retention_start: datetime
) -> datetime | None:
    return max(as_utc(first_success), retention_start) if first_success is not None else None


def _value(text: str | None, truncated: bool) -> JsonValue:
    if text is None or truncated:
        return text
    return json.loads(text)


def _to_item(row: InventoryConfigDiff) -> IncidentTimelineConfigDiff:
    return IncidentTimelineConfigDiff(
        id=row.id,
        category=row.category,
        category_label=_CATEGORY_LABELS.get(row.category, row.category),
        element=row.element,
        element_label=row.element_label if row.element_label is not None else row.element,
        attribute=row.attribute,
        attribute_label=(
            _ATTRIBUTE_LABELS.get(row.attribute, row.attribute) if row.attribute is not None else None
        ),
        old_value=_value(row.old_value, row.truncated),
        new_value=_value(row.new_value, row.truncated),
        truncated=row.truncated,
        changed_after=as_utc(row.changed_after),
        observed_at=as_utc(row.observed_at),
    )


async def read_config_diffs(
    session: AsyncSession,
    target: ColumnElement[bool],
    *,
    from_time: datetime,
    to_time: datetime,
    newest_first: bool,
) -> tuple[list[IncidentTimelineConfigDiff], int]:
    diff = InventoryConfigDiff
    matching = (
        target,
        diff.changed_after < to_time,
        diff.observed_at > from_time,
    )
    boundary = aliased(diff)
    if newest_first:
        order = (diff.observed_at.desc(), diff.id.desc())
        limit = _LIST_LIMIT
        boundary_side, partner_side = boundary.old_value, diff.new_value
    else:
        # DB の既定の照合順序によらず、バイト順で上限を適用する。
        collation = "C" if session.get_bind().dialect.name == "postgresql" else "BINARY"
        order = (
            diff.observed_at.asc(),
            diff.category.collate(collation).asc(),
            diff.element.collate(collation).asc().nulls_first(),
            diff.attribute.collate(collation).asc().nulls_last(),
            diff.new_value.is_(None).desc(),
            diff.id.asc(),
        )
        limit = CARD_DIFF_LIMIT
        boundary_side, partner_side = boundary.new_value, diff.old_value

    # 一覧では ID 降順なので「増えた」行が先に来る。切れ目の相手は同じ観測に
    # 別の差分が挟まっても見つかるようにし、上限の外から最大 1 件を足す。
    page = select(diff.id).where(*matching).order_by(*order).limit(limit).cte()
    boundary_id = select(diff.id).where(*matching).order_by(*order).offset(limit - 1).limit(1)
    partner_id = (
        select(diff.id)
        .join(
            boundary,
            and_(
                boundary.id == boundary_id.correlate(None).scalar_subquery(),
                diff.vcenter_id == boundary.vcenter_id,
                diff.moid == boundary.moid,
                diff.category == boundary.category,
                diff.element == boundary.element,
                diff.observed_at == boundary.observed_at,
            ),
        )
        .where(
            *matching,
            boundary_side.is_(None),
            boundary.attribute.is_(None),
            diff.attribute.is_(None),
            partner_side.is_(None),
            diff.id.not_in(select(page.c.id)),
        )
        .order_by(*order)
        .limit(1)
        .correlate(None)
    )
    count = select(func.count()).select_from(diff).where(*matching).correlate(None).scalar_subquery()
    ids = select(page.c.id).union_all(select(partner_id.scalar_subquery()))
    rows = (await session.execute(select(diff, count).where(diff.id.in_(ids)).order_by(*order))).all()
    return [_to_item(row) for row, _ in rows], rows[0][1] if rows else 0


async def get_inventory_config_diffs(
    session: AsyncSession,
    settings: Settings,
    *,
    vcenter_id: UUID,
    moid: str,
    from_time: datetime | None,
    to_time: datetime | None,
) -> InventoryConfigDiffResponse | None:
    center = (
        await session.execute(
            select(InventorySyncState.config_first_success_at, InventorySyncState.config_last_success_at)
            .select_from(VCenter)
            .outerjoin(InventorySyncState, InventorySyncState.vcenter_id == VCenter.id)
            .where(VCenter.id == vcenter_id)
        )
    ).one_or_none()
    if center is None:
        return None

    first_success, last_success = center
    now = utcnow()
    last_success_at = as_utc(last_success) if last_success is not None else None
    ceiling = max(now, last_success_at or now)
    retention_start = now - timedelta(days=settings.inventory_config_retention_days)
    recorded_since = config_recorded_since(first_success, retention_start)
    status = "ok" if recorded_since is not None else "not_recorded"
    if not inventory_config_enabled(settings):
        status = "disabled"

    obj = await session.scalar(
        select(InventoryObject).where(
            InventoryObject.vcenter_id == vcenter_id, InventoryObject.moid == moid
        )
    )
    diff = InventoryConfigDiff
    target_filter = (diff.vcenter_id == vcenter_id) & (diff.moid == moid)
    if obj is not None:
        target = InventoryTarget(moid=moid, entity_type=obj.entity_type, name=obj.name or moid)
    else:
        latest = await session.scalar(
            select(diff).where(target_filter).order_by(diff.observed_at.desc(), diff.id.desc()).limit(1)
        )
        target = InventoryTarget(
            moid=moid, entity_type=latest.entity_type if latest else None,
            name=(latest.entity_name or moid) if latest else moid,
        )
    items, total = await read_config_diffs(
        session, target_filter, from_time=from_time or retention_start, to_time=to_time or ceiling,
        newest_first=True,
    )
    return InventoryConfigDiffResponse(
        target=target,
        status=status,
        recorded_since=recorded_since,
        last_success_at=last_success_at,
        items=items,
        total=total,
    )
