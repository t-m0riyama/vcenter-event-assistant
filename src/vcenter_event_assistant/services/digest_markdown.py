"""Jinja2 テンプレートから Markdown ダイジェストをレンダリングする。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment

from vcenter_event_assistant.services.digest_context import DigestContext
from vcenter_event_assistant.settings import Settings

_logger = logging.getLogger(__name__)


def _strip_opt(s: str | None) -> str:
    return (s or "").strip()


def _load_template_source(settings: Settings) -> str:
    """spec「解決順（確定）」に従い UTF-8 でテンプレ全文を読む。"""
    path_opt = _strip_opt(settings.digest_template_path)
    if path_opt:
        p = Path(path_opt)
        if not p.is_file():
            msg = f"digest template path is not a readable file: {p}"
            raise FileNotFoundError(msg)
        return p.read_text(encoding="utf-8")

    dir_opt = _strip_opt(settings.digest_template_dir)
    if dir_opt:
        p = Path(dir_opt) / settings.digest_template_file
        if not p.is_file():
            msg = f"digest template under digest_template_dir is not a readable file: {p}"
            raise FileNotFoundError(msg)
        return p.read_text(encoding="utf-8")

    ref = resources.files("vcenter_event_assistant") / "templates" / "digest.md.j2"
    return ref.read_text(encoding="utf-8")


def _resolve_display_timezone(settings: Settings) -> tuple[ZoneInfo, str]:
    """表示用 ``ZoneInfo`` と、テンプレに渡すラベル（IANA 名）を返す。"""
    name = _strip_opt(settings.digest_display_timezone) or "UTC"
    if not name:
        return timezone.utc, "UTC"
    try:
        return ZoneInfo(name), name
    except KeyError:
        _logger.warning(
            "無効な DIGEST_DISPLAY_TIMEZONE=%r のため UTC にフォールバックします",
            name,
        )
        return timezone.utc, "UTC"


def _parse_to_utc(value: object) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    else:
        raise TypeError(f"fmt_ts は str または datetime を想定しています: {type(value)!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_ts_value(value: object, display_tz: ZoneInfo) -> str:
    dt_utc = _parse_to_utc(value)
    local = dt_utc.astimezone(display_tz)
    return local.isoformat(timespec="seconds")


def render_digest_markdown(ctx: DigestContext, *, kind: str, settings: Settings) -> str:
    """
    ``DigestContext`` を Jinja2 で Markdown にレンダリングする。

    Raises:
        OSError / jinja2 例外: テンプレ読込・構文・レンダリング失敗時（呼び出し側で ``DigestRecord.status=error`` にできる）。
    """
    source = _load_template_source(settings)
    display_tz, display_label = _resolve_display_timezone(settings)

    env = Environment(autoescape=False)
    env.filters["fmt_ts"] = lambda v: _format_ts_value(v, display_tz)
    tpl = env.from_string(source)
    ctx_dict: dict[str, Any] = ctx.model_dump(mode="json")
    return str(tpl.render(kind=kind, ctx=ctx_dict, display_timezone=display_label)) + "\n"
