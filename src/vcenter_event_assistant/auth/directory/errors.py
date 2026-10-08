"""ディレクトリ認証のエラー。ログイン画面には出し分けず、監査ログの理由（``reason``）に使う。"""

from __future__ import annotations


class DirectoryError(Exception):
    """ディレクトリ認証の失敗。``reason`` は監査ログ用の短い識別子。"""

    reason = "directory_error"


class DirectoryConfigError(DirectoryError):
    """設定が不正・禁止されている（例: 証明書検証の無効化が全体で禁止されている）。"""

    reason = "directory_config_error"


class DirectoryUnavailable(DirectoryError):
    """接続・TLS・サービスアカウントの bind に失敗した（ユーザーのせいではない）。"""

    reason = "directory_unavailable"


class DirectoryTlsError(DirectoryUnavailable):
    """サーバ証明書を検証できなかった。"""

    reason = "directory_tls_error"


class DirectoryAuthFailed(DirectoryError):
    """ユーザーが見つからない・複数見つかった・パスワードが違う。"""

    reason = "directory_auth_failed"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        if reason:
            self.reason = reason


class DirectoryNoRole(DirectoryError):
    """どのグループの対応にも当てはまらない（ログインを許さない）。"""

    reason = "no_matching_group"
