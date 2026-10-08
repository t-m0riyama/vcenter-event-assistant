"""ディレクトリへの接続と bind（同期。別スレッドで呼ぶ）。

- ``server_uris`` を順に試し、接続できない・TLS を確立できないサーバは飛ばして次を使う
- TLS は既定でサーバ証明書とホスト名を検証する（``ca_cert_pem`` があればそれを信頼する CA にする）
- StartTLS に失敗したら平文のまま続けずに中止する
- bind が拒否された（資格情報の誤り）ときは別のサーバを試さない

テストは ``connect`` を差し替えて ldap3 の MOCK_SYNC の接続を返す（呼び出し側はモジュール経由で呼ぶ）。
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass

from ldap3 import ANONYMOUS, NONE, SIMPLE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from sqlalchemy import ColumnElement, and_, or_, true

from vcenter_event_assistant.auth.directory.errors import (
    DirectoryConfigError,
    DirectoryError,
    DirectoryTlsError,
    DirectoryUnavailable,
)
from vcenter_event_assistant.auth.directory.spec import DirectorySpec
from vcenter_event_assistant.db.models import DirectoryConfig


@dataclass(frozen=True)
class ConnectOptions:
    """アプリ全体の設定のうち、接続に効くもの。"""

    # VEA_DIRECTORY_ALLOW_INSECURE_TLS。false なら tls_verify=false の設定では接続しない
    allow_insecure_tls: bool = True
    # 本番（APP_ENV=production）では暗号化しない接続（transport_security=none）を使わない
    production: bool = False


class BindRejected(DirectoryError):
    """サーバに接続できたが、bind が拒否された（DN またはパスワードの誤り）。"""

    reason = "bind_rejected"


def check_security(spec: DirectorySpec, options: ConnectOptions) -> None:
    """接続してよい設定か。禁止されていれば ``DirectoryConfigError``。"""
    if spec.transport_security == "none" and options.production:
        raise DirectoryConfigError("本番環境では暗号化しない接続（transport_security=none）は使えません。")
    if spec.transport_security != "none" and not spec.tls_verify and not options.allow_insecure_tls:
        raise DirectoryConfigError(
            "証明書を検証しない接続は禁止されています（VEA_DIRECTORY_ALLOW_INSECURE_TLS=false）。"
            "CA 証明書を設定して証明書の検証を有効にしてください。"
        )


def allowed_by_security(options: ConnectOptions) -> ColumnElement[bool]:
    """``check_security`` で拒否されないディレクトリの条件（SQL）。両者は同じ規則を保つ。"""
    conditions: list[ColumnElement[bool]] = []
    if options.production:
        conditions.append(DirectoryConfig.transport_security != "none")
    if not options.allow_insecure_tls:
        conditions.append(
            or_(DirectoryConfig.transport_security == "none", DirectoryConfig.tls_verify.is_(True))
        )
    return and_(true(), *conditions)


def build_tls(spec: DirectorySpec) -> Tls | None:
    """LDAPS / StartTLS 用の TLS 設定。``transport_security=none`` なら ``None``。"""
    if spec.transport_security == "none":
        return None
    if not spec.tls_verify:
        return Tls(validate=ssl.CERT_NONE)
    return Tls(
        validate=ssl.CERT_REQUIRED,
        # 指定がなければ OS の CA ストアを使う
        ca_certs_data=spec.ca_cert_pem or None,
    )


def _server(spec: DirectorySpec, uri: str) -> Server:
    return Server(
        uri,
        use_ssl=spec.transport_security == "ldaps",
        tls=build_tls(spec),
        connect_timeout=spec.timeout_seconds,
        get_info=NONE,
    )


def describe_tls_failure(exc: BaseException) -> str:
    """証明書の検証に失敗した理由を、利用者が対処できる言葉にする。"""
    text = str(exc)
    lowered = text.lower()
    if "expired" in lowered:
        cause = "サーバ証明書の有効期限が切れています"
    elif "hostname" in lowered or "doesn't match" in lowered or "not match" in lowered:
        cause = "サーバ証明書のホスト名が接続先と一致しません"
    elif "self signed" in lowered or "self-signed" in lowered or "unable to get local issuer" in lowered:
        cause = "サーバ証明書の発行元（CA）を信頼できません"
    else:
        cause = "サーバ証明書を検証できません"
    return f"{cause}。CA 証明書を設定するか、証明書の検証を無効にしてください（{text[:200]}）"


def _is_tls_failure(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, ssl.SSLError) or "certificate" in text or "ssl" in text or "tls" in text


def connect(
    spec: DirectorySpec,
    *,
    user: str | None,
    password: str | None,
    options: ConnectOptions,
) -> Connection:
    """bind 済みの接続を返す。``user`` が ``None`` なら匿名で bind する。

    失敗したら ``DirectoryConfigError`` / ``DirectoryTlsError`` / ``DirectoryUnavailable`` /
    ``BindRejected`` を投げる。
    """
    check_security(spec, options)
    if not spec.server_uris:
        raise DirectoryConfigError("接続先のサーバが設定されていません。")
    if user is not None and not password:
        # 空のパスワードは「認証なしの bind」として成功してしまうため送らない
        raise BindRejected("パスワードが空です。")

    last_error: DirectoryError | None = None
    for uri in spec.server_uris:
        conn = Connection(
            _server(spec, uri),
            user=user,
            password=password,
            authentication=SIMPLE if user is not None else ANONYMOUS,
            receive_timeout=spec.timeout_seconds,
            auto_referrals=False,
            read_only=True,
            raise_exceptions=False,
        )
        try:
            conn.open()
            if spec.transport_security == "starttls" and not conn.start_tls():
                raise DirectoryTlsError(f"{uri}: StartTLS を開始できません（{conn.result}）")
        except DirectoryError as exc:
            last_error = exc
            conn.unbind()
            continue
        except (LDAPException, OSError) as exc:
            conn.unbind()
            if spec.transport_security != "none" and _is_tls_failure(exc):
                last_error = DirectoryTlsError(f"{uri}: {describe_tls_failure(exc)}")
            else:
                last_error = DirectoryUnavailable(f"{uri}: 接続できません（{str(exc)[:200]}）")
            continue
        try:
            bound = conn.bind()
        except (LDAPException, OSError) as exc:
            conn.unbind()
            last_error = DirectoryUnavailable(f"{uri}: bind の途中で失敗しました（{str(exc)[:200]}）")
            continue
        if bound:
            return conn
        result = conn.result or {}
        conn.unbind()
        if result.get("description") == "invalidCredentials":
            raise BindRejected(f"{uri}: 資格情報が正しくありません。")
        last_error = DirectoryUnavailable(f"{uri}: bind に失敗しました（{result.get('description')}）")
    assert last_error is not None
    raise last_error
