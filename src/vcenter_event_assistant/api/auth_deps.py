"""認証・認可の FastAPI 依存関数。

- ``get_current_principal``: Cookie のセッションからログインユーザーを解決する（未ログインは 401）
- ``RequireViewer`` / ``RequireOperator`` / ``RequireAdmin``: route に付ける最低ロール（不足は 403）

``/api`` 配下の route は必ずいずれかの ``Require*`` を宣言すること（``tests/test_route_policy.py`` で検査）。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.auth.principal_header import (
    PRINCIPAL_STATE_KEY,
    SESSION_TOUCHED_STATE_KEY,
    principal_marker,
)
from vcenter_event_assistant.auth.roles import Role, role_at_least
from vcenter_event_assistant.auth.service import session_policy
from vcenter_event_assistant.auth.sessions import resolve_session
from vcenter_event_assistant.settings import Settings

AUTH_DISABLED_SOURCE = "disabled"
# 利用者の操作でない要求（画面の定期更新など）に付けるヘッダ。付いていればセッションの無操作期限を延ばさない。
# クライアントが自分のセッションを延ばさないと申告するだけなので、偽装されても害はない
BACKGROUND_REQUEST_HEADER = "x-vea-background"
# クライアントが画面に表示中の利用者とセッション（/api/auth/me の principal_id）。別のタブで別の利用者に
# ログインし直されて Cookie が替わっていたら、前の利用者の画面からの要求を実行せずに 409 で断る
EXPECTED_PRINCIPAL_HEADER = "x-vea-expected-principal"
# ヘッダを付けられないブラウザ自身の要求（CSV のダウンロードなど）は、同じ値をこのクエリで渡す
EXPECTED_PRINCIPAL_QUERY = "vea_expected_principal"
MIN_ROLE_ATTR = "__vea_min_role__"


@dataclass(frozen=True)
class Principal:
    """リクエストを行っている主体。"""

    username: str
    role: Role
    realm: str
    user_id: uuid.UUID | None = None
    display_name: str | None = None
    session_id: uuid.UUID | None = None

    @property
    def auth_disabled(self) -> bool:
        return self.realm == AUTH_DISABLED_SOURCE


# 認証無効時（従来動作）の暗黙の admin。
DISABLED_PRINCIPAL = Principal(username="anonymous", role=Role.ADMIN, realm=AUTH_DISABLED_SOURCE)


def session_cookie_name(settings: Settings) -> str:
    # ``__Host-`` 接頭辞は Secure・Path=/・Domain なしを強制するので、Secure のときだけ使う。
    return "__Host-vea_session" if settings.effective_session_cookie_secure else "vea_session"


def refuse_if_principal_switched(request: Request, marker: str) -> None:
    """応答に利用者を付け、クライアントが表示中の利用者（ヘッダ）と違えば 409 で断る。"""
    setattr(request.state, PRINCIPAL_STATE_KEY, marker)
    expected = request.headers.get(EXPECTED_PRINCIPAL_HEADER) or request.query_params.get(
        EXPECTED_PRINCIPAL_QUERY
    )
    if expected and expected != marker:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="別のタブで利用者が切り替わったため、操作を中止しました。画面を更新してから操作し直してください。",
        )


async def get_current_principal(
    request: Request,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> Principal:
    if not settings.auth_enabled:
        return DISABLED_PRINCIPAL
    token = request.cookies.get(session_cookie_name(settings))
    background = request.headers.get(BACKGROUND_REQUEST_HEADER) == "1"
    resolved = await resolve_session(db, token, session_policy(settings), touch=not background)
    if resolved is None:
        # 期限切れ・世代不一致で削除した行を確定させる（例外で get_session がロールバックするため）
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ログインが必要です。",
        )
    if resolved.touched:
        # 最終利用時刻の更新はルートの処理と切り離して確定させる。ルートが 4xx/5xx で失敗すると
        # get_session がロールバックし、操作したのに無操作期限が延びないままになるため
        await db.commit()
        # 応答に更新した印を付ける（クライアントは印のない応答では操作が伝わっていないとみなす）
        setattr(request.state, SESSION_TOUCHED_STATE_KEY, True)
    user = resolved.user
    # 応答に利用者とセッションの ID を付ける（PrincipalHeaderMiddleware）。クライアントが別アカウントへの
    # 切り替わりや、同じ利用者の再ログイン（ロール変更後など）に気づくため
    refuse_if_principal_switched(request, principal_marker(user.id, resolved.session.id))
    return Principal(
        username=user.username,
        role=Role(user.role),
        realm=user.realm_key,
        user_id=user.id,
        display_name=user.display_name,
        session_id=resolved.session.id,
    )


def require_role(role: Role) -> Callable[..., Awaitable[Principal]]:
    async def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not role_at_least(principal.role, role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="この操作を行う権限がありません。",
            )
        return principal

    setattr(dependency, MIN_ROLE_ATTR, role)
    dependency.__name__ = f"require_{role.value}"
    return dependency


require_viewer = require_role(Role.VIEWER)
require_operator = require_role(Role.OPERATOR)
require_admin = require_role(Role.ADMIN)

RequireViewer = Depends(require_viewer)
RequireOperator = Depends(require_operator)
RequireAdmin = Depends(require_admin)
