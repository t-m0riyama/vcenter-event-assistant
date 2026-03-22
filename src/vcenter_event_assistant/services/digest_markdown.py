"""集約コンテキストから LLM なしの Markdown ダイジェストを生成する。"""

from __future__ import annotations

from datetime import datetime, timezone

from vcenter_event_assistant.services.digest_context import DigestContext

# 要注意イベント一覧の最大行数（プロンプト長・可読性のため）
_MAX_TOP_NOTABLE_EVENTS_IN_MARKDOWN = 20


def _fmt_ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_template_digest(ctx: DigestContext, *, title: str) -> str:
    """``DigestContext`` から表・箇条書き中心の Markdown を組み立てる（LLM 不要）。"""
    lines: list[str] = [
        f"# {title}",
        "",
        f"- 集計期間（UTC）: `{_fmt_ts(ctx.from_utc)}` 〜 `{_fmt_ts(ctx.to_utc)}`（半開区間 `[from, to)`）",
        f"- 登録 vCenter 数: {ctx.vcenter_count}",
        f"- イベント総数: {ctx.total_events}",
        f"- 要注意（notable_score ≥ 40）件数: {ctx.notable_events_count}",
        "",
        "## 上位イベント種別（件数順）",
        "",
        "| 種別 | 件数 | max notable |",
        "|------|------|-------------|",
    ]
    for b in ctx.top_event_types:
        lines.append(f"| `{b.event_type}` | {b.event_count} | {b.max_notable_score} |")
    if not ctx.top_event_types:
        lines.append("| （なし） | | |")

    lines.extend(["", "## 要注意イベント（スコア上位）", ""])
    top_slice = ctx.top_notable_events[:_MAX_TOP_NOTABLE_EVENTS_IN_MARKDOWN]
    for ev in top_slice:
        ent = ev.entity_name or "—"
        lines.append(
            f"- `{ev.event_type}` score={ev.notable_score} at `{_fmt_ts(ev.occurred_at)}` entity=`{ent}` — {ev.message[:200]}"
        )
    if not top_slice:
        lines.append("- （該当なし）")
    if len(ctx.top_notable_events) > _MAX_TOP_NOTABLE_EVENTS_IN_MARKDOWN:
        lines.append(
            f"\n（他 {len(ctx.top_notable_events) - _MAX_TOP_NOTABLE_EVENTS_IN_MARKDOWN} 件は省略）"
        )

    lines.extend(["", "## ホスト CPU 利用率（ピーク上位）", "", "| vCenter | ホスト | % | サンプル時刻 |", "|---------|--------|---|--------------|"])
    for h in ctx.high_cpu_hosts:
        lines.append(f"| `{h.vcenter_id[:8]}…` | `{h.entity_name}` | {h.value:.1f} | `{_fmt_ts(h.sampled_at)}` |")
    if not ctx.high_cpu_hosts:
        lines.append("| | （なし） | | |")

    lines.extend(["", "## ホストメモリ利用率（ピーク上位）", "", "| vCenter | ホスト | % | サンプル時刻 |", "|---------|--------|---|--------------|"])
    for h in ctx.high_mem_hosts:
        lines.append(f"| `{h.vcenter_id[:8]}…` | `{h.entity_name}` | {h.value:.1f} | `{_fmt_ts(h.sampled_at)}` |")
    if not ctx.high_mem_hosts:
        lines.append("| | （なし） | | |")

    return "\n".join(lines) + "\n"
