"""診断引数とイベント本文で扱うストレージデバイス ID。"""

import re

DEVICE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_PDL_MESSAGE = re.compile(r"Device (.*?) has been removed or is permanently inaccessible", re.DOTALL)
_STORAGE_ID_IN_MESSAGE = re.compile(
    r"(?<![A-Za-z0-9._:-])(?ai:naa|eui|mpx)\.[A-Za-z0-9_.:-]*[A-Za-z0-9_]"
)
_STORAGE_ID_SEPARATOR = re.compile(r"""[\s,;'")\]]|[^\x00-\x7f]""")
_STORAGE_ID_END = re.compile(rf"\Z|{_STORAGE_ID_SEPARATOR.pattern}|\.(?:\Z|\s)")


def extract_storage_device_id(message: str | None) -> str | None:
    if not message:
        return None
    formatted = _PDL_MESSAGE.match(message)
    if formatted is not None:
        value = formatted[1]
        return value if DEVICE_ID_PATTERN.fullmatch(value) else None

    # 同じ ID の表記が複数あれば、本文で最初に出た表記を残す。
    candidates: dict[str, str] = {}
    rejected_end: int | None = None
    for match in _STORAGE_ID_IN_MESSAGE.finditer(message):
        if rejected_end is not None and _STORAGE_ID_SEPARATOR.search(message, rejected_end, match.start()) is None:
            # naa.a/naa.b のようにつながった値から、後半だけを採用しない。
            return None
        if _STORAGE_ID_END.match(message, match.end()) is None:
            rejected_end = match.end()
            continue
        rejected_end = None
        value = match[0]
        if DEVICE_ID_PATTERN.fullmatch(value):
            candidates.setdefault(value.lower(), value)
    return next(iter(candidates.values())) if len(candidates) == 1 else None
