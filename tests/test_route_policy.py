"""全 API route が最低ロールを宣言していることと、その対応表のスナップショット。

route を追加・変更したらこの表も更新すること（意図しない無認可 route を防ぐ）。
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.routing import APIRoute

from vcenter_event_assistant.api.auth_deps import MIN_ROLE_ATTR, get_current_principal
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.plugins.registry import (
    build_collector_registry,
    set_collector_registry,
)
from vcenter_event_assistant.settings import Settings, get_settings

PUBLIC = "public"
AUTHENTICATED = "authenticated"
VIEWER, OPERATOR, ADMIN = Role.VIEWER.value, Role.OPERATOR.value, Role.ADMIN.value

EXPECTED: dict[tuple[str, str], str] = {
    # auth（保護対象 router の外）
    ("GET", "/api/auth/realms"): PUBLIC,
    ("POST", "/api/auth/login"): PUBLIC,
    ("POST", "/api/auth/logout"): PUBLIC,
    ("GET", "/api/auth/me"): AUTHENTICATED,
    ("POST", "/api/auth/me/password"): AUTHENTICATED,
    ("GET", "/api/auth/users"): ADMIN,
    ("POST", "/api/auth/users"): ADMIN,
    ("PATCH", "/api/auth/users/{user_id}"): ADMIN,
    ("DELETE", "/api/auth/users/{user_id}"): ADMIN,
    ("POST", "/api/auth/users/{user_id}/password"): ADMIN,
    ("POST", "/api/auth/users/{user_id}/sessions/revoke"): ADMIN,
    ("POST", "/api/auth/users/{user_id}/unlock"): ADMIN,
    # config / ルール類
    ("GET", "/api/config"): VIEWER,
    ("GET", "/api/event-score-rules"): VIEWER,
    ("POST", "/api/event-score-rules"): ADMIN,
    ("POST", "/api/event-score-rules/import"): ADMIN,
    ("PATCH", "/api/event-score-rules/{rule_id}"): ADMIN,
    ("DELETE", "/api/event-score-rules/{rule_id}"): ADMIN,
    ("GET", "/api/event-type-guides"): VIEWER,
    ("POST", "/api/event-type-guides"): ADMIN,
    ("POST", "/api/event-type-guides/import"): ADMIN,
    ("PATCH", "/api/event-type-guides/{guide_id}"): ADMIN,
    ("DELETE", "/api/event-type-guides/{guide_id}"): ADMIN,
    # vCenter
    ("GET", "/api/vcenters"): VIEWER,
    ("POST", "/api/vcenters"): ADMIN,
    ("GET", "/api/vcenters/{vcenter_id}"): VIEWER,
    ("PATCH", "/api/vcenters/{vcenter_id}"): ADMIN,
    ("DELETE", "/api/vcenters/{vcenter_id}"): ADMIN,
    ("GET", "/api/vcenters/{vcenter_id}/test"): OPERATOR,
    # 参照系
    ("GET", "/api/events/event-types"): VIEWER,
    ("GET", "/api/events/rate-series"): VIEWER,
    ("GET", "/api/events"): VIEWER,
    ("PATCH", "/api/events/{event_id}"): OPERATOR,
    ("GET", "/api/logs"): VIEWER,
    ("GET", "/api/logs/export.csv"): VIEWER,
    ("GET", "/api/metrics/catalog"): VIEWER,
    ("GET", "/api/metrics/keys"): VIEWER,
    ("GET", "/api/metrics"): VIEWER,
    ("GET", "/api/dashboard/attention"): VIEWER,
    ("GET", "/api/dashboard/summary"): VIEWER,
    ("GET", "/api/digests"): VIEWER,
    ("GET", "/api/digests/{digest_id}"): VIEWER,
    ("POST", "/api/digests/run"): OPERATOR,
    ("POST", "/api/chat"): OPERATOR,
    ("POST", "/api/chat/preview"): OPERATOR,
    ("POST", "/api/incident-timeline"): VIEWER,
    ("POST", "/api/incident-timeline/snapshots/manual"): OPERATOR,
    ("GET", "/api/incident-timeline/snapshots/manual"): VIEWER,
    # アラート
    ("GET", "/api/alerts/rules"): VIEWER,
    ("POST", "/api/alerts/rules"): ADMIN,
    ("PATCH", "/api/alerts/rules/{rule_id}"): ADMIN,
    ("DELETE", "/api/alerts/rules/{rule_id}"): ADMIN,
    ("POST", "/api/alerts/rules/import"): ADMIN,
    ("GET", "/api/alerts/history"): VIEWER,
    ("POST", "/api/alerts/states/resolve"): OPERATOR,
    ("DELETE", "/api/alerts/history/{history_id}"): ADMIN,
    ("POST", "/api/ingest/run"): OPERATOR,
    # プラグイン
    ("GET", "/api/plugins/collectors"): VIEWER,
    ("PATCH", "/api/plugins/collectors/{plugin_id}"): ADMIN,
    ("POST", "/api/plugins/collectors/reload"): ADMIN,
    ("GET", "/api/plugins/installed"): ADMIN,
    ("POST", "/api/plugins/installed"): ADMIN,
    ("POST", "/api/plugins/installed/upload"): ADMIN,
    ("DELETE", "/api/plugins/installed/{distribution}"): ADMIN,
    ("GET", "/api/plugins/collectors/{plugin_id}/configuration"): ADMIN,
    ("PUT", "/api/plugins/collectors/{plugin_id}/draft"): ADMIN,
    ("POST", "/api/plugins/collectors/{plugin_id}/draft/import"): ADMIN,
    ("POST", "/api/plugins/collectors/{plugin_id}/draft/validate"): ADMIN,
    ("POST", "/api/plugins/collectors/{plugin_id}/draft/actions/{action}"): ADMIN,
    ("POST", "/api/plugins/collectors/{plugin_id}/draft/apply"): ADMIN,
    ("GET", "/api/plugins/ssh/credentials"): ADMIN,
    ("POST", "/api/plugins/ssh/credentials"): ADMIN,
    ("GET", "/api/plugins/ssh/credentials/{identifier}/public-key"): ADMIN,
    ("DELETE", "/api/plugins/ssh/credentials/{identifier}"): ADMIN,
    ("GET", "/api/plugins/ssh/connections"): ADMIN,
    ("POST", "/api/plugins/ssh/connections"): ADMIN,
    ("PUT", "/api/plugins/ssh/connections/{identifier}"): ADMIN,
    ("POST", "/api/plugins/ssh/connections/{identifier}/host-key"): ADMIN,
    ("POST", "/api/plugins/ssh/connections/{identifier}/approve"): ADMIN,
    ("GET", "/api/plugins/vcenters/{identifier}/hosts"): ADMIN,
}


def _declared_policy(route: APIRoute) -> str:
    roles = [
        getattr(dep.dependency, MIN_ROLE_ATTR)
        for dep in route.dependencies
        if hasattr(dep.dependency, MIN_ROLE_ATTR)
    ]
    if roles:
        return max(roles, key=lambda r: r.rank).value
    if any(dep.call is get_current_principal for dep in route.dependant.dependencies):
        return AUTHENTICATED
    return PUBLIC


def _api_routes() -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for route in create_app().routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api"):
            continue
        for method in route.methods:
            found[(method, route.path)] = _declared_policy(route)
    return found


def test_route_policy_matches_snapshot() -> None:
    assert _api_routes() == EXPECTED


def test_protected_router_requires_login_for_every_route() -> None:
    for route in create_app().routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api"):
            continue
        if route.path.startswith("/api/auth"):
            continue
        calls = [dep.dependency for dep in route.dependencies]
        assert get_current_principal in calls, route.path


# ---- 実リクエストでの強制確認 -------------------------------------------------

_ROLE_ORDER = [VIEWER, OPERATOR, ADMIN]
_UUID_PARAMS = {"vcenter_id", "identifier", "user_id"}
_TEXT_PARAMS = {"plugin_id", "distribution", "action"}
# 必要ロールでの実行は副作用（取り込み・LLM 呼び出し・プラグイン再読込）が大きいので省く
_SKIP_SUFFICIENT = {
    ("POST", "/api/ingest/run"),
    ("POST", "/api/digests/run"),
    ("POST", "/api/plugins/collectors/reload"),
}


def _concrete(path: str) -> str:
    def fill(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in _UUID_PARAMS:
            return str(uuid.uuid4())
        if name in _TEXT_PARAMS:
            return "no-such-thing"
        return "999999"

    return re.sub(r"\{([^}]+)\}", fill, path)


async def _call(client, method: str, path: str):
    kwargs = {} if method in ("GET", "DELETE") else {"json": {}}
    return await client.request(method, _concrete(path), **kwargs)


_PROTECTED = sorted((k, v) for k, v in EXPECTED.items() if v != PUBLIC)


@pytest.fixture
def _plugin_management_enabled(monkeypatch: pytest.MonkeyPatch, no_external_collectors):
    # 無効時は存在を伏せる 404 になり、ロール判定を確認できないため有効にする
    monkeypatch.setenv("VEA_PLUGIN_MANAGEMENT_ENABLED", "1")
    get_settings.cache_clear()
    # lifespan を走らせないので、コレクタのレジストリを自前で用意する
    set_collector_registry(build_collector_registry(Settings()))
    yield
    set_collector_registry(None)


@pytest.mark.usefixtures("_plugin_management_enabled")
@pytest.mark.parametrize(("key", "required"), _PROTECTED, ids=lambda x: str(x))
async def test_route_enforces_role(open_client, key: tuple[str, str], required: str) -> None:
    method, path = key
    async with open_client(None) as anon:
        assert (await _call(anon, method, path)).status_code == 401

    if required == AUTHENTICATED:
        return

    for lower in _ROLE_ORDER[: _ROLE_ORDER.index(required)]:
        async with open_client(lower, username=f"u-{lower}") as c:
            resp = await _call(c, method, path)
            assert resp.status_code == 403, (lower, resp.text)

    if key in _SKIP_SUFFICIENT:
        return
    async with open_client(required, username=f"u-{required}") as c:
        resp = await _call(c, method, path)
        assert resp.status_code not in (401, 403), resp.text


_MANAGEMENT_GATED = sorted(
    k
    for k in EXPECTED
    if k[1].startswith("/api/plugins/") and k != ("GET", "/api/plugins/collectors")
)


@pytest.mark.parametrize("key", _MANAGEMENT_GATED, ids=lambda x: str(x))
@pytest.mark.parametrize("role", [None, VIEWER, ADMIN])
async def test_disabled_plugin_management_is_hidden_before_auth(
    open_client, key: tuple[str, str], role: str | None
) -> None:
    """管理が無効なら、未ログインでもロール不足でも 401/403 ではなく 404 を返す（存在を伏せる）。"""
    method, path = key
    async with open_client(role, username=f"hidden-{role}") as c:
        resp = await _call(c, method, path)
    assert resp.status_code == 404, resp.text
