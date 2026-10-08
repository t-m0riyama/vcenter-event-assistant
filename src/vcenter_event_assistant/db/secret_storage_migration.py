"""起動時の秘密情報（``EncryptedString`` の列）の平文→暗号化移行。"""

from __future__ import annotations

import logging

from sqlalchemy import text

from vcenter_event_assistant.db.encrypted_string import (
    ENC_PREFIX,
    encrypt_for_storage,
    is_encrypted_storage_value,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant.settings_binding import require_settings, resolve_vea_secret_key

logger = logging.getLogger(__name__)

# ``EncryptedString`` を使う列（テーブル、列、ログでの呼び名）。列を足したらここにも足す。
# SQL に埋め込むのはこの定数だけ（入力値は埋め込まない）
ENCRYPTED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("vcenters", "password", "vCenter password"),
    ("directory_configs", "bind_password", "directory bind password"),
    ("ssh_credentials", "private_key", "SSH private key"),
)


async def ensure_secret_storage(settings: Settings | None = None) -> None:
    """``VEA_SECRET_KEY`` に応じて秘密情報の保存形式を整える。

    - 鍵未設定: WARNING を出し平文のまま（後方互換）。
    - 鍵あり: DB 内の平文行を ``enc:`` 形式へ一括更新する。
    """
    s = settings or require_settings()
    secret = s.vea_secret_key if settings is not None else resolve_vea_secret_key()
    if not secret:
        encrypted: dict[str, int] = {}
        async with session_scope(settings=s) as session:
            for table, column, label in ENCRYPTED_COLUMNS:
                count = int(
                    (
                        await session.execute(
                            text(f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE :prefix"),
                            {"prefix": f"{ENC_PREFIX}%"},
                        )
                    ).scalar_one()
                    or 0
                )
                if count:
                    encrypted[label] = count
        if encrypted:
            logger.warning(
                "Found %d secret(s) stored encrypted (%s) but VEA_SECRET_KEY is not set; "
                "set VEA_SECRET_KEY or restore from backup.",
                sum(encrypted.values()),
                ", ".join(f"{label}: {count}" for label, count in encrypted.items()),
            )
        else:
            logger.warning(
                "VEA_SECRET_KEY is not set; passwords and keys (vCenter, directory bind, SSH) "
                "are stored in plaintext in the database."
            )
        return

    async with session_scope(settings=s) as session:
        for table, column, label in ENCRYPTED_COLUMNS:
            migrated = 0
            rows = (await session.execute(text(f"SELECT id, {column} FROM {table}"))).all()
            for row_id, stored in rows:
                if stored is None or is_encrypted_storage_value(stored):
                    continue
                await session.execute(
                    text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                    {"value": encrypt_for_storage(stored, secret), "id": row_id},
                )
                migrated += 1
            if migrated:
                logger.info("Encrypted %d legacy plaintext %s(s) at startup.", migrated, label)
