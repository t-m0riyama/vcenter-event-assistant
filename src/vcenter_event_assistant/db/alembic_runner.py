"""Alembic をアプリ起動時（async コンテキスト）から実行するヘルパ。"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from vcenter_event_assistant.settings import Settings, get_settings

ALEMBIC_HEAD = "k4l5m6n7o8p9"

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class LegacySchemaStampError(RuntimeError):
    """旧 DB の stamp 対象リビジョンを安全に判定できない。"""


def alembic_config(*, settings: Settings | None = None) -> Config:
    """``DATABASE_URL`` を反映した Alembic 設定を返す。"""
    s = settings or get_settings()
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", s.database_url)
    return cfg


def _run_with_connection(sync_conn: object, cfg: Config, fn) -> None:
    cfg.attributes["connection"] = sync_conn
    cfg.attributes["skip_file_config"] = True
    fn(cfg)


async def get_applied_alembic_revision(engine: AsyncEngine) -> str | None:
    """``alembic_version.version_num`` を返す。テーブルが無ければ ``None``。"""

    def sync_read(sync_conn) -> str | None:
        insp = inspect(sync_conn)
        if not insp.has_table("alembic_version"):
            return None
        row = sync_conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
        if row is None:
            return None
        return str(row[0])

    async with engine.connect() as conn:
        return await conn.run_sync(sync_read)


async def infer_legacy_stamp_revision(engine: AsyncEngine) -> str | None:
    """``alembic_version`` 未作成 DB の stamp 先を推定する。

    Returns:
        空 DB のとき ``None``（stamp 不要で ``upgrade head`` のみ）。
        旧 DB のとき stamp 対象リビジョン ID。

    Raises:
        LegacySchemaStampError: 列の組み合わせが一意に決まらない。
    """

    def sync_infer(sync_conn) -> str | None:
        insp = inspect(sync_conn)
        if not insp.has_table("vcenters"):
            return ALEMBIC_HEAD

        def has_column(table: str, column: str) -> bool:
            if not insp.has_table(table):
                return False
            if sync_conn.dialect.name == "sqlite":
                res = sync_conn.execute(text(f"PRAGMA table_info({table})"))
                return column in [row[1] for row in res.fetchall()]
            cols = [c["name"] for c in insp.get_columns(table)]
            return column in cols

        has_user_comment = has_column("events", "user_comment")
        has_action_required = has_column("event_type_guides", "action_required")
        has_last_notified_at = has_column("alert_states", "last_notified_at")
        fingerprint = (has_user_comment, has_action_required, has_last_notified_at)

        mapping: dict[tuple[bool, bool, bool], str] = {
            (True, True, True): "k4l5m6n7o8p9",
            (True, True, False): "j3k4l5m6n7o8",
            (True, False, False): "b2c3d4e5f6a7",
            (False, False, False): "c4d27748ae50",
        }
        revision = mapping.get(fingerprint)
        if revision is None:
            msg = (
                "legacy DB schema fingerprint is ambiguous; "
                f"user_comment={has_user_comment}, "
                f"action_required={has_action_required}, "
                f"last_notified_at={has_last_notified_at}. "
                "Restore from backup and run manual alembic stamp, or contact support."
            )
            raise LegacySchemaStampError(msg)
        return revision

    async with engine.connect() as conn:
        return await conn.run_sync(sync_infer)


async def alembic_stamp(engine: AsyncEngine, revision: str, *, settings: Settings | None = None) -> None:
    """指定リビジョンで ``alembic_version`` を stamp する。"""
    cfg = alembic_config(settings=settings)

    async with engine.begin() as conn:

        def sync_stamp(sync_conn) -> None:
            _run_with_connection(sync_conn, cfg, lambda c: command.stamp(c, revision))

        await conn.run_sync(sync_stamp)


async def alembic_upgrade_head(engine: AsyncEngine, *, settings: Settings | None = None) -> None:
    """``upgrade head`` を実行する。"""
    cfg = alembic_config(settings=settings)

    async with engine.begin() as conn:

        def sync_upgrade(sync_conn) -> None:
            _run_with_connection(sync_conn, cfg, lambda c: command.upgrade(c, "head"))

        await conn.run_sync(sync_upgrade)
