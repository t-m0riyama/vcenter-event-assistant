"""起動時の vCenter パスワード平文→暗号化移行。"""

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


async def ensure_vcenter_password_storage(settings: Settings | None = None) -> None:
    """``VEA_SECRET_KEY`` に応じて vCenter パスワード保存形式を整える。

    - 鍵未設定: WARNING を出し平文のまま（後方互換）。
    - 鍵あり: DB 内の平文行を ``enc:`` 形式へ一括更新する。
    """
    s = settings or require_settings()
    secret = s.vea_secret_key if settings is not None else resolve_vea_secret_key()
    if not secret:
        async with session_scope(settings=s) as session:
            encrypted_count = int(
                (
                    await session.execute(
                        text("SELECT COUNT(*) FROM vcenters WHERE password LIKE :prefix"),
                        {"prefix": f"{ENC_PREFIX}%"},
                    )
                ).scalar_one()
                or 0
            )
        if encrypted_count:
            logger.warning(
                "Found %d vCenter password(s) stored encrypted but VEA_SECRET_KEY is not set; "
                "set VEA_SECRET_KEY or restore from backup.",
                encrypted_count,
            )
        else:
            logger.warning(
                "VEA_SECRET_KEY is not set; vCenter passwords are stored in plaintext in the database."
            )
        return

    migrated = 0
    async with session_scope(settings=s) as session:
        rows = (await session.execute(text("SELECT id, password FROM vcenters"))).all()
        for row_id, stored in rows:
            if stored is None or is_encrypted_storage_value(stored):
                continue
            await session.execute(
                text("UPDATE vcenters SET password = :password WHERE id = :id"),
                {"password": encrypt_for_storage(stored, secret), "id": row_id},
            )
            migrated += 1
    if migrated:
        logger.info("Encrypted %d legacy plaintext vCenter password(s) at startup.", migrated)
