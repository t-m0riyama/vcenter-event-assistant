"""DB 由来の設定・ジョブ追従・ホットリロード API（プラグイン管理フェーズ 1）。"""

from __future__ import annotations

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from httpx import AsyncClient

from vcenter_event_assistant.db.models import CollectorPluginSetting
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.jobs.scheduler import (
    _collector_job_id,
    reconcile_collector_jobs,
)
from vcenter_event_assistant.plugins.config import collector_env_locked_fields
from vcenter_event_assistant.plugins.registry import (
    build_collector_registry,
    set_collector_registry,
)
from vcenter_event_assistant.services.plugin_settings import (
    load_collector_db_overrides,
    update_collector_setting,
)
from vcenter_event_assistant.settings import Settings, get_settings

EVENTS_ID = "builtin.vcenter.events"


@pytest.fixture(autouse=True)
def _no_entry_point_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    """開発環境に入っている外部プラグインの影響を受けないようにする。"""
    monkeypatch.setattr(
        "vcenter_event_assistant.plugins.registry.entry_points", lambda **_: []
    )


def _write_toml(tmp_path, body: str) -> str:
    path = tmp_path / "collectors.toml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_database_override_beats_toml(tmp_path) -> None:
    config = _write_toml(
        tmp_path,
        f'[collectors."{EVENTS_ID}"]\nenabled = true\ninterval_seconds = 120\n',
    )
    settings = Settings(collector_config_file=config)

    from_toml = build_collector_registry(settings).get(EVENTS_ID)
    assert from_toml.config.interval_seconds == 120

    from_db = build_collector_registry(
        settings, db_overrides={EVENTS_ID: {"interval_seconds": 999}}
    ).get(EVENTS_ID)
    assert from_db.config.interval_seconds == 999
    assert from_db.status == "enabled"


def test_database_override_can_disable_a_builtin_collector() -> None:
    registry = build_collector_registry(
        Settings(), db_overrides={EVENTS_ID: {"enabled": False}}
    )
    assert registry.get(EVENTS_ID).status == "disabled"
    assert EVENTS_ID not in {item.plugin_id for item in registry.enabled()}


def test_environment_beats_database_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEA_COLLECTOR__BUILTIN_VCENTER_EVENTS__INTERVAL_SECONDS", "77")
    registry = build_collector_registry(
        Settings(), db_overrides={EVENTS_ID: {"interval_seconds": 999}}
    )
    assert registry.get(EVENTS_ID).config.interval_seconds == 77
    assert collector_env_locked_fields(EVENTS_ID) == ["interval_seconds"]


def test_env_locked_fields_ignores_plugin_specific_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VEA_COLLECTOR__BUILTIN_VCENTER_EVENTS__SENSOR", "cpu")
    assert collector_env_locked_fields(EVENTS_ID) == []


def test_none_columns_delegate_to_lower_sources(tmp_path) -> None:
    """NULL 列は「未設定」であり、TOML の値を潰さない。"""
    config = _write_toml(
        tmp_path,
        f'[collectors."{EVENTS_ID}"]\ninterval_seconds = 120\n',
    )
    settings = Settings(collector_config_file=config)
    registry = build_collector_registry(
        settings, db_overrides={EVENTS_ID: {"enabled": True}}
    )
    assert registry.get(EVENTS_ID).config.interval_seconds == 120


async def test_load_and_update_collector_settings_round_trip() -> None:
    async with session_scope(settings=get_settings()) as session:
        await update_collector_setting(session, EVENTS_ID, enabled=False)
        await update_collector_setting(session, EVENTS_ID, interval_seconds=300)

    async with session_scope(settings=get_settings()) as session:
        overrides = await load_collector_db_overrides(session)
    assert overrides[EVENTS_ID] == {"enabled": False, "interval_seconds": 300}


async def test_update_collector_setting_rejects_short_interval() -> None:
    async with session_scope(settings=get_settings()) as session:
        with pytest.raises(ValueError):
            await update_collector_setting(session, EVENTS_ID, interval_seconds=5)


async def test_update_collector_setting_leaves_untouched_fields() -> None:
    async with session_scope(settings=get_settings()) as session:
        await update_collector_setting(
            session, EVENTS_ID, enabled=False, timeout_seconds=30.0
        )
    async with session_scope(settings=get_settings()) as session:
        await update_collector_setting(session, EVENTS_ID, interval_seconds=60)
        row = await session.get(CollectorPluginSetting, EVENTS_ID)
        assert row.enabled is False
        assert row.timeout_seconds == 30.0
        assert row.interval_seconds == 60


