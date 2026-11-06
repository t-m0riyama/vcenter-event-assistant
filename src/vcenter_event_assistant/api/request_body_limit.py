"""パーサーに渡す HTTP リクエスト本文のバイト数を制限する。"""

from fastapi.exception_handlers import http_exception_handler
from starlette._utils import get_route_path
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from vcenter_event_assistant.api.schemas.chat import (
    MAX_ATTACHMENT_IMAGE_BYTES,
    MAX_ATTACHMENT_TEXT_CHARS,
)
from vcenter_event_assistant.plugins.installer import MAX_UPLOAD_BYTES

MIB = 1024 * 1024
DEFAULT_BODY_LIMIT = 16 * MIB
LOGIN_BODY_LIMIT = 64 * 1024
UPLOAD_BODY_LIMIT = MAX_UPLOAD_BYTES + MIB
CHAT_ATTACHMENT_WIRE_BYTES = max(
    4 * ((MAX_ATTACHMENT_IMAGE_BYTES + 2) // 3),
    12 * MAX_ATTACHMENT_TEXT_CHARS,
)
TOO_LARGE = "Request body too large"


class _MultipartBodyTooLarge(MultiPartException):
    """Starlette に解析途中の一時ファイルを閉じさせる。"""


async def body_limit_http_exception_handler(
    request: Request, exc: Exception
) -> Response:
    assert isinstance(exc, HTTPException)
    # Request.form() は Starlette のバージョンによって明示的な cause を設定しない。
    if isinstance(exc.__cause__ or exc.__context__, _MultipartBodyTooLarge):
        exc = HTTPException(413, TOO_LARGE)
    return await http_exception_handler(request, exc)


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, chat_attachment_max_files: int) -> None:
        self.app = app
        self.chat_limit = (
            49 * MIB + chat_attachment_max_files * CHAT_ATTACHMENT_WIRE_BYTES
        )

    def _limit(self, scope: Scope) -> int:
        if scope["method"] == "POST":
            path = get_route_path(scope)
            if path == "/api/auth/login":
                return LOGIN_BODY_LIMIT
            if path == "/api/plugins/installed/upload":
                return UPLOAD_BODY_LIMIT
            if path in ("/api/chat", "/api/chat/preview"):
                return self.chat_limit
        return DEFAULT_BODY_LIMIT

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limit(scope)
        headers = Headers(scope=scope)
        maximum = str(limit)
        for value in headers.getlist("content-length"):
            # 巨大な桁数でも整数に変換せずに比較する。実際の受信量も別途検査する。
            digits = value.strip().lstrip("0")
            if (
                digits.isascii()
                and digits.isdecimal()
                and (
                    len(digits) > len(maximum)
                    or (len(digits) == len(maximum) and digits > maximum)
                )
            ):
                await JSONResponse({"detail": TOO_LARGE}, status_code=413)(
                    scope, receive, send
                )
                return

        # GET のストリーミング応答などは、応答開始後にも切断監視で receive を呼ぶ。
        if scope["method"] not in ("POST", "PUT", "PATCH", "DELETE"):
            await self.app(scope, receive, send)
            return

        received = 0
        media_type = headers.get("content-type", "").partition(";")[0].strip().lower()

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    if media_type == "multipart/form-data":
                        raise _MultipartBodyTooLarge(TOO_LARGE)
                    raise HTTPException(413, TOO_LARGE)
            return message

        await self.app(scope, limited_receive, send)
