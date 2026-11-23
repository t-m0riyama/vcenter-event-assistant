"""LLM 送信直前の識別子トークン化と応答の逆変換。"""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from vcenter_event_assistant.services.vcenter_labels import first_hostname_label_if_fqdn

if TYPE_CHECKING:
    from vcenter_event_assistant.services.chat.chat_incident_timeline import IncidentTimelinePayload

# 本文を置換する前に、JSON の識別子を登録する。
_COLLECT_KEYS = {
    "entity_name": "entity",
    "entity_moid": "moid",
    "user_name": "user",
    "username": "user",
    "vcenter_label": "vcenter",
}

# 文字列内 IPv4（簡易）
_IPV4_RE = re.compile(
    r"(?<![0-9])"
    r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)"
    r"(?:\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)){3}"
    r"(?![0-9])",
)

# pyVmomi の _GetMoId() はサーバーから受け取った文字列を返す。
# govmomi の simulator/registry.go の refValueMap を参照。VirtualApp は resgroup-v、StoragePod は group-p。
# Folder の group-/group-d/h/n/v/s、OpaqueNetwork の network-o、Alarm の alarm- は vCenter の表記に合わせる
# （Broadcom KB 415622, 426491, 417248, 450412, 434473, 383952）。
# govmomi の Registry.newReference はカウンターを 1 ずつ増やし、%d でゼロ埋めせず採番する。
_MOID_WORD = r"[A-Za-z0-9_-]"
_MOID_WORD_RE = re.compile(_MOID_WORD)
_MOID_PATTERN = (
    r"(?:(?:vm|host|datastore|dvportgroup|dvs|datacenter|snapshot|envbrowser|task|alarm)-"
    r"|network-o?|resgroup-v?|domain-[cs]|group-[dhnpsv]?)[1-9][0-9]*"
)
_MOID_RE = re.compile(rf"(?<!{_MOID_WORD}){_MOID_PATTERN}(?!{_MOID_WORD})")


class LlmAnonymizer:
    """
    カテゴリごとに連番トークンを発行し、同一 (category, value) には同一トークンを返す。
    """

    def __init__(self) -> None:
        self._next: dict[str, int] = defaultdict(int)
        self._pair_to_token: dict[tuple[str, str], str] = {}
        self._reverse: dict[str, str] = {}

    def token_for(self, category: str, value: str) -> str:
        """空文字はトークン化しない。"""
        if not value:
            return ""
        cat_key = category.strip().lower()
        if cat_key == "entity" and self.has_registered_moid(value):
            cat_key = "moid"
        cat_upper = cat_key.upper()
        pair = (cat_key, value)
        if pair in self._pair_to_token:
            return self._pair_to_token[pair]
        self._next[cat_upper] += 1
        n = self._next[cat_upper]
        tok = f"__LM_{cat_upper}_{n:03d}__"
        self._pair_to_token[pair] = tok
        self._reverse[tok] = value
        return tok

    def has_registered_moid(self, value: str) -> bool:
        """同じ文字列が moid として登録済みかどうか。"""
        return ("moid", value) in self._pair_to_token

    def share_token_with(self, category: str, alias: str, canonical: str) -> None:
        """
        ``alias`` を ``canonical`` と同一トークンに紐づける（``canonical`` は ``token_for`` 済み）。

        FQDN と第1ラベル（短縮ホスト名）を LLM から同一識別子として扱わせる。
        ``_reverse`` は更新しない（逆変換の代表は ``canonical``）。
        """
        if not alias or not canonical or alias == canonical:
            return
        cat_key = category.strip().lower()
        tok = self._pair_to_token.get((cat_key, canonical))
        if not tok:
            return
        self._pair_to_token[(cat_key, alias)] = tok

    @property
    def reverse_map(self) -> dict[str, str]:
        """トークン → 原文（逆変換用）。"""
        return dict(self._reverse)

    def registered_replacements(self) -> list[tuple[str, str, str]]:
        """(カテゴリ, 原文, トークン) の一覧。既知の形式の moid は正規表現でまとめて探す。"""
        return [
            (cat, orig, tok) for (cat, orig), tok in self._pair_to_token.items()
            if cat != "moid" or _MOID_RE.fullmatch(orig) is None
        ]


def strip_ipv4(text: str) -> str:
    """文字列中の IPv4 アドレスを除去する（WEB 検索クエリ等の外部送出前サニタイズ用）。"""
    return _IPV4_RE.sub("", text)


