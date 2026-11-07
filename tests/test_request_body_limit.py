"""HTTP 本文の受信境界を実際の ASGI アプリで検証する。"""

import json

import pytest
from starlette.datastructures import Headers
from starlette.types import Message

from vcenter_event_assistant.api import request_body_limit
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.settings import get_settings


async def _post(
    path: str,
    chunks: list[bytes],
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    root_path: str = "",
    content_type: bytes = b"application/json",
    csrf: bool = True,
) -> tuple[int, list[Message]]:
    received = 0
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal received
        assert received < len(chunks), "unexpected body read"
        body = chunks[received]
        received += 1
        return {
            "type": "http.request",
            "body": body,
            "more_body": received < len(chunks),
        }

    async def send(message: Message) -> None:
        sent.append(message)

    await create_app()(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "root_path": root_path,
            "query_string": b"",
            "headers": [
                (b"host", b"test"),
                (b"origin", b"http://test"),
                *([(b"x-requested-with", b"XMLHttpRequest")] if csrf else []),
                (b"content-type", content_type),
                *(headers or []),
            ],
        },
        receive,
        send,
    )
    return received, sent


def _assert_413(sent: list[Message]) -> None:
    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert len(starts) == 1
    assert starts[0]["status"] == 413
    headers = Headers(raw=starts[0]["headers"])
    assert headers["access-control-allow-origin"] == "http://test"
    assert headers["x-content-type-options"] == "nosniff"
    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    assert int(headers["content-length"]) == len(body)
    assert json.loads(body) == {"detail": "Request body too large"}


@pytest.fixture(autouse=True)
def _allow_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://test")
    get_settings.cache_clear()


@pytest.mark.parametrize("root_path", ["", "/vea"])
@pytest.mark.parametrize(
    ("chunks", "declared", "read_count"),
    [
        ([], b"17", 0),
        ([b" " * 10, b" " * 7, b"unread"], None, 2),
        ([b" " * 10, b" " * 7, b"unread"], b"16", 2),
    ],
)
async def test_login_overflow(
    monkeypatch, root_path, chunks, declared, read_count
) -> None:
    monkeypatch.setattr(request_body_limit, "LOGIN_BODY_LIMIT", 16)
    headers = [(b"content-length", declared)] if declared is not None else None
    received, sent = await _post(
        f"{root_path}/api/auth/login",
        chunks,
        headers=headers,
        root_path=root_path,
    )
    assert received == read_count
    _assert_413(sent)


async def test_login_body_at_limit_reaches_parser(monkeypatch) -> None:
    monkeypatch.setattr(request_body_limit, "LOGIN_BODY_LIMIT", 16)
    received, sent = await _post("/api/auth/login", [b"{}" + b" " * 14])
    assert received == 1
    assert sent[0]["status"] == 422


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/preview"])
@pytest.mark.parametrize(("role", "status"), [(None, 401), ("viewer", 403)])
async def test_chat_denies_before_receiving_body(path, role, status, make_login_cookie) -> None:
    headers = []
    if role is not None:
        name, token = await make_login_cookie(role)
        headers.append((b"cookie", f"{name}={token}".encode()))
    received, sent = await _post(path, [], headers=headers)
    assert received == 0
    assert sent[0]["status"] == status


@pytest.mark.parametrize("auth_enabled", [False, True])
async def test_chat_reads_body_for_operator_or_auth_disabled(
    monkeypatch, auth_enabled, make_login_cookie
) -> None:
    headers = []
    if auth_enabled:
        name, token = await make_login_cookie("operator")
        headers.append((b"cookie", f"{name}={token}".encode()))
    else:
        monkeypatch.setenv("VEA_AUTH_ENABLED", "false")
        get_settings.cache_clear()
        headers.append((b"x-vea-expected-principal", b"auth-disabled"))
    received, sent = await _post("/api/chat", [b"{}"], headers=headers)
    assert received == 1
    assert sent[0]["status"] == 422


async def test_chat_subpath_uses_chat_body_limit() -> None:
    headers = [
        (b"content-length", str(request_body_limit.DEFAULT_BODY_LIMIT + 1).encode())
    ]
    received, sent = await _post(
        "/vea/api/chat/preview", [], headers=headers, root_path="/vea"
    )
    assert received == 0
    assert sent[0]["status"] == 401


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/preview"])
@pytest.mark.parametrize("auth_enabled", [False, True])
async def test_chat_rejects_auth_mode_switch_before_receiving_body(
    monkeypatch, auth_enabled, path, make_login_cookie
) -> None:
    if auth_enabled:
        name, token = await make_login_cookie("operator")
        headers = [(b"cookie", f"{name}={token}".encode()), (b"x-vea-expected-principal", b"auth-disabled")]
    else:
        monkeypatch.setenv("VEA_AUTH_ENABLED", "false")
        get_settings.cache_clear()
        headers = [(b"x-vea-expected-principal", b"user:session")]
    received, sent = await _post(path, [], headers=headers)
    assert received == 0
    assert sent[0]["status"] == 409
    response_headers = Headers(raw=sent[0]["headers"])
    if auth_enabled:
        assert response_headers["x-vea-principal"] != "auth-disabled"
    else:
        assert response_headers["x-vea-principal"] == "auth-disabled"


async def test_rejection_that_does_not_read_body_keeps_its_status() -> None:
    received, sent = await _post("/api/auth/login", [], csrf=False)
    assert received == 0
    assert sent[0]["status"] == 403


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("root_path", ["", "/vea"])
async def test_multipart_overflow_closes_partial_file(
    monkeypatch, authenticated, root_path, make_login_cookie
) -> None:
    from starlette import formparsers

    files = []
    spool = formparsers.SpooledTemporaryFile

    def track_spool(*args, **kwargs):
        file = spool(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", track_spool)
    monkeypatch.setattr(request_body_limit, "UPLOAD_BODY_LIMIT", 256)
    headers = []
    if authenticated:
        name, token = await make_login_cookie("admin")
        headers.append((b"cookie", f"{name}={token}".encode()))
    received, sent = await _post(
        f"{root_path}/api/plugins/installed/upload",
        [
            b'--test\r\nContent-Disposition: form-data; name="file"; filename="pkg.whl"\r\n\r\nabc',
            b"x" * 256,
            b"\r\n--test--\r\n",
        ],
        headers=headers,
        root_path=root_path,
        content_type=b"multipart/form-data; boundary=test",
    )
    assert received == 2
    assert len(files) == 1
    assert files[0].closed
    _assert_413(sent)


async def test_malformed_multipart_stays_400() -> None:
    _, sent = await _post(
        "/api/plugins/installed/upload",
        [],
        content_type=b"multipart/form-data",
    )
    assert sent[0]["status"] == 400


async def test_urlencoded_overflow_returns_413(monkeypatch) -> None:
    monkeypatch.setattr(request_body_limit, "UPLOAD_BODY_LIMIT", 16)
    received, sent = await _post(
        "/api/plugins/installed/upload",
        [b"file=" + b"x" * 12],
        content_type=b"application/x-www-form-urlencoded",
    )
    assert received == 1
    _assert_413(sent)
