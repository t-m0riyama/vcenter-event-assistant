from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

def _normalize_to_utc(v: object) -> datetime:
    """datetime / ISO-8601 文字列を UTC に正規化する（複数の field_validator 共通）。"""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise TypeError("expected datetime or ISO-8601 string")

class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
