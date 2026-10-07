"""ローカルユーザーのパスワードハッシュ（argon2id）とポリシー検証。"""

from __future__ import annotations

from dataclasses import dataclass

import anyio.to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# ユーザーが存在しない場合もハッシュ検証を 1 回走らせ、応答時間でユーザーの有無を推測させない。
_DUMMY_HASH = _hasher.hash("vea-dummy-password-for-timing")

PASSWORD_MAX_LENGTH = 256


class PasswordPolicyError(ValueError):
    """パスワードがポリシーを満たさない。"""


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    needs_rehash: bool = False


def validate_password_policy(password: str, *, min_length: int) -> None:
    """長さと文字種の最低限の検査。違反時は日本語メッセージ付きで例外。"""
    if len(password) < min_length:
        raise PasswordPolicyError(f"パスワードは {min_length} 文字以上にしてください。")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError(f"パスワードは {PASSWORD_MAX_LENGTH} 文字以下にしてください。")
    if password.strip() != password or not password.strip():
        raise PasswordPolicyError("パスワードの先頭・末尾に空白は使えません。")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in password):
        raise PasswordPolicyError("パスワードに制御文字は使えません。")


def hash_password_sync(password: str) -> str:
    return _hasher.hash(password)


async def hash_password(password: str) -> str:
    return await anyio.to_thread.run_sync(hash_password_sync, password)


def _verify_sync(password_hash: str | None, password: str) -> VerifyResult:
    if not password_hash:
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except VerificationError:
            pass
        return VerifyResult(ok=False)
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return VerifyResult(ok=False)
    return VerifyResult(ok=True, needs_rehash=_hasher.check_needs_rehash(password_hash))


async def verify_password(password_hash: str | None, password: str) -> VerifyResult:
    """``password_hash`` が ``None`` でもダミー検証を行い、常に同程度の時間をかける。"""
    return await anyio.to_thread.run_sync(_verify_sync, password_hash, password)
