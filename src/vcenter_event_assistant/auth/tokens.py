"""セッショントークンの生成とハッシュ化。"""

from __future__ import annotations

import hashlib
import secrets


def new_session_token() -> str:
    """Cookie に入れる推測不能なトークン（256 bit）。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """DB に保存するのはこの SHA-256 だけにする。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
