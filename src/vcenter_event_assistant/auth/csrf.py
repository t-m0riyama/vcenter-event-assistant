"""Cookie 認証向けの CSRF 対策ミドルウェア（監査 M-14）。

``/api/*`` への状態変更リクエストに対し、

1. ``X-Requested-With: XMLHttpRequest`` を必須にする（フォーム送信や単純リクエストでは付けられない）
2. ``Origin`` があれば、自ホストか ``CORS_ORIGINS`` に含まれるものだけを許可する

を確認する。違反は 403。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER = "x-requested-with"
CSRF_HEADER_VALUE = "XMLHttpRequest"


class CsrfMiddleware:
    def __init__(self, app: ASGIApp, *, trusted_origins: Iterable[str] = ()) -> None:
        self.app = app
        self.trusted_origins = {
            o.rstrip("/").lower() for o in trusted_origins if o.strip()
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS:
            path: str = scope["path"]
            if path == "/api" or path.startswith("/api/"):
                reason = self._violation(scope)
                if reason is not None:
                    await _forbidden(send, reason)
                    return
        await self.app(scope, receive, send)

    def _violation(self, scope: Scope) -> str | None:
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        if headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
            return "missing_header"
        origin = headers.get("origin")
        if origin is None:
            return None
        if origin.rstrip("/").lower() in self.trusted_origins:
            return None
        host = headers.get("host", "").lower()
        if host and urlsplit(origin).netloc.lower() == host:
            return None
        return "origin_mismatch"


async def _forbidden(send: Send, reason: str) -> None:
    body = json.dumps(
        {
            "detail": "リクエストを検証できませんでした。画面を再読み込みしてください。",
            "code": f"csrf_{reason}",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
