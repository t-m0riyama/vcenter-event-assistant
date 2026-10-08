"""認証済みの応答に、そのリクエストの利用者を表すヘッダを付けるミドルウェア。

別のタブで別のアカウントにログインし直すと Cookie が替わり、このタブの API 要求も 401 にならずに
その利用者として成功する。画面が前の利用者のまま操作を続けないよう、クライアントは応答の
``X-VEA-Principal`` を表示中の利用者と照合する。値は利用者の ID とセッションの ID を組み合わせたもので、
本人にしか返らない。セッションの ID も含めるのは、管理者がロールを変えてセッションを失効させた後に
同じ利用者が別のウィンドウでログインし直した場合も、別の値になって照合のきっかけになるようにするため。
"""

from __future__ import annotations

import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

PRINCIPAL_HEADER = b"x-vea-principal"
# ``get_current_principal`` が request.state（= scope["state"]）に入れるキー
PRINCIPAL_STATE_KEY = "vea_principal_id"


def principal_marker(user_id: uuid.UUID, session_id: uuid.UUID) -> str:
    """``X-VEA-Principal`` と ``/api/auth/me`` の ``principal_id`` に入れる値。"""
    return f"{user_id}:{session_id}"


class PrincipalHeaderMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_principal(message: Message) -> None:
            if message["type"] == "http.response.start":
                principal_id = scope.get("state", {}).get(PRINCIPAL_STATE_KEY)
                if principal_id:
                    headers = list(message.get("headers", []))
                    headers.append((PRINCIPAL_HEADER, str(principal_id).encode("latin-1")))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_principal)