def deanonymize_text(text: str, reverse_map: dict[str, str]) -> str:
    """トークンを原文に戻す。トークン同士の部分一致を避けるため長いトークンから置換する。"""
    if not reverse_map:
        return text
    toks = sorted(reverse_map.keys(), key=len, reverse=True)
    out = text
    for tok in toks:
        out = out.replace(tok, reverse_map[tok])
    return out


def _append_extra_vcenter_pairs(
    pairs: list[tuple[str, str]],
    extra_vcenter_strings: Sequence[str] | None,
) -> None:
    """登録 vCenter 由来の文字列を収集リストに追加（``vcenter`` カテゴリ）。"""
    if not extra_vcenter_strings:
        return
    for s in extra_vcenter_strings:
        if s:
            pairs.append(("vcenter", s))


def _apply_entity_fqdn_short_aliases(
    a: LlmAnonymizer, pairs: list[tuple[str, str]]
) -> None:
    """
    FQDN の候補が一つなら短縮名をその別名にし、候補が複数なら専用トークンを発行する。

    ``pairs`` に対する ``token_for`` 完了後に呼ぶ。登録済みの短縮名はそのトークンを保持する。
    """
    entity_names = dict.fromkeys(value for category, value in pairs if category == "entity")
    candidates_by_short: dict[str, list[str]] = defaultdict(list)
    for name in entity_names:
        short = first_hostname_label_if_fqdn(name)
        if short and short not in entity_names and not a.has_registered_moid(short):
            candidates_by_short[short].append(name)
    for short, candidates in candidates_by_short.items():
        if len(candidates) == 1:
            a.share_token_with("entity", short, candidates[0])
        else:
            a.token_for("entity", short)


