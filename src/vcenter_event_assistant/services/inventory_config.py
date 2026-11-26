"""構成の今の値と差分を同じトランザクションで更新する。"""

from collections import Counter
from dataclasses import asdict
from itertools import batched
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.auth.timeutil import as_utc
from vcenter_event_assistant.collectors.config_values import (
    FORMATS,
    ConfigValue,
    diff_config,
    value_hash,
)
from vcenter_event_assistant.collectors.inventory_config import (
    ConfigBaseline,
    ConfigObservation,
)
from vcenter_event_assistant.db.models import (
    InventoryConfigDiff,
    InventoryConfigState,
    InventorySyncState,
)


async def config_baselines(
    session: AsyncSession, vcenter_id: UUID
) -> tuple[str | None, dict[str, ConfigBaseline]]:
    state = await session.get(InventorySyncState, vcenter_id)
    if state is None or state.config_instance_uuid is None:
        return None, {}
    rows = await session.execute(
        select(
            InventoryConfigState.moid,
            InventoryConfigState.change_version,
            InventoryConfigState.format,
            InventoryConfigState.verified_at,
        ).where(
            InventoryConfigState.vcenter_id == vcenter_id,
            InventoryConfigState.category == "vm_config",
        )
    )
    return state.config_instance_uuid, {
        moid: ConfigBaseline(change_version, format_, as_utc(verified_at))
        for moid, change_version, format_, verified_at in rows
    }


async def persist_inventory_config(
    session: AsyncSession,
    vcenter_id: UUID,
    observation: ConfigObservation,
) -> None:
    state = await session.get(InventorySyncState, vcenter_id)
    if state is None:
        state = InventorySyncState(vcenter_id=vcenter_id)
        session.add(state)

    table = InventoryConfigState.__table__
    target = table.c.vcenter_id == vcenter_id
    reset = (
        state.config_instance_uuid is not None
        and state.config_instance_uuid != observation.instance_uuid
    )
    if reset:
        await session.execute(delete(table).where(target))

    existing = {
        (row.moid, row.category): row
        for row in await session.execute(
            select(
                table.c.id,
                table.c.moid,
                table.c.category,
                table.c.value_hash,
                table.c.format,
                table.c.change_version,
                table.c.verified_at,
                table.c.entity_name,
                table.c.entity_type,
            ).where(target)
        )
    }
    started_at = as_utc(observation.started_at)
    observed_at = as_utc(observation.observed_at)
    compared: Counter[str] = Counter()
    changed: Counter[str] = Counter()
    new_rows = []
    value_updates = []
    verified = []
    changed_values: dict[int, tuple[ConfigValue, dict[str, Any]]] = {}

    readable = observation.values.keys() | {
        (moid, "vm_config") for moid in observation.unchanged_vms
    }
    for moid, category in sorted(readable):
        key = moid, category
        if key in observation.carry_over or (
            category == "vm_config"
            and (moid in observation.deferred_vms or moid in observation.unread_vms)
        ):
            continue
        old = existing.get(key)
        obj = observation.objects[moid]
        name = obj.name if obj.name is not None else (old.entity_name if old else moid)
        format_ = FORMATS[category]
        value = observation.values.get(key)
        version = (
            observation.change_versions.get(moid) if category == "vm_config" else None
        )

        if value is None:
            # 近道は、同じ vCenter の同じ版・世代の行にだけ使える。
            if old is None or old.format != format_ or old.change_version != version:
                continue
            compared[category] += 1
        else:
            digest = value_hash(value)
            if old is None:
                new_rows.append(
                    dict(
                        vcenter_id=vcenter_id,
                        moid=moid,
                        category=category,
                        entity_type=obj.entity_type,
                        entity_name=name,
                        format=format_,
                        value=value,
                        value_hash=digest,
                        change_version=version,
                        verified_at=started_at,
                    )
                )
                continue
            if old.format == format_:
                compared[category] += 1
                if old.value_hash != digest:
                    changed[category] += 1
                    changed_after = as_utc(old.verified_at)
                    changed_values[old.id] = (
                        value,
                        dict(
                            vcenter_id=vcenter_id,
                            moid=moid,
                            category=category,
                            entity_type=obj.entity_type,
                            entity_name=name,
                            changed_after=changed_after,
                            observed_at=max(observed_at, changed_after),
                        ),
                    )
            if (
                old.format != format_
                or old.value_hash != digest
                or old.change_version != version
            ):
                value_updates.append(
                    dict(
                        row_id=old.id,
                        format=format_,
                        value_hash=digest,
                        value=value,
                        change_version=version,
                    )
                )

        verified.append(
            dict(
                row_id=old.id,
                verified_at=max(started_at, as_utc(old.verified_at)),
                entity_type=obj.entity_type,
                entity_name=name,
            )
        )

    diffs: list[dict[str, Any]] = []
    for ids in batched(changed_values, 500):
        old_values = await session.execute(
            select(table.c.id, table.c.value).where(table.c.id.in_(ids))
        )
        for row_id, old_value in old_values:
            value, details = changed_values[row_id]
            diffs.extend(
                {**details, **asdict(diff)}
                for diff in diff_config(details["category"], old_value, value)
            )

    removed = [
        {"row_id": row.id}
        for row in existing.values()
        if row.moid not in observation.objects
    ]
    by_id = table.c.id == bindparam("row_id")
    if removed:
        await session.execute(delete(table).where(by_id), removed)
    if new_rows:
        await session.execute(insert(table), new_rows)
    if value_updates:
        await session.execute(
            update(table)
            .where(by_id)
            .values(
                {
                    key: bindparam(key)
                    for key in ("format", "value_hash", "value", "change_version")
                }
            ),
            value_updates,
        )
    if verified:
        await session.execute(
            update(table)
            .where(by_id)
            .values(
                {
                    key: bindparam(key)
                    for key in ("verified_at", "entity_type", "entity_name")
                }
            ),
            verified,
        )
    if diffs:
        await session.execute(insert(InventoryConfigDiff.__table__), diffs)

    success_at = observed_at
    if state.config_last_success_at is not None:
        success_at = max(success_at, as_utc(state.config_last_success_at))
    if reset or state.config_first_success_at is None:
        state.config_first_success_at = success_at
    state.config_instance_uuid = observation.instance_uuid
    state.config_last_started_at = started_at
    state.config_last_success_at = success_at
    state.config_object_count = len(observation.objects)
    state.config_deferred_count = len(observation.deferred_vms)

    warnings = [
        f"{category} の構成が比較した {count} 件のうち {changed[category]} 件で変わりました。"
        for category, count in sorted(compared.items())
        if count >= 20 and changed[category] * 2 >= count
    ]
    warnings.extend(
        f"{category} の構成に同じ名前の要素がありました。"
        for category in sorted(observation.duplicate_categories)
    )
    unread = observation.unread_vms - observation.removed_vms
    if unread:
        warnings.append(f"段 2 で構成を読めなかった VM が {len(unread)} 台ありました。")
    if warnings:
        state.config_last_warning = " ".join(warnings)
        state.config_last_warning_at = success_at
