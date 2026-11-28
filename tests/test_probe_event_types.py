"""PDL・APD の確認内容と、実機へ送る要求・共有用出力の守りを試験する。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest
from pyVmomi import SoapAdapter, vim, vmodl
from pyVmomi.VmomiSupport import newestVersions
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from scripts import probe_event_types as probe
from vcenter_event_assistant.db.base import Base
from vcenter_event_assistant.db.models import EventEntity, EventRecord, VCenter
from vcenter_event_assistant.settings import Settings

_NOW = datetime(2026, 11, 26, tzinfo=timezone.utc)
_SCSI, _PSASTOR, _START, _TIMEOUT, _EXIT = probe.EVENT_TYPES
_NAME = "hidden-vcenter-registration"
_VCENTER = "hidden-vcenter.example"
_HOST_ID = "host-8749"
_HOST = f"{_HOST_ID}.hidden-esxi.example"
_DS_ID = "datastore-5843"
_DS = f"{_DS_ID}.hidden-datastore"
_DEVICE = "naa.6000c29cfa4794a4cb279b94a5fcc47e"
_OTHER = "eui.0011223344556677"
_IP = "192.0.2.43"
_NUM = "1729"
_DETAIL = "hidden-argument-value"
_BODY = f"Device {_DEVICE} at {_HOST} on {_DS} became unavailable."


class _BrokenDetail:
    fullFormat = f"{_START} | APD began"

    @property
    def key(self):
        raise KeyError("hidden-catalog-exception")


class _BrokenCatalog:
    @property
    def eventInfo(self):
        raise LookupError("hidden-catalog-response")


@pytest.fixture
def endpoints(monkeypatch):
    manager = Mock()
    manager.description = SimpleNamespace(eventInfo=[])
    manager.QueryEvents.return_value = []
    manager.QueryEvents.side_effect = lambda spec: [
        row
        for row in manager.QueryEvents.return_value
        if row.eventTypeId in spec.eventTypeId
    ]
    si = Mock()
    si.RetrieveContent.return_value = SimpleNamespace(eventManager=manager)
    connect = Mock(return_value=si)
    disconnect = Mock()
    monkeypatch.setattr(probe, "utcnow", lambda: _NOW)
    monkeypatch.setattr(probe, "connect_vcenter", connect)
    monkeypatch.setattr(probe, "disconnect", disconnect)
    return SimpleNamespace(
        manager=manager, si=si, connect=connect, disconnect=disconnect
    )


@pytest.fixture
def stub_db(monkeypatch):
    center = VCenter(
        name=_NAME, host=_VCENTER, username="hidden-user", password="hidden-password"
    )
    center.protocol, center.port, center.verify_ssl = "https", 443, True
    monkeypatch.setattr(probe, "_read_database", AsyncMock(return_value=(center, [])))


@pytest.fixture
async def database(tmp_path, monkeypatch):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'probe db.sqlite'}"
    )
    monkeypatch.setattr(probe, "get_settings", lambda: settings)
    setup = create_async_engine(settings.database_url)
    try:
        async with setup.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(setup)() as session:
            target = VCenter(
                name=_NAME,
                host=_VCENTER,
                username="hidden-user",
                password="hidden-password",
            )
            other = VCenter(
                name="other", host="other.example", username="user", password="password"
            )
            session.add_all([target, other])
            await session.flush()
            saved = EventRecord(
                vcenter_id=target.id,
                event_type=_SCSI,
                vmware_key=1,
                occurred_at=_NOW - timedelta(days=45),
                message=_BODY,
                entity_type="HostSystem",
                entity_name=_HOST,
                entity_moid=_HOST_ID,
            )
            saved.entities = [
                EventEntity(
                    vcenter_id=target.id,
                    role="ds",
                    position=0,
                    is_primary=False,
                    entity_type="Datastore",
                    entity_name=_DS,
                    entity_moid=_DS_ID,
                ),
                EventEntity(
                    vcenter_id=target.id,
                    role="host",
                    position=0,
                    is_primary=True,
                    entity_type="HostSystem",
                    entity_name=_HOST,
                    entity_moid=_HOST_ID,
                ),
            ]
            session.add_all(
                [
                    saved,
                    EventRecord(
                        vcenter_id=other.id,
                        event_type=_SCSI,
                        vmware_key=1,
                        occurred_at=_NOW,
                        message="other-center-message",
                    ),
                    EventRecord(
                        vcenter_id=target.id,
                        event_type="other.event.type",
                        vmware_key=2,
                        occurred_at=_NOW,
                        message="unrelated-event-message",
                    ),
                ]
            )
            await session.commit()
        yield settings
    finally:
        await setup.dispose()


def _event_ex(kind, *, when=_NOW, device=None, body="", host_id=_HOST_ID, **kwargs):
    return vim.event.EventEx(
        eventTypeId=kind,
        createdTime=when,
        fullFormattedMessage=body,
        objectId=host_id,
        objectType=vim.HostSystem,
        arguments=[vmodl.KeyAnyValue(key="disk", value=device)] if device else [],
        **kwargs,
    )


def test_probe_reports_shapes_and_database_scope(database, endpoints, capsys):
    row = _event_ex(
        _SCSI,
        when=_NOW - timedelta(days=2),
        device=_DEVICE,
        body=_BODY,
        host=vim.event.HostEventArgument(host=vim.HostSystem(_HOST_ID), name=_HOST),
        ds=vim.event.DatastoreEventArgument(datastore=vim.Datastore(_DS_ID), name=_DS),
    )
    row2 = _event_ex(
        _SCSI,
        when=_NOW - timedelta(days=1),
        device=_DEVICE,
        body=_BODY,
        host=row.host,
        ds=row.ds,
    )
    row.arguments.extend(
        [
            vmodl.KeyAnyValue(key="addr", value=_IP),
            vmodl.KeyAnyValue(key="retry", value=int(_NUM)),
            vmodl.KeyAnyValue(key="vendor", value="t10.ACME_SERIAL"),
            vmodl.KeyAnyValue(key="path", value="mpx.vmhba1:C0:T0:L0"),
            vmodl.KeyAnyValue(key="detail", value=_DETAIL),
        ]
    )
    extended = vim.event.ExtendedEvent(
        eventTypeId=_PSASTOR,
        createdTime=row.createdTime + timedelta(seconds=2),
        managedObject=vim.HostSystem(_HOST_ID),
        data=[vim.event.ExtendedEvent.Pair(key="lun", value=_DEVICE.upper())],
        fullFormattedMessage=f"{_DEVICE.upper()} is gone",
    )
    endpoints.manager.QueryEvents.return_value = [row, row2, extended]
    endpoints.manager.description.eventInfo = [
        _BrokenDetail(),
        SimpleNamespace(
            key=vim.event.EventEx,
            category="error",
            fullFormat=f"{_SCSI} | disk failed",
            formatOnHost="Disk lost on {host.name}",
            formatOnVm="x" * 300 + "past-limit",
        ),
    ]

    assert probe.main([_NAME, "--days", "7"]) == 0
    captured = capsys.readouterr()
    out = captured.out
    assert captured.err == ""
    assert (
        "[カタログ]" in out
        and "[QueryEvents 直近 7 日]" in out
        and "[アプリの DB]" in out
    )
    assert "eventInfo[0].key 読み取り失敗=KeyError" in out
    assert f"{_START} 一致=1" in out
    assert f'{_SCSI} 一致=1\n  key="EventEx" category="error"' in out
    assert 'formatOnHost="Disk lost on {host.name}"' in out
    assert f"{_EXIT} 一致=0" in out
    assert f"{_SCSI} 件数=2 最古=2.00日前 最新=1.00日前" in out
    assert f"{_EXIT} 件数=0 最古=- 最新=-" in out
    assert "API型=EventEx 件数=2" in out and "API型=ExtendedEvent 件数=1" in out
    assert "objectType=HostSystem 件数=2" in out
    assert "objectIdあり=2 hostあり=2 dsあり=2" in out
    assert "objectIdあり=0 hostあり=0 dsあり=0" in out
    assert (
        "本文 件数=2" in out
        and "Device {disk} at {host} on {ds} became unavailable." in out
    )
    assert "本文 件数=1" in out and "{lun} is gone" in out
    for fields in (
        "disk 型=str 形=naa.+32hex",
        "lun 型=str 形=naa.+32hex",
        "addr 型=str 形=IPv4",
        "retry 型=int 形=number",
        "vendor 型=str 形=t10.",
        "path 型=str 形=mpx.",
        "detail 型=str 形=other",
    ):
        assert f"argument key={fields}" in out
    assert "両種別の組=1" in out and "1超〜10秒=1" in out
    assert f"{_SCSI} 行数=1 最古=45.00日前 最新=45.00日前" in out
    assert f"{_PSASTOR} 行数=0 最古=- 最新=-" in out
    assert "Device {device} at {host} on {ds} became unavailable." in out
    assert "role=host entityType=HostSystem 件数=1" in out
    assert "role=ds entityType=Datastore 件数=1" in out

    sample = next(line for line in out.splitlines() if "objectId=h:" in line)
    aliases = dict(field.split("=") for field in sample.split() if "=h:" in field)
    assert aliases["objectId"] == aliases["host.id"]
    assert {"host.name", "ds.name", "ds.id", "device"} <= aliases.keys()
    assert all(len(value) == 12 for value in aliases.values())
    for value in (
        _NAME,
        _VCENTER,
        _HOST,
        _HOST_ID,
        _DS,
        _DS_ID,
        _DEVICE,
        _OTHER,
        _DETAIL,
        _IP,
        _NUM,
        "ACME_SERIAL",
        "vmhba1",
        "hidden-user",
        "hidden-password",
        "hidden-catalog",
        "other-center-message",
        "unrelated-event-message",
    ):
        assert value.casefold() not in out.casefold()
    endpoints.connect.assert_called_once()
    assert endpoints.connect.call_args.kwargs["host"] == _VCENTER


def test_query_sends_serializable_read_only_request(endpoints, stub_db):
    assert probe.main([_NAME]) == 0
    manager = endpoints.manager
    specs = [entry.args[0] for entry in manager.QueryEvents.call_args_list]
    assert len(specs) == 5
    assert endpoints.si.method_calls == [call.RetrieveContent()]
    endpoints.disconnect.assert_called_once_with(endpoints.si)
    ids = [
        "esx.problem.scsi.device.state.permanentloss",
        "esx.problem.psastor.device.state.permanentloss",
        "esx.problem.storage.apd.start",
        "esx.problem.storage.apd.timeout",
        "esx.clear.storage.apd.exit",
    ]
    for spec, kind in zip(specs, ids, strict=True):
        # 既定の SOAP 2.0 では eventTypeId と maxCount が XML に含まれない。
        xml = SoapAdapter.Serialize(spec, version=newestVersions.Get("vim"))
        assert isinstance(spec.eventTypeId, list) and spec.eventTypeId == [kind]
        assert b"<type>" not in xml
        assert xml.count(b"<eventTypeId>") == 1
        assert f"<eventTypeId>{kind}</eventTypeId>".encode() in xml
        assert b"<disableFullMessage>false</disableFullMessage>" in xml
        assert b"<maxCount>1000</maxCount>" in xml
        assert spec.time.beginTime == _NOW - timedelta(days=30)
        assert spec.time.endTime == _NOW + timedelta(minutes=5)
    assert manager.method_calls == [call.QueryEvents(spec) for spec in specs]


def test_query_splits_saturated_kind_and_deduplicates_boundary(
    endpoints, stub_db, capsys
):
    specs = []
    boundary = _NOW - timedelta(days=15) + timedelta(minutes=2, seconds=30)
    row = _event_ex(_EXIT, when=boundary, key=0)

    def fake_query(spec):
        specs.append(spec)
        if spec.eventTypeId != [_EXIT]:
            return [] if spec.eventTypeId != [_SCSI] else [_event_ex(_SCSI)]
        begin, end = spec.time.beginTime, spec.time.endTime
        if begin < boundary < end:
            return [row] * 1000
        return [row]

    endpoints.manager.QueryEvents.side_effect = fake_query
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out
    assert f"{_SCSI} 件数=1" in out
    assert f"{_EXIT} 件数=1" in out
    assert "QueryEvents の上限" not in out
    parent, left, right = [spec for spec in specs if spec.eventTypeId == [_EXIT]]
    assert parent.time.beginTime == left.time.beginTime
    assert left.time.endTime == right.time.beginTime == boundary
    assert right.time.endTime == parent.time.endTime
    assert len(specs) == 7


@pytest.mark.parametrize("size", [999, 1000])
def test_query_limit(endpoints, stub_db, capsys, size):
    endpoints.manager.QueryEvents.return_value = [
        vim.event.EventEx(eventTypeId=_EXIT, createdTime=_NOW, key=index + 1)
        for index in range(size)
    ]
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out
    assert f"{_EXIT} 件数={size}" in out
    warnings = [line for line in out.splitlines() if "QueryEvents の上限" in line]
    assert len(warnings) == (32 if size == 1000 else 0)
    assert all(
        line.startswith(f"{_EXIT} QueryEvents の上限 1000 件に達した範囲 ")
        and "〜" in line
        and "日前" in line
        for line in warnings
    )
    assert len(set(warnings)) == len(warnings)
    if warnings:
        assert "〜0.000000日前" in warnings[-1]
    assert all("〜-" not in line for line in warnings)
    assert endpoints.manager.QueryEvents.call_count == (67 if size == 1000 else 5)


def test_query_continues_when_catalog_cannot_be_read(endpoints, stub_db, capsys):
    endpoints.manager.description = _BrokenCatalog()
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out
    assert "eventInfo 読み取り失敗=LookupError" in out
    assert "hidden-catalog-response" not in out
    assert f"{_SCSI} 件数=0 最古=- 最新=-" in out
    assert f"{_SCSI} 行数=0 最古=- 最新=-" in out


@pytest.mark.parametrize("field", probe._CATALOG_FIELDS)
def test_catalog_matches_exact_id_and_limits_output(endpoints, stub_db, capsys, field):
    entry = {"key": "CustomKey", "fullFormat": "x" * 300 + "past-limit"}
    if field == "fullFormat":
        entry[field] = f"{_SCSI} | " + "y" * 300 + "past-limit"
    elif field == "key":
        entry[field] = _SCSI
    else:
        entry[field] = f"Unrelated prose mentions {_SCSI}"
    sibling = _SCSI + ".noopenhandles"
    endpoints.manager.description.eventInfo = [
        SimpleNamespace(**entry),
        SimpleNamespace(key=vim.event.EventEx, fullFormat=f"{sibling} | sibling-prose"),
    ]
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out
    expected = int(field in {"key", "fullFormat"})
    assert f"{_SCSI} 一致={expected}" in out
    assert f"{_PSASTOR} 一致=0" in out
    assert "past-limit" not in out and "sibling-prose" not in out
    assert f"兄弟 ID {sibling}" in out


def test_probe_drops_rows_with_values_discovered_elsewhere(endpoints, stub_db, capsys):
    endpoints.manager.description.eventInfo = [
        SimpleNamespace(key=vim.event.EventEx, fullFormat=f"{_SCSI} | {_HOST}"),
        SimpleNamespace(key=vim.event.EventEx, fullFormat=f"{_START} | {_VCENTER}"),
        SimpleNamespace(
            key=vim.event.EventEx, fullFormat=f"{_EXIT} | " + "x" * 285 + _DETAIL
        ),
    ]
    endpoints.manager.QueryEvents.return_value = [
        _event_ex(_SCSI, body=f"Unreplaced registration {_NAME}"),
        _event_ex(_SCSI, body=f"Unreplaced datastore {_DS} appears in another event"),
        _event_ex(
            _PSASTOR,
            host_id=None,
            body="Other event",
            objectName=_HOST,
            ds=vim.event.DatastoreEventArgument(
                name=_DS, datastore=vim.Datastore(_DS_ID)
            ),
        ),
        vim.event.EventEx(
            eventTypeId=_EXIT,
            arguments=[vmodl.KeyAnyValue(key="detail", value=_DETAIL)],
        ),
    ]
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out
    assert out.count("伏せきれない値があったので省略") == 3
    assert "Unreplaced" not in out
    assert "x" * 50 not in out
    for value in (_NAME, _VCENTER, _HOST, _DS, _DETAIL):
        assert value not in out
    assert '"{値}"' in out


def test_hash_aliases_are_stable_only_for_one_run(monkeypatch):
    entropy = Mock(side_effect=[b"A" * 32, b"B" * 32])
    monkeypatch.setattr(probe.secrets, "token_bytes", entropy)
    first = probe._Report()
    second = probe._Report()
    assert first.alias(_HOST) == first.alias(_HOST)
    assert first.alias(_HOST) != first.alias(_DS)
    assert first.alias(_HOST) != second.alias(_HOST)
    assert _HOST not in first.alias(_HOST)
    assert entropy.call_args_list == [call(32), call(32)]


def test_pdl_pairing_distinguishes_host_device_time_and_unmatched(
    endpoints, stub_db, capsys
):
    t = _NOW - timedelta(days=1)
    later = t + timedelta(seconds=24)
    endpoints.manager.QueryEvents.return_value = [
        _event_ex(_SCSI, when=t, device=_DEVICE),
        _event_ex(_SCSI, when=later, device=_DEVICE),
        _event_ex(
            _PSASTOR,
            when=later,
            body=f"{_DEVICE}.",
            host_id=None,
            host=vim.event.HostEventArgument(host=vim.HostSystem(_HOST_ID), name=_HOST),
        ),
        _event_ex(_PSASTOR, when=t + timedelta(seconds=2), device=_DEVICE),
        _event_ex(_SCSI, when=later + timedelta(seconds=100), device=_DEVICE),
        _event_ex(_PSASTOR, when=t, device=_OTHER),
        _event_ex(_SCSI, when=t, device=_OTHER, host_id="host-12345"),
        _event_ex(_SCSI, when=t, body="Device unknown"),
        _event_ex(_PSASTOR, when=t, device=_DEVICE, host_id=None),
        vim.event.EventEx(
            eventTypeId=_SCSI, objectId=_HOST_ID, fullFormattedMessage=_DEVICE
        ),
        _event_ex(_EXIT, when=t, device=_DEVICE),
    ]
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out
    assert "両種別の組=2" in out
    assert "組の時刻差 絶対差 0秒=1 0超〜1秒=0 1超〜10秒=1 10超〜60秒=0" in out
    assert f"{_SCSI} 同種別の最小間隔=24秒 相手なし=2" in out
    assert f"{_PSASTOR} 同種別の最小間隔=22秒 相手なし=1" in out
    assert "同じホストの1秒以内に別デバイスあり=1" in out
    assert "デバイスなし=1 デバイス候補複数=0 ホスト不明=1 時刻不明=1" in out
    assert "形=eui.+16hex" in out


def test_pdl_gap_buckets_and_simultaneity_are_per_host(endpoints, stub_db, capsys):
    t = _NOW - timedelta(days=1)
    endpoints.manager.QueryEvents.return_value = [
        _event_ex(_SCSI, when=t, device=_DEVICE),
        _event_ex(_PSASTOR, when=t + timedelta(milliseconds=200), device=_DEVICE),
        _event_ex(_SCSI, when=t, device=_OTHER, host_id="host-12345"),
        _event_ex(
            _PSASTOR,
            when=t + timedelta(seconds=20),
            device=_OTHER,
            host_id="host-12345",
        ),
        _event_ex(_SCSI, when=t, device="t10.ACME_SERIAL", host_id="host-56789"),
        _event_ex(
            _PSASTOR,
            when=t + timedelta(seconds=90),
            device="t10.ACME_SERIAL",
            host_id="host-56789",
        ),
    ]
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out.split("[アプリの DB]", 1)[0]
    assert "両種別の組=2" in out
    assert (
        "各 scsi に最も近い psastor の時刻差 絶対差 0秒=0 0超〜1秒=1 1超〜10秒=0 10超〜60秒=1 60超〜600秒=1"
        in out
    )
    assert "同じホストの1秒以内に別デバイスあり=0" in out


def test_pdl_uses_disk_id_without_partition_and_requires_a_host(
    endpoints, stub_db, capsys
):
    endpoints.manager.QueryEvents.return_value = [
        vim.event.EventEx(
            eventTypeId=kind,
            createdTime=_NOW,
            objectId=object_id,
            fullFormattedMessage=f"Disk {device} became unavailable",
        )
        for object_id in (_HOST_ID, _DEVICE)
        for kind, device in ((_SCSI, _DEVICE + ":1"), (_PSASTOR, _DEVICE))
    ]
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out
    assert "両種別の組=1" in out
    assert "デバイスなし=0 デバイス候補複数=0 ホスト不明=2 時刻不明=0" in out
    assert "Disk {device}:{値} became unavailable" in out
    assert _DEVICE not in out


async def test_database_uses_read_only_sqlite_for_actual_lookup(
    database, monkeypatch, tmp_path
):
    engines, statements = [], []

    def track_engine(url):
        engine = create_async_engine(url)
        engines.append(engine)

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def record(conn, cursor, stmt, parameters, context, executemany):
            statements.append(stmt)

        return engine

    monkeypatch.setattr(probe, "create_async_engine", track_engine)
    center, rows = await probe._read_database(_NAME, database)
    assert center.name == _NAME and len(rows) == 1 and len(rows[0].entities) == 2
    assert len(statements) == 3 and all(
        stmt.startswith("SELECT") for stmt in statements
    )
    (readonly,) = engines
    try:
        async with readonly.begin() as conn:
            with pytest.raises(OperationalError, match="readonly"):
                await conn.execute(text("CREATE TABLE write_probe (id INTEGER)"))
    finally:
        await readonly.dispose()
    missing = tmp_path / "absent.sqlite"
    with pytest.raises(OperationalError):
        await probe._read_database(
            _NAME, Settings(database_url=f"sqlite+aiosqlite:///{missing}")
        )
    assert not missing.exists()


@pytest.mark.parametrize("driver", ["asyncpg", "psycopg"])
async def test_database_sets_postgres_transaction_read_only_before_lookup(
    monkeypatch, driver
):
    engine = SimpleNamespace(dispose=AsyncMock())
    session = Mock()
    session.get_bind.return_value = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql")
    )
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session
    create = Mock(return_value=engine)
    monkeypatch.setattr(probe, "create_async_engine", create)
    monkeypatch.setattr(
        probe, "async_sessionmaker", Mock(return_value=lambda: session_context)
    )

    url = f"postgresql+{driver}://localhost/probe"
    assert await probe._read_database(_NAME, Settings(database_url=url)) == (None, [])
    if driver == "asyncpg":
        create.assert_called_once_with(
            url,
            connect_args={
                "server_settings": {"default_transaction_read_only": "on"},
            },
        )
    else:
        create.assert_called_once_with(url)
    methods = [
        (entry[0], str(entry.args[0]))
        for entry in session.method_calls
        if entry[0] != "get_bind"
    ]
    assert len(methods) == 2
    assert methods[0] == ("execute", "SET TRANSACTION READ ONLY")
    assert methods[1][0] == "scalar" and methods[1][1].startswith("SELECT")
    engine.dispose.assert_awaited_once()


_PRIVATE_BODY_VALUES = (
    "PROD-DS-01",
    "192.0.2.50",
    "vmhba2:C0:T3:L4",
    "6718b128-006c6074-9850-b7b58cbc7286",
    "iqn.2024-02.example:private-target",
    "bluebranch",
    "2001:db8::27",
    "秘密識別子",
)
_PDL_BODY = (
    f"Device {_DEVICE} has been removed or is permanently inaccessible. "
    f'Affected datastores (if any): "{_PRIVATE_BODY_VALUES[0]}".\nPath at '
    + " ".join(_PRIVATE_BODY_VALUES[1:])
)
_SAFE_PDL_BODY = (
    "Device {device} has been removed or is permanently inaccessible. "
    "Affected datastores (if any): {値} Path at {値}"
)


def test_body_allowlist_is_fixed():
    assert probe._WORDS == frozenset(
        """a affected all any apd are as at became been by cannot datastore datastores
        device devices disk due entered exited for from gone has have host if in inaccessible
        is lost loss no of on or path paths pdl permanent permanently removed
        restored state storage the timed timeout to unavailable was were with
        after be being down failed fast filesystem identifier now seconds will""".split()
    )


def test_template_hides_unobserved_values_before_output_checks():
    report = probe._Report()
    message = probe._Message(_PDL_BODY)
    template = message.template(report, set(probe._WORDS))
    for value in _PRIVATE_BODY_VALUES:
        assert value not in template
    assert template == _SAFE_PDL_BODY
    assert (
        probe._Message('Host "device host" at "lost').template(
            report, set(probe._WORDS)
        )
        == "Host {値} at {値}"
    )
    assert (
        probe._Message('Host "device host\\').template(report, set(probe._WORDS))
        == "Host {値}"
    )
    assert (
        probe._Message("Host state\u0338").template(report, set(probe._WORDS))
        == "Host {値}"
    )
    assert (
        probe._Message("Host“device host”").template(report, set(probe._WORDS))
        == "Host{値}"
    )
    assert (
        probe._Message("Device datastore-5843.hidden-datastore").template(
            report, set(probe._WORDS)
        )
        == "Device {値}"
    )


@pytest.mark.parametrize(
    "value",
    [
        "host.example",
        "192.0.2.50",
        "2001:db8::27",
        "::dead",
        "6f0d2893-e766-4567-af72-cac500d677d4",
        "6718b128-006c6074-9850-b7b58cbc7286",
        "vmhba2:C0:T3:L4",
        "iqn.2024-02.example:private-target",
        _DEVICE,
    ],
)
def test_emit_omits_residual_identifier_shapes_even_after_truncation(capsys, value):
    report = probe._Report()
    report.add(
        "  本文 件数=1 " + "x" * 300, original="x" * 300 + " " + value, template=True
    )
    report.emit()
    assert capsys.readouterr().out == "伏せきれない値があったので省略\n"


def test_short_and_generic_values_do_not_omit_fixed_lines(endpoints, stub_db, capsys):
    event_row = _event_ex(_SCSI, body=_PDL_BODY + ". Host apd was removed.")
    event_row.datacenter = vim.event.DatacenterEventArgument(
        name="Datacenter",
        datacenter=vim.Datacenter("datacenter-1173"),
    )
    event_row.host = vim.event.HostEventArgument(
        name="apd.example",
        host=vim.HostSystem(_HOST_ID),
    )
    event_row.arguments.extend(
        [
            vmodl.KeyAnyValue(key="1", value="1"),
            vmodl.KeyAnyValue(key="2", value="esx"),
            vmodl.KeyAnyValue(key="3", value="root"),
        ]
    )
    endpoints.manager.QueryEvents.return_value = [event_row]
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out
    assert "[QueryEvents 直近 30 日]" in out and "[アプリの DB]" in out
    assert f"{_SCSI} 件数=1" in out
    assert f"{_SCSI} 行数=0" in out
    assert "hostあり=1" in out and "両種別の組=0" in out
    assert _SAFE_PDL_BODY in out
    assert "Host {host} was removed." in out
    assert "Host apd was removed." not in out
    assert all(value not in out for value in _PRIVATE_BODY_VALUES)

    report = probe._Report()
    report.remember("1", "3648", "esx", "root", "Datacenter")
    report.remember_host("bluebranch.example")
    report.remember_host("abc.example")
    assert report.private == {
        "root",
        "datacenter",
        "bluebranch",
        "bluebranch.example",
        "abc.example",
    }
    report.add("Datacenter 3648 root")
    report.add("対象 件数=1", original="root")
    report.emit()
    assert capsys.readouterr().out.splitlines() == [
        "Datacenter 3648 root",
        probe._OMITTED,
    ]


def test_emit_checks_escaped_display_as_well_as_unabridged_value(capsys):
    report = probe._Report()
    report.remember(r"opaque\nvalue")
    value = "opaque\nvalue"
    report.add(f"  定型文={probe._quoted(value)}", original=value)
    report.emit()
    assert capsys.readouterr().out == probe._OMITTED + "\n"


def test_probe_does_not_read_event_id_or_tgw_properties():
    class Event:
        _wsdlName = "Event"

        @property
        def eventId(self):
            raise AssertionError("eventId")

        @property
        def tgw(self):
            raise AssertionError("tgw")

    assert probe._observe(Event(), probe._Report()).kind == "Event"


def test_replacements_require_left_boundary_and_mask_all_moid_shapes():
    report = probe._Report()
    message = probe._Message(
        "-keyvalue keyvalue .keyvalue domain-c4 domain-s4 resgroup-8 group-9 network-5 dvs-4 dvportgroup-5"
    )
    message.replace("keyvalue", "disk", report)
    assert message.template(report, set(probe._WORDS)) == (
        "-{値} {disk} .{値} " + " ".join(["{moid}"] * 7)
    )


@pytest.mark.parametrize("where", ["connect", "query"])
def test_db_templates_are_safe_when_vcenter_fails(
    where, endpoints, database, capsys, monkeypatch
):
    read = probe._read_database

    async def with_db_only_message(*args):
        center, rows = await read(*args)
        rows[0].message = _PDL_BODY + ' on "DB-ONLY-DATASTORE" at secretbranch'
        return center, rows

    monkeypatch.setattr(probe, "_read_database", with_db_only_message)
    api = endpoints.connect if where == "connect" else endpoints.manager.QueryEvents
    api.side_effect = ConnectionError("private exception payload bluebranch.example")

    assert probe.main([_NAME]) == 1
    output = capsys.readouterr()
    assert "vCenter 読み取り失敗=ConnectionError" in output.out
    assert "[アプリの DB]" in output.out and f"{_SCSI} 行数=1" in output.out
    assert _SAFE_PDL_BODY in output.out
    assert all(
        value not in output.out + output.err
        for value in (
            *_PRIVATE_BODY_VALUES,
            "DB-ONLY-DATASTORE",
            "secretbranch",
            "private exception payload",
        )
    )
    if where == "query":
        endpoints.disconnect.assert_called_once_with(endpoints.si)


def test_catalog_words_belong_to_the_exact_kind(endpoints, stub_db, capsys):
    endpoints.manager.description.eventInfo = [
        SimpleNamespace(
            key=_SCSI,
            fullFormat='Connectivity signal at {argumentName} "hiddenquoted"',
            formatOnHost="Availability on {host.name}",
            formatOnVm="Unreachable",
        ),
        SimpleNamespace(
            key=_PSASTOR + ".noopenhandles",
            fullFormat="Siblingword",
            description=_PSASTOR,
        ),
    ]
    message = (
        "Connectivity Availability Unreachable argumentName hiddenquoted Siblingword"
    )
    endpoints.manager.QueryEvents.return_value = [
        _event_ex(_SCSI, body=message),
        _event_ex(_PSASTOR, body=message),
    ]
    assert probe.main([_NAME]) == 0
    templates = [
        line for line in capsys.readouterr().out.splitlines() if "本文 件数" in line
    ]
    assert templates == [
        '  本文 件数=1 "Connectivity Availability Unreachable {値}"',
        '  本文 件数=1 "{値}"',
    ]


def test_correlation_window_signs_and_ambiguous_devices(endpoints, stub_db, capsys):
    t = _NOW - timedelta(days=3)
    endpoints.manager.QueryEvents.return_value = [
        _event_ex(_SCSI, when=t, device=_DEVICE, body=_DEVICE.upper()),
        _event_ex(_SCSI, when=t + timedelta(seconds=8), device=_DEVICE),
        _event_ex(_PSASTOR, when=t - timedelta(seconds=2), device=_DEVICE),
        _event_ex(_PSASTOR, when=t + timedelta(seconds=13), device=_DEVICE),
        _event_ex(_SCSI, when=t, device=_OTHER, host_id="host-52"),
        _event_ex(
            _PSASTOR, when=t + timedelta(seconds=630), device=_OTHER, host_id="host-52"
        ),
        _event_ex(_SCSI, when=t, device=_OTHER, host_id="host-53"),
        _event_ex(
            _PSASTOR, when=t + timedelta(days=1), device=_OTHER, host_id="host-53"
        ),
        _event_ex(_SCSI, when=t + timedelta(milliseconds=800), body=_OTHER),
        _event_ex(_SCSI, when=t, body=f"{_DEVICE} {_OTHER}"),
        _event_ex(_PSASTOR, when=t, body="storage path is lost"),
    ]
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out.split("[アプリの DB]", 1)[0]
    assert "組の窓 最小=4秒 最大=60秒" in out
    assert f"{_SCSI} 同種別の最小間隔=8秒 相手なし=4" in out
    assert f"{_PSASTOR} 同種別の最小間隔=15秒 相手なし=3" in out
    assert "両種別の組=1" in out
    assert "組の時刻差 psastor−scsi 最小=-2秒 最大=-2秒" in out
    assert "組の時刻差 負 0超〜1秒=0 1超〜10秒=1" in out
    assert "600超〜3600秒=1 3600超秒=1" in out
    assert "同じホストの1秒以内に別デバイスあり=1" in out
    assert "デバイスなし=1 デバイス候補複数=1" in out
    assert "本文と引数のデバイス一致=1" in out


def test_pair_at_same_time_is_used_once(capsys):
    report = probe._Report()
    probe._pdl_pairs(
        [
            probe._Occurrence(kind, _NOW, _HOST_ID, _DEVICE, 1)
            for kind in (_SCSI, _SCSI, _PSASTOR)
        ],
        report,
        source="DB",
    )
    report.emit()
    out = capsys.readouterr().out
    assert "[PDL の組（DB）]" in out
    assert "組の窓 最小=60秒 最大=60秒" in out
    assert "両種別の組=1" in out
    assert f"{_SCSI} 同種別の最小間隔=- 相手なし=1" in out
    assert f"{_SCSI} 同じ時刻の重複=1" in out


@pytest.mark.parametrize("host_role", ["host", "managedObject"])
def test_database_pairs_use_known_host_before_object_fallback(
    database, monkeypatch, endpoints, capsys, host_role
):
    read = probe._read_database

    async def with_saved_pair(*args):
        center, rows = await read(*args)
        rows[0].entity_type = "Datastore"
        rows[0].entity_moid = _DS_ID
        next(
            entity for entity in rows[0].entities if entity.role == "host"
        ).role = host_role
        rows[0].entities.insert(
            0,
            EventEntity(vcenter_id=center.id, role="object", entity_moid="host-4321"),
        )
        rows.append(
            EventRecord(
                vcenter_id=center.id,
                event_type=_PSASTOR,
                occurred_at=rows[0].occurred_at + timedelta(seconds=3),
                message=f"Device {_DEVICE.upper()} is lost",
                entity_type="HostSystem",
                entity_moid=_HOST_ID,
            )
        )
        return center, rows

    monkeypatch.setattr(probe, "_read_database", with_saved_pair)
    assert probe.main([_NAME]) == 0
    api, database_output = capsys.readouterr().out.split("[アプリの DB]", 1)
    assert "両種別の組=0" in api
    assert "両種別の組=1" in database_output
    assert "組の時刻差 psastor−scsi 最小=3秒 最大=3秒" in database_output


@pytest.mark.parametrize(
    ("role", "entity_type", "moid", "expected_pairs"),
    [
        ("object", None, _HOST_ID, 1),
        ("object", "", _HOST_ID, 1),
        ("object", "Datastore", _HOST_ID, 0),
        ("managedObject", None, _HOST_ID, 0),
        ("object", None, f"{_HOST_ID}-extra", 0),
    ],
)
def test_database_pairs_fall_back_to_untyped_host_object(
    endpoints, stub_db, capsys, role, entity_type, moid, expected_pairs
):
    _, rows = probe._read_database.return_value
    for kind in probe.PDL_TYPES:
        body = f"Device {_DEVICE} at {moid} became unavailable."
        rows.append(
            EventRecord(
                vcenter_id=1,
                event_type=kind,
                occurred_at=_NOW,
                message=body,
                entity_type=entity_type,
                entity_moid=moid,
                entities=[
                    EventEntity(
                        vcenter_id=1,
                        role=role,
                        entity_type=entity_type,
                        entity_moid=moid,
                    )
                ],
            )
        )
        endpoints.manager.QueryEvents.return_value.append(
            vim.event.EventEx(
                eventTypeId=kind,
                createdTime=_NOW,
                fullFormattedMessage=body,
                objectId=moid,
            )
        )

    assert probe.main([_NAME]) == 0
    output = capsys.readouterr().out
    api, database_output = output.split("[アプリの DB]", 1)
    assert f"両種別の組={expected_pairs}" in database_output
    assert f"ホスト不明={0 if expected_pairs else 2}" in database_output
    assert "objectId=h:" in api
    assert moid not in output
    if expected_pairs:
        assert "両種別の組=1" in api
        assert "at {host} became unavailable" in database_output


@pytest.mark.parametrize("phase", ["_database_summary", "emit"])
def test_rendering_errors_print_only_the_type(
    endpoints, stub_db, capsys, monkeypatch, phase
):
    target = probe._Report if phase == "emit" else probe
    monkeypatch.setattr(
        target, phase, Mock(side_effect=ValueError("private render value"))
    )
    assert probe.main([_NAME]) == 1
    captured = capsys.readouterr()
    assert "private render value" not in captured.out + captured.err
    if phase == "emit":
        assert captured.err == "出力失敗=ValueError\n"
    else:
        assert "DB 集計失敗=ValueError" in captured.out


def test_days_overflow_is_an_argument_error(endpoints, stub_db, capsys):
    with pytest.raises(SystemExit) as error:
        probe.main([_NAME, "--days", "9999999999"])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "--days が大きすぎます。" in captured.err
    assert "DB 読み取り失敗" not in captured.out + captured.err
    endpoints.connect.assert_not_called()


@pytest.mark.parametrize(
    "args",
    [
        [_NAME, "--days", "private-center.example"],
        [_NAME, "private-center.example"],
    ],
)
def test_argument_errors_do_not_echo_private_values(endpoints, stub_db, capsys, args):
    with pytest.raises(SystemExit) as error:
        probe.main(args)
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "引数を確認してください。" in captured.err
    assert "private-center.example" not in captured.out + captured.err
    endpoints.connect.assert_not_called()


def test_missing_center_is_reported_on_stderr(endpoints, stub_db, capsys):
    probe._read_database.return_value = (None, [])
    assert probe.main([_NAME]) == 1
    captured = capsys.readouterr()
    assert (
        captured.out == "" and captured.err == "登録済みの vCenter が見つかりません。\n"
    )
    endpoints.connect.assert_not_called()


def test_affected_datastores_masks_allowlisted_db_names_to_end_of_line(
    endpoints, database, capsys, monkeypatch
):
    read = probe._read_database

    async def with_db_only_message(*args):
        center, rows = await read(*args)
        rows[0].message = (
            "Device is lost.aFfEcTeD datastores (if any): "
            "Storage, Shared Storage. Host Disk, PDL Lost, [Fast], Failed Now.\r\n"
            "Path is lost."
        )
        return center, rows

    monkeypatch.setattr(probe, "_read_database", with_db_only_message)
    endpoints.manager.description.eventInfo = [
        SimpleNamespace(key=_SCSI, fullFormat="Shared Fast Failed Now"),
    ]
    assert probe.main([_NAME]) == 0
    templates = [
        line for line in capsys.readouterr().out.splitlines() if "本文 件数" in line
    ]
    assert len(templates) == 1
    assert "datastores (if any): {値}  Path is lost." in templates[0]
    for value in ("Storage", "Shared", "Host Disk", "PDL Lost", "Fast", "Failed Now"):
        assert value not in templates[0]


def test_hashed_sample_and_allowed_words_survive_remembered_names(
    endpoints, stub_db, capsys
):
    first = _event_ex(_SCSI, body="Device Storage Calibrated is lost.")
    first.datacenter = vim.event.DatacenterEventArgument(
        name="Datacenter",
        datacenter=vim.Datacenter("datacenter-1173"),
    )
    first.arguments.extend(
        vmodl.KeyAnyValue(key=key, value=value)
        for key, value in [("1", "sToRaGe"), ("2", "DEVICE"), ("3", "calibrated")]
    )
    second = _event_ex(_SCSI, body=first.fullFormattedMessage, host_id=None)
    endpoints.manager.QueryEvents.return_value = [first, second]
    endpoints.manager.description.eventInfo = [
        SimpleNamespace(key=_SCSI, formatOnHost="Calibrated"),
    ]

    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out
    assert "datacenter.name=h:" in out and "datacenter.id=h:" in out
    assert "Device Storage Calibrated is lost." in out
    assert "datacenter.name=Datacenter" not in out


def test_catalog_free_apd_keeps_verified_timeout_words(endpoints, stub_db, capsys):
    apd = _event_ex(
        _TIMEOUT,
        body=(
            f"Device or filesystem with identifier [{_DEVICE}] has entered the All Paths "
            "Down Timeout state after being in the All Paths Down state for 140 seconds. "
            "I/Os will now be fast failed."
        ),
    )
    endpoints.manager.QueryEvents.return_value = [apd]
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out
    assert f"{_TIMEOUT} 一致=0" in out
    assert "filesystem with identifier [{device}]" in out
    assert "Down Timeout state after being in" in out
    assert "for {値} seconds. {値} will now be fast failed." in out
    assert _DEVICE not in out


def test_scsi_windows_are_local_and_ignore_same_timestamp_duplicates(capsys):
    times = {_SCSI: [0, 0, 4, 200], _PSASTOR: [1, 205, 206]}
    report = probe._Report()
    probe._pdl_pairs(
        [
            probe._Occurrence(
                kind, _NOW + timedelta(seconds=offset), _HOST_ID, _DEVICE, 1
            )
            for kind, offsets in times.items()
            for offset in offsets
        ]
        + [
            probe._Occurrence(
                kind, _NOW + timedelta(seconds=offset), _HOST_ID, _OTHER, 1
            )
            for kind, offset in ((_SCSI, 0), (_SCSI, 4), (_PSASTOR, -3))
        ],
        report,
        source="vCenter",
    )
    report.emit()
    out = capsys.readouterr().out
    assert "[PDL の組（vCenter）]" in out
    assert "組の窓 最小=2秒 最大=60秒" in out
    assert "両種別の組=2" in out
    assert "組の時刻差 psastor−scsi 最小=1秒 最大=5秒" in out
    assert f"{_SCSI} 同じ時刻の重複=1" in out
    assert f"{_PSASTOR} 同じ時刻の重複=0" in out


def test_nearest_distributions_in_both_directions_with_or_without_device(capsys):
    t = _NOW
    report = probe._Report()
    probe._pdl_pairs(
        [
            probe._Occurrence(_SCSI, t, _HOST_ID, _DEVICE, 1),
            probe._Occurrence(_PSASTOR, t - timedelta(seconds=9), _HOST_ID, _DEVICE, 1),
            probe._Occurrence(_PSASTOR, t + timedelta(seconds=6), _HOST_ID, _DEVICE, 1),
            probe._Occurrence(_PSASTOR, t + timedelta(seconds=2), _HOST_ID, _OTHER, 1),
            probe._Occurrence(_PSASTOR, t + timedelta(seconds=1), _HOST_ID, None, 0),
            probe._Occurrence(_PSASTOR, t, "host-929", _DEVICE, 1),
        ],
        report,
        source="DB",
    )
    report.emit()
    lines = capsys.readouterr().out.splitlines()
    assert (
        "  各 scsi に最も近い psastor の時刻差 psastor−scsi 最小=6秒 最大=6秒" in lines
    )
    assert (
        "  各 psastor に最も近い scsi の時刻差 psastor−scsi 最小=-9秒 最大=6秒" in lines
    )
    assert (
        "  同じホストで各 scsi に最も近い psastor の時刻差 psastor−scsi 最小=1秒 最大=1秒"
        in lines
    )
    assert (
        "  同じホストで各 psastor に最も近い scsi の時刻差 正 0超〜1秒=1 1超〜10秒=2 10超〜60秒=0 60超〜600秒=0 600超〜3600秒=0 3600超秒=0"
        in lines
    )


def test_catalog_sibling_queries_are_bounded_and_only_report_count_and_host_gap(
    endpoints, stub_db, capsys, monkeypatch
):
    eligible = [_SCSI + f".notice{index:02d}" for index in range(11)]
    eligible[0] = _SCSI + ".noopenhandles"
    selected = eligible[0]
    unrelated = "esx.problem.unrelated"
    body_only = _SCSI + ".notakey"
    endpoints.manager.description.eventInfo = [
        *(SimpleNamespace(key=kind) for kind in reversed(eligible)),
        SimpleNamespace(key=unrelated, description=body_only),
    ]
    midpoint = _NOW - timedelta(days=15) + timedelta(minutes=2, seconds=30)
    sibling = _event_ex(
        selected,
        when=midpoint,
        device=_OTHER,
        body="private sibling event payload",
        key=81,
    )
    pdl = [
        _event_ex(_SCSI, when=midpoint - timedelta(seconds=5), device=_DEVICE),
        _event_ex(_PSASTOR, when=midpoint, host_id="host-456", device=_OTHER),
    ]
    monkeypatch.setattr(probe, "_QUERY_LIMIT", 2)

    def query(spec):
        (kind,) = spec.eventTypeId
        if kind == selected:
            if spec.time.beginTime < midpoint < spec.time.endTime:
                return [sibling, sibling]
            return [sibling]
        return [event for event in pdl if event.eventTypeId == kind]

    endpoints.manager.QueryEvents.side_effect = query
    assert probe.main([_NAME]) == 0
    out = capsys.readouterr().out
    assert "問い合わせ上限で省いた兄弟 ID 数=1" in out
    assert "[PDL の組（vCenter）]" in out and "[PDL の組（DB）]" in out
    siblings = out.split("[兄弟イベント（vCenter）]", 1)[1].split("[アプリの DB]", 1)[0]
    assert siblings.count("兄弟イベント件数") == 10
    assert f"{selected} 兄弟イベント件数=1" in siblings
    assert "同じホストで最も近い PDL との時刻差 兄弟−PDL 最小=5秒 最大=5秒" in siblings
    assert all(
        word not in siblings
        for word in ("本文", "対象 件数", "private sibling", _OTHER)
    )
    calls = [
        entry.args[0].eventTypeId[0]
        for entry in endpoints.manager.QueryEvents.call_args_list
    ]
    assert calls == [*probe.EVENT_TYPES, selected, selected, selected, *eligible[1:10]]
    assert all(value not in out for value in (unrelated, body_only, eligible[-1]))


def test_period_reports_future_events_as_zero_days_ago():
    assert (
        probe._period([_NOW + timedelta(minutes=2)], _NOW)
        == "最古=0.00日前 最新=0.00日前"
    )
