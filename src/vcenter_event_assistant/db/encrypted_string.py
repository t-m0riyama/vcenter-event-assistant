"""DB 保存用の Fernet 暗号化文字列 TypeDecorator。"""

from __future__ import annotations

import hashlib
import logging
from base64 import urlsafe_b64encode

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from vcenter_event_assistant.settings_binding import require_settings

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:"


class SecretKeyDecryptError(RuntimeError):
    """``VEA_SECRET_KEY`` で復号できない（鍵ローテーション失敗等）。"""


def fernet_key_bytes(secret: str) -> bytes:
    """任意の秘密文字列から Fernet 鍵（32 バイト url-safe base64）を導出する。"""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return urlsafe_b64encode(digest)


def encrypt_for_storage(plaintext: str, secret: str) -> str:
    """平文を ``enc:`` 付き DB 値にエンコードする。"""
    token = Fernet(fernet_key_bytes(secret)).encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"{ENC_PREFIX}{token}"


def decrypt_from_storage(stored: str, secret: str) -> str:
    """``enc:`` 付き DB 値を平文に戻す。失敗時は :class:`SecretKeyDecryptError`。"""
    if not stored.startswith(ENC_PREFIX):
        return stored
    ciphertext = stored[len(ENC_PREFIX) :]
    try:
        return Fernet(fernet_key_bytes(secret)).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        msg = (
            "Failed to decrypt vCenter password with VEA_SECRET_KEY. "
            "Restore the previous key or re-enter vCenter passwords in the UI."
        )
        raise SecretKeyDecryptError(msg) from exc


def is_encrypted_storage_value(value: str) -> bool:
    """DB 列値が暗号化形式か。"""
    return value.startswith(ENC_PREFIX)


class EncryptedString(TypeDecorator[str]):
    """``VEA_SECRET_KEY`` 設定時のみ Fernet 暗号化して DB に保存する文字列型。

    Python 側では常に平文。鍵未設定時は平文のまま読み書きする。
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int = 2048) -> None:
        super().__init__(length)
        self.impl = String(length)

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        secret = require_settings().vea_secret_key
        if not secret:
            return value
        if is_encrypted_storage_value(value):
            return value
        return encrypt_for_storage(value, secret)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        if not is_encrypted_storage_value(value):
            return value
        secret = require_settings().vea_secret_key
        if not secret:
            msg = (
                "Encrypted vCenter password found in database but VEA_SECRET_KEY is not set. "
                "Set VEA_SECRET_KEY or restore from backup."
            )
            raise SecretKeyDecryptError(msg)
        return decrypt_from_storage(value, secret)
