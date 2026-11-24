"""ログの先頭行から、版付きの型を作る。"""

import re
from hashlib import sha256
from typing import Callable

from vcenter_event_assistant.services.log_patterns.normalization import normalize_sql_text

MASK_VERSION = 1
UNPARSED = "<UNPARSED>"
_RAW_MAX = 2000
_TEMPLATE_MAX = 500

# リモートログ収集の parser.STAMP と同じ形。
_STAMP = re.compile(r"^\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?\s*")
_H = "[0-9a-fA-F]"
_SECRET_WORDS = r"password|passwd|pwd|secret|token|apikey|api_key|session|cookie|authorization"
_ORIGINATOR = re.compile(r"\[Originator@\d+\b([^\]]*)\]")
_AUTH_SCHEMES = r"Bearer|Basic|Digest|Negotiate|NTLM"
_SECRET = re.compile(
    rf'''(?P<label>(?<!(?-i:[A-Za-z0-9]))["']?(?:{_SECRET_WORDS})\b["']?\s*[:=]\s*)'''
    rf'''(?:(?P<labeled_auth>(?:{_AUTH_SCHEMES})\s+[^\s\],;]+)|'''
    r'''"(?:\\.|[^"\\])*(?:"|\\?$)|'(?:\\.|[^'\\])*(?:'|\\?$)|[^\s\],;]+)'''
    r'''|\b(?P<scheme>Bearer)\s+[^\s\],;]+''',
    re.IGNORECASE,
)
_EXTENSIONS = r"vmx|vmdk|vmsd|nvram|log|vswp|vmxf"
_PLACEHOLDER = re.compile(r"(<[A-Z]+>)")
_NUMBER_PROTECTED = re.compile(r"(<[A-Z]+>|\b0x[0-9a-fA-F]{1,2}\b)")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SPACE = re.compile(r"\s+")


def _originator(match: re.Match[str]) -> str:
    sub = re.search(r"(?:^|\s)(sub=\S+)", match[1])
    return f"[{sub[1]}]" if sub else "[]"


def _secret(match: re.Match[str]) -> str:
    label = match["label"]
    if label is None:
        return f"{match['scheme']} <SECRET>"
    # 秘密の語が付いた認証情報は、方式と値の両方を伏せる。
    return label + ("<SECRET> <SECRET>" if match["labeled_auth"] is not None else "<SECRET>")


def _identity(match: re.Match[str]) -> str:
    return match[1] + ("=<ID>" if match[1].lower() == "opid" else "=<USER>")


# 計画書の規則 3〜11 の順。12 の数は短い 0x の値も保護してから伏せる。
_RULES: tuple[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"\b(opID|user)=[^\s\]]+", re.IGNORECASE), _identity),
    (re.compile(r"""\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'"<>\]]+"""), "<URL>"),
    (re.compile(rf"(?<![\w:])(?:{_H}{{2}}:){{7}}{_H}{{2}}(?![\w:])"), "<WWN>"),
    (re.compile(rf"(?<![\w:-]){_H}{{2}}([:-])(?:{_H}{{2}}\1){{4}}{_H}{{2}}(?![\w:-])"), "<MAC>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b"), "<IP>"),
    (re.compile(
        rf"(?<![\w:])(?:{_H}{{1,4}}:){{7}}{_H}{{1,4}}(?![\w:])"
        rf"|(?<![\w:])(?:{_H}{{1,4}}:)*{_H}{{1,4}}::(?:{_H}{{1,4}}:)*{_H}{{0,4}}(?![\w:])"
        rf"|(?<![\w:])::{_H}{{1,4}}(?::{_H}{{1,4}})*(?![\w:])"
    ), "<IP>"),
    (re.compile(r"""(?:(?<=^)|(?<=[\s:="'(\[]))/[^\s"',)\]]*"""), "<PATH>"),
    (re.compile(
        rf"""\[(?!Originator|sub=)[^\]\s][^\]]*\] [^\s"']*\.(?:{_EXTENSIONS})(?=$|[\s"'),;\]])"""
    ), "<PATH>"),
    (re.compile(r"\b\d{4}-\d\d-\d\d(?:[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?)?"), "<TIME>"),
    (re.compile(r"\b\d\d:\d\d:\d\d(?:\.\d+)?\b"), "<TIME>"),
    (re.compile(rf"\b{_H}{{8}}-{_H}{{4}}-{_H}{{4}}-{_H}{{4}}-{_H}{{12}}\b"), "<UUID>"),
    (re.compile(rf"\b{_H}{{8}}-{_H}{{8}}-{_H}{{4}}-{_H}{{12}}\b"), "<UUID>"),
    (re.compile(r"""\b(?:naa|eui|t10|mpx)\.[^\s"',;)\]]+"""), "<DEV>"),
    (re.compile(r"\bvmhba\d+:C\d+:T\d+:L\d+\b"), "<HBAPATH>"),
    (re.compile(rf"\b0x{_H}{{3,}}\b"), "<HEX>"),
    (re.compile(rf"\b(?={_H}*[a-fA-F]){_H}{{8,}}\b"), "<HEX>"),
)


def normalize_log_kind(log_kind: str) -> str:
    return normalize_sql_text(log_kind)


def pattern_key(log_kind: str, template: str) -> str:
    value = f"{MASK_VERSION}\0{normalize_log_kind(log_kind)}\0{template}"
    return sha256(value.encode()).hexdigest()[:32]


def mask_message(message: str) -> str:
    """時刻・可変値を伏せた先頭行を返す。失敗時は決めた型にまとめる。"""
    try:
        end = message.find("\n", 0, _RAW_MAX)
        line = _STAMP.sub("", message[:_RAW_MAX if end == -1 else end], count=1)
        line = _ORIGINATOR.sub(_originator, line)
        line = _SECRET.sub(_secret, line)
        for pattern, replacement in _RULES:
            parts = _PLACEHOLDER.split(line)
            for index in range(0, len(parts), 2):
                parts[index] = pattern.sub(replacement, parts[index])
            line = "".join(parts)
        parts = _NUMBER_PROTECTED.split(line)
        for index in range(0, len(parts), 2):
            parts[index] = _NUMBER.sub("<N>", parts[index])
        return _SPACE.sub(" ", "".join(parts)).strip()[:_TEMPLATE_MAX]
    except Exception:
        return UNPARSED
