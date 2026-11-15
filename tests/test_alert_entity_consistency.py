"""通知履歴（GET /api/alerts/history）とタイムライン（POST /api/incident-timeline/view）で、
metric_threshold のアラートの対象名が一致することを確かめる。

対象名は「そのアラートの ``occurred_at`` の時点の名前」（``sampled_at <= occurred_at`` で最も新しいサンプル。
さかのぼる下限は ``occurred_at − metric_name_lookback``）。表示期間やページの区切りに依存しないので、
通知履歴の行の「タイムラインで見る」リンクで開いたタイムラインに、その行自身が必ず出る。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.db.models import AlertHistory, AlertRule, MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_entity_resolution import metric_name_lookback
from vcenter_event_assistant.services.alerting.alert_eval_common import metric_context_key
from vcenter_event_assistant.settings_binding import require_settings

T0 = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
CPU = "host.cpu.usage_pct"
HISTORY_URL = "/api/alerts/history"
TIMELINE_URL = "/api/incident-timeline/view"

# 通知履歴の行からタイムラインを開くときの、occurred_at の前後の幅。
# frontend/src/routing/timelineHash.ts の TIMELINE_ENTRY_HALF_WIDTH_MS（30 * 60_000 ミリ秒）と同じ値にする。
# 画面側の値を変えたら、ここも合わせる。
ENTRY_HALF_WIDTH = timedelta(minutes=30)


async def _vcenter(name: str) -> uuid.UUID:
    vid = uuid.uuid4()
    async with session_scope() as session:
        session.add(VCenter(id=vid, name=name, host="h", port=443, username="u", password="p"))
    return vid


async def _sample(vid: uuid.UUID, moid: str, name: str, at: datetime, *, metric_key: str = CPU) -> None:
    async with session_scope() as session:
        session.add(
            MetricSample(
                vcenter_id=vid, sampled_at=at, entity_type="VirtualMachine", entity_moid=moid,
                entity_name=name, metric_key=metric_key, value=95.0,
            )
        )


async def _alert(
    vid: uuid.UUID, moid: str, at: datetime, *, name: str, metric_key: str = CPU, state: str = "firing"
) -> int:
    async with session_scope() as session:
        rule = AlertRule(
            name=name, rule_type="metric_threshold", alert_level="critical",
            config={"metric_key": metric_key, "threshold": 90},
        )
        session.add(rule)
        await session.flush()
        row = AlertHistory(
            rule_id=rule.id, alert_level="critical", state=state,
            context_key=metric_context_key(vid, moid),
            occurred_at=at, notified_at=at, channel="none", success=None,
        )
        session.add(row)
        await session.flush()
        return row.id


def _parse_api_utc(value: str) -> datetime:
    """画面の parseApiUtcInstantMs と同じく、タイムゾーンの無い値は UTC として読む。"""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso_ms(value: datetime) -> str:
    """画面の Date#toISOString と同じく、ミリ秒までの UTC の文字列にする。"""
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _history(client: AsyncClient, **params: int) -> list[dict]:
    resp = await client.get(HISTORY_URL, params={"limit": 200, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def _timeline(client: AsyncClient, body: dict) -> dict:
    resp = await client.post(TIMELINE_URL, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _entry_link_body(row: dict) -> dict:
    """通知履歴の行の「タイムラインで見る」リンクと同じ条件（timelineEntryHash）。"""
    occurred = _parse_api_utc(row["occurred_at"])
    body: dict[str, object] = {
        "from": _iso_ms(occurred - ENTRY_HALF_WIDTH),
        "to": _iso_ms(occurred + ENTRY_HALF_WIDTH),
        "anchor": _iso_ms(occurred),
        "sources": ["event", "alert"],
    }
    if row["vcenter_id"]:
        body["vcenter_id"] = row["vcenter_id"]
    if row["entity_name"]:
        body["entity"] = row["entity_name"]
    return body


async def _assert_each_row_is_found_by_its_link(client: AsyncClient, rows: list[dict]) -> None:
    for row in rows:
        data = await _timeline(client, _entry_link_body(row))
        hits = [i for i in data["items"] if i["id"] == f"alert:{row['id']}"]
        assert hits, (row, data["items"])
        assert hits[0]["entity_name"] == row["entity_name"]


# --- 一貫性: 通知履歴のリンクで開いたタイムラインに、その行が出る -------------------------


@pytest.mark.asyncio
async def test_link_finds_each_row_when_the_vm_was_renamed_between_rows(client: AsyncClient) -> None:
    """(a) 同じ VM の 3 日離れた 2 行の間に web-old → web-new の改名がある。"""
    vid = await _vcenter("vc-rename")
    await _sample(vid, "vm-1", "web-old", T0 - timedelta(minutes=5))
    await _sample(vid, "vm-1", "web-new", T0 + timedelta(days=3) - timedelta(minutes=5))
    old_id = await _alert(vid, "vm-1", T0, name="cpu-old")
    new_id = await _alert(vid, "vm-1", T0 + timedelta(days=3), name="cpu-new")

    rows = await _history(client)
    by_id = {r["id"]: r for r in rows}
    assert by_id[old_id]["entity_name"] == "web-old"
    assert by_id[new_id]["entity_name"] == "web-new"
    await _assert_each_row_is_found_by_its_link(client, rows)


@pytest.mark.asyncio
async def test_link_finds_the_row_when_the_vm_is_renamed_right_after_it(client: AsyncClient) -> None:
    """(b) 1 行だけのページ。サンプルは T−5 分（web-a）と T+10 分（web-b）で、行の時刻は T。"""
    vid = await _vcenter("vc-single")
    t = T0 + timedelta(hours=5, microseconds=123_456)
    await _sample(vid, "vm-1", "web-a", t - timedelta(minutes=5))
    await _sample(vid, "vm-1", "web-b", t + timedelta(minutes=10))
    row_id = await _alert(vid, "vm-1", t, name="cpu-single")

    (row,) = await _history(client)
    assert row["id"] == row_id
    assert row["entity_name"] == "web-a"
    await _assert_each_row_is_found_by_its_link(client, [row])


# --- 名前が表示期間・ページの区切りに依存しない -------------------------------------------


@pytest.mark.asyncio
async def test_timeline_gives_the_same_name_whatever_the_period(client: AsyncClient) -> None:
    vid = await _vcenter("vc-period")
    t = T0 + timedelta(hours=5)
    await _sample(vid, "vm-1", "web-a", t - timedelta(minutes=5))
    await _sample(vid, "vm-1", "web-b", t + timedelta(minutes=10))
    await _sample(vid, "vm-1", "web-c", t + timedelta(days=2))
    row_id = await _alert(vid, "vm-1", t, name="cpu-period")

    periods = [
        (t - timedelta(minutes=30), t + timedelta(minutes=30)),
        (t - timedelta(minutes=1), t + timedelta(seconds=1)),
        (t - timedelta(hours=6), t + timedelta(hours=6)),
        (t - timedelta(days=1), t + timedelta(days=3)),
    ]
    names = []
    for start, end in periods:
        data = await _timeline(client, {"from": _iso_ms(start), "to": _iso_ms(end), "sources": ["alert"]})
        (item,) = [i for i in data["items"] if i["id"] == f"alert:{row_id}"]
        names.append(item["entity_name"])
    assert names == ["web-a"] * len(periods)

    # 対象の絞り込みも、アラートの時点の名前に当てる（後の名前では出ない）
    for needle, expected in (("web-a", [f"alert:{row_id}"]), ("web-b", []), ("web-c", [])):
        data = await _timeline(
            client,
            {"from": _iso_ms(periods[3][0]), "to": _iso_ms(periods[3][1]), "sources": ["alert"], "entity": needle},
        )
        assert [i["id"] for i in data["items"]] == expected, needle


@pytest.mark.asyncio
async def test_history_gives_the_same_name_whatever_the_page(client: AsyncClient) -> None:
    vid = await _vcenter("vc-page")
    names = ["web-1", "web-2", "web-3", "web-4"]
    times = [T0 + timedelta(days=d) for d in range(len(names))]
    for name, at in zip(names, times, strict=True):
        await _sample(vid, "vm-1", name, at - timedelta(minutes=5))
    ids = [await _alert(vid, "vm-1", at, name=f"cpu-page-{n}") for n, at in enumerate(times)]
    expected = dict(zip(ids, names, strict=True))

    full = {r["id"]: r["entity_name"] for r in await _history(client)}
    assert full == expected
    for limit in (1, 2, 3):
        for offset in range(len(ids)):
            for r in await _history(client, limit=limit, offset=offset):
                assert r["entity_name"] == expected[r["id"]], (limit, offset)


# --- 時刻の境界 ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sample_at_exactly_occurred_at_is_used(client: AsyncClient) -> None:
    """評価器は発火・回復の occurred_at にきっかけのサンプルの sampled_at をそのまま入れるので、等号を含める。"""
    vid = await _vcenter("vc-exact")
    t = T0 + timedelta(hours=1, microseconds=987_654)
    await _sample(vid, "vm-1", "before", t - timedelta(minutes=5))
    await _sample(vid, "vm-1", "at-incident", t)
    await _sample(vid, "vm-1", "after", t + timedelta(microseconds=1))
    row_id = await _alert(vid, "vm-1", t, name="cpu-exact")

    (row,) = await _history(client)
    assert row["entity_name"] == "at-incident"
    data = await _timeline(client, _entry_link_body(row))
    assert [(i["id"], i["entity_name"]) for i in data["items"]] == [(f"alert:{row_id}", "at-incident")]


@pytest.mark.asyncio
async def test_lookback_is_measured_from_each_alert(client: AsyncClient) -> None:
    lookback = metric_name_lookback(require_settings().perf_sample_interval_seconds)
    vid = await _vcenter("vc-lookback")
    t = T0 + timedelta(days=1)
    await _sample(vid, "vm-in", "just-in", t - lookback)
    await _sample(vid, "vm-out", "just-out", t - lookback - timedelta(seconds=1))
    in_id = await _alert(vid, "vm-in", t, name="cpu-in")
    out_id = await _alert(vid, "vm-out", t, name="cpu-out")

    by_id = {r["id"]: r["entity_name"] for r in await _history(client)}
    assert by_id == {in_id: "just-in", out_id: None}
    data = await _timeline(
        client, {"from": _iso_ms(t - timedelta(minutes=30)), "to": _iso_ms(t + timedelta(minutes=30))}
    )
    got = {i["id"]: (i["entity_name"], i["ref"]["entity_moid"]) for i in data["items"]}
    assert got == {f"alert:{in_id}": ("just-in", "vm-in"), f"alert:{out_id}": (None, "vm-out")}


@pytest.mark.asyncio
async def test_samples_only_after_the_alert_do_not_name_it(client: AsyncClient) -> None:
    """サンプルが occurred_at より後にしか無いときは解決しない（後の名前で絞ると、その行がリンクから外れ得る）。"""
    vid = await _vcenter("vc-after")
    t = T0 + timedelta(hours=2)
    await _sample(vid, "vm-1", "later", t + timedelta(minutes=1))
    row_id = await _alert(vid, "vm-1", t, name="cpu-after")

    (row,) = await _history(client)
    assert (row["vcenter_id"], row["entity_name"]) == (str(vid), None)
    data = await _timeline(client, _entry_link_body(row))
    (item,) = data["items"]
    assert (item["id"], item["entity_name"], item["ref"]["entity_moid"]) == (f"alert:{row_id}", None, "vm-1")


@pytest.mark.asyncio
async def test_same_moid_on_another_vcenter_is_not_mixed_at_the_alert_time(client: AsyncClient) -> None:
    v1 = await _vcenter("vc-mix-1")
    v2 = await _vcenter("vc-mix-2")
    t = T0 + timedelta(hours=3)
    await _sample(v1, "vm-1", "web-on-vc1", t - timedelta(minutes=10))
    # v2 の同じ moid のサンプルのほうが occurred_at に近い。vCenter をまたいで取り違えると v1 の名前が変わる
    await _sample(v2, "vm-1", "web-on-vc2", t - timedelta(minutes=1))
    r1 = await _alert(v1, "vm-1", t, name="cpu-mix-1")

    (row,) = [r for r in await _history(client) if r["id"] == r1]
    assert (row["vcenter_id"], row["entity_name"]) == (str(v1), "web-on-vc1")
    await _assert_each_row_is_found_by_its_link(client, [row])


@pytest.mark.asyncio
async def test_row_written_by_the_evaluator_is_named_by_its_triggering_sample(client: AsyncClient) -> None:
    """評価器 → AlertState.fired_at → 通知 → AlertHistory.occurred_at の実際の経路でも、occurred_at は
    きっかけのサンプルの sampled_at とマイクロ秒まで一致し、その名前で解決される（後の改名は拾わない）。"""
    from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator

    vid = await _vcenter("vc-eval")
    async with session_scope() as session:
        session.add(
            AlertRule(
                name="cpu-eval", rule_type="metric_threshold", alert_level="critical",
                config={"metric_key": CPU, "threshold": 90.0},
            )
        )
    now = datetime.now(timezone.utc).replace(microsecond=654_321)
    trigger_at = now - timedelta(minutes=1)
    await _sample(vid, "vm-1", "web-a", now - timedelta(minutes=10))
    await _sample(vid, "vm-1", "web-b", trigger_at)

    await AlertEvaluator(require_settings()).evaluate_all()
    await _sample(vid, "vm-1", "web-c", now)  # 発火の後の改名

    (row,) = await _history(client)
    assert row["state"] == "firing"
    assert _parse_api_utc(row["occurred_at"]) == trigger_at
    assert row["entity_name"] == "web-b"
    await _assert_each_row_is_found_by_its_link(client, [row])


# --- 名前が同じ呼び出しに居合わせるほかのアラート（ほかのルールの指標）に依存しない -------

MEM = "host.mem.usage_pct"


@pytest.mark.asyncio
async def test_link_finds_a_cpu_row_when_a_memory_rule_row_shares_the_page(client: AsyncClient) -> None:
    """Codex の指摘（PR #315）の再現。CPU の stale の行とメモリのルールの行が同じページにある。

    指標ごとに最新のサンプルの名前が違う（CPU は改名前の web-old、メモリは改名後の web-new）。名前を
    呼び出しの全ルールの指標の和集合から引くと、通知履歴（{CPU, メモリ}）では web-new、リンクで開いた
    タイムライン（前後 30 分にはメモリの行が無いので {CPU}）では web-old になり、押した行が除かれる。
    """
    vid = await _vcenter("vc-keys")
    t = T0 + timedelta(days=2)
    await _sample(vid, "vm-1", "web-old", t - timedelta(minutes=20), metric_key=CPU)
    await _sample(vid, "vm-1", "web-new", t - timedelta(minutes=2), metric_key=MEM)
    await _sample(vid, "vm-1", "web-mem", t - timedelta(days=1, minutes=1), metric_key=MEM)
    cpu_id = await _alert(vid, "vm-1", t, name="cpu-stale", metric_key=CPU, state="stale")
    mem_id = await _alert(vid, "vm-1", t - timedelta(days=1), name="mem-high", metric_key=MEM)

    rows = await _history(client)
    by_id = {r["id"]: r for r in rows}
    assert by_id[cpu_id]["entity_name"] == "web-old"
    assert by_id[mem_id]["entity_name"] == "web-mem"
    await _assert_each_row_is_found_by_its_link(client, rows)


@pytest.mark.asyncio
async def test_names_do_not_depend_on_which_other_rules_share_the_call(client: AsyncClient) -> None:
    """ページの区切りや表示期間で居合わせるアラート（指標）の組み合わせが変わっても、各アラートの名前は同じ。"""
    vid = await _vcenter("vc-mixed")
    t = T0 + timedelta(days=3)
    # CPU とメモリで、サンプルの時刻と名前をずらす（指標をまたいで引くと名前が変わる）
    await _sample(vid, "vm-1", "cpu-1", t - timedelta(minutes=30), metric_key=CPU)
    await _sample(vid, "vm-1", "mem-1", t - timedelta(minutes=20), metric_key=MEM)
    await _sample(vid, "vm-1", "cpu-2", t + timedelta(minutes=50), metric_key=CPU)
    await _sample(vid, "vm-1", "mem-2", t + timedelta(minutes=55), metric_key=MEM)
    expected: dict[int, str] = {}
    for minute, key, name in ((0, CPU, "cpu-1"), (10, MEM, "mem-1"), (60, CPU, "cpu-2"), (70, MEM, "mem-2")):
        hid = await _alert(vid, "vm-1", t + timedelta(minutes=minute), name=f"r-{minute}", metric_key=key)
        expected[hid] = name

    assert {r["id"]: r["entity_name"] for r in await _history(client)} == expected
    for limit in (1, 2, 3):
        for offset in range(len(expected)):
            for r in await _history(client, limit=limit, offset=offset):
                assert r["entity_name"] == expected[r["id"]], (limit, offset)

    periods = [
        (t - timedelta(minutes=5), t + timedelta(minutes=5)),
        (t + timedelta(minutes=5), t + timedelta(minutes=65)),
        (t - timedelta(hours=1), t + timedelta(hours=2)),
    ]
    for start, end in periods:
        data = await _timeline(client, {"from": _iso_ms(start), "to": _iso_ms(end), "sources": ["alert"]})
        for item in data["items"]:
            assert item["entity_name"] == expected[item["ref"]["alert_history_id"]], (start, end)