def test_reconcile_collector_jobs_adds_removes_and_reschedules() -> None:
    settings = Settings()
    scheduler = AsyncIOScheduler()

    first = build_collector_registry(settings)
    assert reconcile_collector_jobs(scheduler, settings, first)["added"]
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert _collector_job_id(EVENTS_ID) in job_ids
    assert _collector_job_id(EVENTS_ID) == "poll_events"

    # 無効化したコレクタのジョブは削除される。
    second = build_collector_registry(
        settings, db_overrides={EVENTS_ID: {"enabled": False}}
    )
    changes = reconcile_collector_jobs(scheduler, settings, second)
    assert changes["removed"] == ["poll_events"]
    assert "poll_events" not in {job.id for job in scheduler.get_jobs()}

    # 再度有効化すると追加され、interval 変更は reschedule される。
    third = build_collector_registry(
        settings, db_overrides={EVENTS_ID: {"enabled": True, "interval_seconds": 111}}
    )
    changes = reconcile_collector_jobs(scheduler, settings, third)
    assert EVENTS_ID in changes["added"]

    fourth = build_collector_registry(
        settings, db_overrides={EVENTS_ID: {"enabled": True, "interval_seconds": 222}}
    )
    changes = reconcile_collector_jobs(scheduler, settings, fourth)
    assert changes["rescheduled"] == [EVENTS_ID]
    assert changes["added"] == [] and changes["removed"] == []

    # 変化がなければ何もしない。
    changes = reconcile_collector_jobs(scheduler, settings, fourth)
    assert changes == {"added": [], "removed": [], "rescheduled": []}


def _enable_management(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEA_PLUGIN_MANAGEMENT_ENABLED", "true")
    get_settings.cache_clear()


async def test_management_endpoints_are_hidden_when_disabled(
    client: AsyncClient,
) -> None:
    set_collector_registry(build_collector_registry(Settings()))
    try:
        assert (await client.get("/api/plugins/collectors")).status_code == 200
        patch = await client.patch(
            f"/api/plugins/collectors/{EVENTS_ID}", json={"enabled": False}
        )
        reload = await client.post("/api/plugins/collectors/reload")
    finally:
        set_collector_registry(None)
    assert patch.status_code == 404
    assert reload.status_code == 404


async def test_patch_persists_and_reload_applies_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_management(monkeypatch)
    set_collector_registry(build_collector_registry(Settings()))
    try:
        listed = (await client.get("/api/plugins/collectors")).json()
        assert listed["management_enabled"] is True
        assert listed["reload_required"] is False
        generation = listed["generation"]

        patched = await client.patch(
            f"/api/plugins/collectors/{EVENTS_ID}",
            json={"enabled": False, "interval_seconds": 600},
        )
        assert patched.status_code == 200
        body = patched.json()
        # 保存しただけでは稼働中の世代には反映されない。
        assert body["reload_required"] is True
        assert body["generation"] == generation
        events = next(c for c in body["collectors"] if c["id"] == EVENTS_ID)
        assert events["status"] == "enabled"

        reloaded = await client.post("/api/plugins/collectors/reload")
        assert reloaded.status_code == 200
        reload_body = reloaded.json()
        assert reload_body["generation"] == generation + 1
        events = next(c for c in reload_body["collectors"] if c["id"] == EVENTS_ID)
        assert events["status"] == "disabled"

        after = (await client.get("/api/plugins/collectors")).json()
        assert after["reload_required"] is False
        assert after["generation"] == generation + 1
    finally:
        set_collector_registry(None)


async def test_patch_rejects_unknown_collector(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_management(monkeypatch)
    set_collector_registry(build_collector_registry(Settings()))
    try:
        response = await client.patch(
            "/api/plugins/collectors/nope.nothing", json={"enabled": True}
        )
    finally:
        set_collector_registry(None)
    assert response.status_code == 404


async def test_patch_rejects_out_of_range_interval(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_management(monkeypatch)
    set_collector_registry(build_collector_registry(Settings()))
    try:
        response = await client.patch(
            f"/api/plugins/collectors/{EVENTS_ID}", json={"interval_seconds": 5}
        )
    finally:
        set_collector_registry(None)
    assert response.status_code == 422


async def test_reload_required_ignores_env_locked_fields(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """env で固定された項目は DB 値が効かないのが正なので、未反映として数えない。"""
    _enable_management(monkeypatch)
    monkeypatch.setenv("VEA_COLLECTOR__BUILTIN_VCENTER_EVENTS__INTERVAL_SECONDS", "77")
    set_collector_registry(build_collector_registry(Settings()))
    try:
        await client.patch(
            f"/api/plugins/collectors/{EVENTS_ID}", json={"interval_seconds": 600}
        )
        body = (await client.get("/api/plugins/collectors")).json()
    finally:
        set_collector_registry(None)
    events = next(c for c in body["collectors"] if c["id"] == EVENTS_ID)
    assert events["interval_seconds"] == 77
    assert events["env_locked_fields"] == ["interval_seconds"]
    assert body["reload_required"] is False