def _collect_pairs(obj: Any, acc: list[tuple[str, str]]) -> None:
    """ツリー内の識別子フィールドを先に列挙する。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v and k in _COLLECT_KEYS:
                acc.append((_COLLECT_KEYS[k], v))
            _collect_pairs(v, acc)
    elif isinstance(obj, list):
        for x in obj:
            _collect_pairs(x, acc)


def _register_pairs(pairs: list[tuple[str, str]]) -> LlmAnonymizer:
    a = LlmAnonymizer()
    # 名前の代わりに入った moid は、entity_moid と同じトークンに揃える。
    for category, value in pairs:
        if category == "moid":
            a.token_for(category, value)
    for category, value in pairs:
        if category != "moid":
            a.token_for(category, value)
    _apply_entity_fqdn_short_aliases(a, pairs)
    return a


def anonymize_plain_text(text: str, a: LlmAnonymizer) -> str:
    """IPv4、登録済みの原文、既知の形式の moid を置換する。生成済みトークンは再走査しない。"""
    if not text:
        return text
    # 原文の文字位置を確保し、IPv4、長い原文の順に重複しない置換範囲を集める。
    claimed = bytearray(len(text))
    replacements: list[tuple[int, int, str | None]] = []
    for match in _IPV4_RE.finditer(text):
        start, end = match.span()
        claimed[start:end] = b"\x01" * (end - start)
        replacements.append((start, end, a.token_for("ip", match.group(0))))

    candidates: list[tuple[str, str, str | None, int | None]] = [
        (category, original, token, None) for category, original, token in a.registered_replacements()
    ]
    candidates.extend(("moid", match[0], None, match.start()) for match in _MOID_RE.finditer(text))
    # 長い原文を優先する。同じ長さなら、先に並べた登録済みの候補を優先する。
    candidates.sort(key=lambda candidate: len(candidate[1]), reverse=True)
    for category, original, token, position in candidates:
        if position is not None:
            end = position + len(original)
            if claimed.find(b"\x01", position, end) == -1:
                claimed[position:end] = b"\x01" * len(original)
                replacements.append((position, end, None))
            continue
        if len(original) < 2:
            continue
        search_from = 0
        while (start := text.find(original, search_from)) != -1:
            end = start + len(original)
            if category == "moid" and (
                (start > 0 and _MOID_WORD_RE.match(text, start - 1))
                or _MOID_WORD_RE.match(text, end)
            ):
                search_from = start + 1
                continue
            overlap = claimed.find(b"\x01", start, end)
            if overlap != -1:
                # 同じ長さの候補は、重複位置から続く確保済み範囲の途中でも一致できない。
                search_from = claimed.find(b"\x00", overlap)
                if search_from == -1:
                    break
                continue
            claimed[start:end] = b"\x01" * len(original)
            replacements.append((start, end, token))
            search_from = end

    parts: list[str] = []
    previous_end = 0
    for start, end, token in sorted(replacements):
        if token is None:
            token = a.token_for("moid", text[start:end])
        parts.extend((text[previous_end:start], token))
        previous_end = end
    parts.append(text[previous_end:])
    return "".join(parts)


def _anonymize_node(obj: Any, a: LlmAnonymizer) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k == "message" and isinstance(v, str):
                out[k] = anonymize_plain_text(v, a)
            elif k in _COLLECT_KEYS and isinstance(v, str):
                out[k] = a.token_for(_COLLECT_KEYS[k], v)
            else:
                out[k] = _anonymize_node(v, a)
        return out
    if isinstance(obj, list):
        return [_anonymize_node(x, a) for x in obj]
    return copy.deepcopy(obj)


def anonymize_json_like(obj: Any) -> tuple[Any, dict[str, str]]:
    """
    JSON 互換オブジェクトを再帰的に匿名化する。

    先にツリー全体から識別子を収集して登録し、その後でフィールドと message の本文を匿名化する。
    """
    pairs: list[tuple[str, str]] = []
    _collect_pairs(obj, pairs)
    a = _register_pairs(pairs)
    out = _anonymize_node(obj, a)
    return out, a.reverse_map


def anonymize_for_llm(
    context_dict: dict[str, Any],
    template_markdown: str,
    *,
    extra_vcenter_strings: Sequence[str] | None = None,
) -> tuple[dict[str, Any], str, dict[str, str]]:
    """
    ダイジェスト用: 集約 JSON とテンプレ Markdown を同一 ``LlmAnonymizer`` で匿名化する。

    ``extra_vcenter_strings`` に DB 登録済み vCenter の表示名・接続 host 等を渡すと、
    JSON に無い文字列も Markdown からトークン化する。
    """
    pairs: list[tuple[str, str]] = []
    _collect_pairs(context_dict, pairs)
    _append_extra_vcenter_pairs(pairs, extra_vcenter_strings)
    a = _register_pairs(pairs)
    ctx_out = _anonymize_node(context_dict, a)
    md_out = anonymize_plain_text(template_markdown, a)
    return ctx_out, md_out, a.reverse_map


def anonymize_chat_for_llm(
    payload: dict[str, Any],
    message_contents: list[str],
    *,
    extra_vcenter_strings: Sequence[str] | None = None,
    attachment_texts: Sequence[str] | None = None,
    attachment_filenames: Sequence[str] | None = None,
    incident_timeline: IncidentTimelinePayload | None = None,
) -> tuple[dict[str, Any], list[str], list[str], list[str], dict[str, str]]:
    """
    チャット用: マージ済みペイロード・会話本文・テキスト添付を同一 ``LlmAnonymizer`` で匿名化する。

    ``extra_vcenter_strings`` により登録済み vCenter 名を会話本文からもトークン化する。
    ``attachment_texts`` と ``attachment_filenames`` はテキスト添付の本文とファイル名。
    会話と同じトークン体系で処理する（画像は匿名化できない）。
    ``incident_timeline`` のメトリクスタイトルは、送信用の JSON でホスト名の部分だけを置換する。

    Returns:
        (payload, message_contents, attachment_texts, attachment_filenames, reverse_map)
    """
    pairs: list[tuple[str, str]] = []
    _collect_pairs(payload, pairs)
    timeline_json = None
    metric_titles: list[tuple[dict[str, Any], str, slice]] = []
    if incident_timeline is not None:
        timeline_json = incident_timeline.model_dump(mode="json")
        for column, column_json in zip(incident_timeline.columns, timeline_json["columns"], strict=True):
            for key, items in (("items", column.items), ("visible_items", column.visible_items)):
                for item, item_json in zip(items, column_json[key], strict=True):
                    if item.metric_host is not None:
                        host, span = item.metric_host
                        pairs.append(("entity", host))
                        metric_titles.append((item_json, host, span))
    _append_extra_vcenter_pairs(pairs, extra_vcenter_strings)
    a = _register_pairs(pairs)
    out_payload = _anonymize_node(payload, a)
    if timeline_json is not None:
        for item_json, host, span in metric_titles:
            title = item_json["title"]
            item_json["title"] = title[:span.start] + a.token_for("entity", host) + title[span.stop:]
        out_payload["incident_timeline"] = timeline_json
    out_contents = [anonymize_plain_text(c, a) for c in message_contents]
    out_attachments = [anonymize_plain_text(t, a) for t in (attachment_texts or [])]
    out_filenames = [anonymize_plain_text(name, a) for name in (attachment_filenames or [])]
    return out_payload, out_contents, out_attachments, out_filenames, a.reverse_map
