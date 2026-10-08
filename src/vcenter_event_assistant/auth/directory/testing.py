"""ディレクトリの接続試験（管理画面の「接続試験」）。段階ごとに結果を返す。

1. connect: サーバに接続し、TLS を確立して、サービスアカウント（未設定なら匿名）で bind する
2. user_search: 試験用のユーザー名でユーザーを 1 件見つける（ユーザー名を指定したときだけ）
3. user_bind: そのユーザーとして bind する（パスワードを指定したときだけ）
4. groups: 所属グループを調べ、対応表から決まるロールを示す（ユーザー名を指定したときだけ）
"""

from __future__ import annotations

from dataclasses import dataclass

from vcenter_event_assistant.auth.directory import backend
from vcenter_event_assistant.auth.directory.connection import ConnectOptions
from vcenter_event_assistant.auth.directory.errors import DirectoryError
from vcenter_event_assistant.auth.directory.role_mapping import normalize_dn, resolve_role
from vcenter_event_assistant.auth.directory.spec import DirectorySpec


@dataclass(frozen=True)
class StageResult:
    stage: str
    ok: bool
    message: str


def run_test(
    spec: DirectorySpec,
    options: ConnectOptions,
    *,
    username: str | None = None,
    password: str | None = None,
) -> list[StageResult]:
    results: list[StageResult] = []
    tls_note = ""
    if spec.transport_security == "none":
        tls_note = "（暗号化なし）"
    elif not spec.tls_verify:
        tls_note = "（証明書検証: 無効）"
    try:
        conn = backend.service_connection(spec, options)
    except DirectoryError as exc:
        return [StageResult("connect", False, str(exc))]
    try:
        who = spec.bind_dn or "匿名"
        results.append(StageResult("connect", True, f"接続して {who} で bind しました{tls_note}。"))
        if not username:
            return results
        try:
            name = backend.clean_username(username)
            entry = backend.find_user(conn, spec, name)
        except DirectoryError as exc:
            results.append(StageResult("user_search", False, str(exc)))
            return results
        results.append(StageResult("user_search", True, f"ユーザーが見つかりました: {entry.dn}"))
        if password:
            try:
                backend.verify_user_password(spec, entry.dn, password, options)
            except DirectoryError as exc:
                results.append(StageResult("user_bind", False, str(exc)))
                return results
            results.append(StageResult("user_bind", True, "このユーザーとして bind できました。"))
        try:
            groups = backend.member_groups(conn, spec, entry, name)
        except DirectoryError as exc:
            results.append(StageResult("groups", False, str(exc)))
            return results
        role = resolve_role(groups, spec.mappings)
        matched = [label for label, _r in spec.mapping_labels if normalize_dn(label) in groups]
        if role is None:
            results.append(
                StageResult("groups", False, "対応表のどのグループにも属していないため、ログインできません。")
            )
        else:
            results.append(
                StageResult("groups", True, f"ロール {role.value} でログインできます（一致したグループ: {', '.join(matched)}）。")
            )
        return results
    finally:
        conn.unbind()
