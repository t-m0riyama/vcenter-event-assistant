"""LLM 送信直前の識別子トークン化と応答の逆変換。"""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from typing import Any

# entity_name / user 系で先に登録した原文を message 内で置換する際に使う
_COLLECT_KEYS: tuple[tuple[str, str], ...] = (
    ("entity_name", "entity"),
    ("user_name", "user"),
    ("username", "user"),
    ("vcenter_label", "vcenter"),
)

_ANONYMIZE_KEYS: frozenset[str] = frozenset(
    {"entity_name", "message", "user_name", "username", "vcenter_label"},
)

# 文字列内 IPv4（簡易）
_IPV4_RE = re.compile(
    r"(?<![0-9])"
    r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)"
    r"(?:\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)){3}"
    r"(?![0-9])",
)


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

    @property
    def reverse_map(self) -> dict[str, str]:
        """トークン → 原文（逆変換用）。"""
        return dict(self._reverse)

    def replacements_longest_first(self) -> list[tuple[str, str]]:
        """原文が長い順に (原文, トークン)。message 内の部分置換に用いる。"""
        pairs: list[tuple[str, str]] = [(orig, tok) for tok, orig in self._reverse.items()]
        pairs.sort(key=lambda x: len(x[0]), reverse=True)
        return pairs


def deanonymize_text(text: str, reverse_map: dict[str, str]) -> str:
    """トークンを原文に戻す。トークン同士の部分一致を避けるため長いトークンから置換する。"""
    if not reverse_map:
        return text
    toks = sorted(reverse_map.keys(), key=len, reverse=True)
    out = text
    for tok in toks:
        out = out.replace(tok, reverse_map[tok])
    return out


def _collect_entity_user_pairs(obj: Any, acc: list[tuple[str, str]]) -> None:
    """ツリー内の entity / user フィールドを先に列挙する。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v:
                for field, cat in _COLLECT_KEYS:
                    if k == field:
                        acc.append((cat, v))
                        break
            _collect_entity_user_pairs(v, acc)
    elif isinstance(obj, list):
        for x in obj:
            _collect_entity_user_pairs(x, acc)


def _replace_ipv4_in_string(s: str, a: LlmAnonymizer) -> str:
    """同一 IP は同一トークン。"""

    def _sub(m: re.Match[str]) -> str:
        return a.token_for("ip", m.group(0))

    return _IPV4_RE.sub(_sub, s)


def anonymize_plain_text(text: str, a: LlmAnonymizer) -> str:
    """
    自由文に対し IPv4 を ip トークン化し、続いて既に発行済みの原文（全カテゴリ）を長い順に置換する。
    """
    if not text:
        return text
    s = _replace_ipv4_in_string(text, a)
    for original, tok in a.replacements_longest_first():
        if len(original) < 2:
            continue
        if original in s:
            s = s.replace(original, tok)
    return s


def _anonymize_node(obj: Any, a: LlmAnonymizer) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in _ANONYMIZE_KEYS and isinstance(v, str):
                if k == "message":
                    out[k] = anonymize_plain_text(v, a)
                elif k in ("user_name", "username"):
                    out[k] = a.token_for("user", v)
                elif k == "entity_name":
                    out[k] = a.token_for("entity", v)
                elif k == "vcenter_label":
                    out[k] = a.token_for("vcenter", v)
                else:
                    out[k] = copy.deepcopy(v)
            else:
                out[k] = _anonymize_node(v, a)
        return out
    if isinstance(obj, list):
        return [_anonymize_node(x, a) for x in obj]
    return copy.deepcopy(obj)


def anonymize_json_like(obj: Any) -> tuple[Any, dict[str, str]]:
    """
    JSON 互換オブジェクトを再帰的に匿名化する。

    手順: 先にツリー全体から entity / user の値を収集してトークン登録し、
    その後に各フィールドを匿名化（message は IPv4 + 登録済み原文の部分置換）。
    """
    pairs: list[tuple[str, str]] = []
    _collect_entity_user_pairs(obj, pairs)
    a = LlmAnonymizer()
    for cat, val in pairs:
        a.token_for(cat, val)
    out = _anonymize_node(obj, a)
    return out, a.reverse_map


def anonymize_for_llm(
    context_dict: dict[str, Any],
    template_markdown: str,
) -> tuple[dict[str, Any], str, dict[str, str]]:
    """
    ダイジェスト用: 集約 JSON とテンプレ Markdown を同一 ``LlmAnonymizer`` で匿名化する。
    """
    pairs: list[tuple[str, str]] = []
    _collect_entity_user_pairs(context_dict, pairs)
    a = LlmAnonymizer()
    for cat, val in pairs:
        a.token_for(cat, val)
    ctx_out = _anonymize_node(context_dict, a)
    md_out = anonymize_plain_text(template_markdown, a)
    return ctx_out, md_out, a.reverse_map


def anonymize_chat_for_llm(
    payload: dict[str, Any],
    message_contents: list[str],
) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    """
    チャット用: マージ済みペイロードと会話本文を同一 ``LlmAnonymizer`` で匿名化する。
    """
    pairs: list[tuple[str, str]] = []
    _collect_entity_user_pairs(payload, pairs)
    a = LlmAnonymizer()
    for cat, val in pairs:
        a.token_for(cat, val)
    out_payload = _anonymize_node(payload, a)
    out_contents = [anonymize_plain_text(c, a) for c in message_contents]
    return out_payload, out_contents, a.reverse_map
