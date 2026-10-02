"""Byte positions refer to uncompressed UTF-8 data, before decoding."""

from datetime import datetime, timezone
import re

STAMP = re.compile(rb"^\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?")
LEVEL = re.compile(r"\b(panic|critical|error|warning|warn|info|debug|verbose)\b", re.I)


def timestamp(line: bytes):
    match = STAMP.match(line)
    if not match:
        return None
    try:
        value = datetime.fromisoformat(match.group().decode().replace("Z", "+00:00"))
        # Do not invent a timezone for an ambiguous timestamp.
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except ValueError:
        return None


def records(data: bytes, start: int, *, eof: bool):
    """Yield (offset, end, text, time, severity). Hold the active trailing record.

    A timestamp-looking line starts a record even when its timestamp is invalid.
    Unterminated lines remain unread; immutable rotated files may finish at EOF.
    """
    lines = data.splitlines(keepends=True)
    if lines and not lines[-1].endswith(b"\n") and not eof:
        lines.pop()
    pending = []
    position = start
    begin = start
    for line in lines:
        starts_record = bool(STAMP.match(line))
        if pending and starts_record:
            yield _record(begin, position, b"".join(pending))
            pending = []
        if not pending:
            begin = position
        pending.append(line)
        position += len(line)
        # Unknown standalone lines can be saved immediately.
        if len(pending) == 1 and not starts_record:
            yield _record(begin, position, b"".join(pending))
            pending = []
    if pending and eof:
        yield _record(begin, position, b"".join(pending))


def _record(begin, end, raw):
    text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
    match = LEVEL.search(text.split("\n", 1)[0])
    level = match.group().lower() if match else None
    if level == "warn":
        level = "warning"
    return begin, end, text, timestamp(raw), level
