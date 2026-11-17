from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


def to_utc_or_value_error(value: datetime) -> datetime:
    """要求で受け取った日時を UTC に揃える。タイムゾーンの無い値は UTC とみなす。

    UTC に直すと日時の範囲を外れる値（``0001-01-01T00:00:00+01:00`` など）は、``astimezone`` の
    ``OverflowError`` を ``ValueError`` にする。pydantic の検証の中なら 500 ではなく 422 になる。
    """
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    try:
        return value.astimezone(timezone.utc)
    except OverflowError as exc:
        raise ValueError("datetime must be within the supported range when converted to UTC") from exc


# 要求の本文・クエリで受け取る日時の型。UTC に揃え、UTC に直せない値は 422 にする。
UtcDateTime = Annotated[datetime, AfterValidator(to_utc_or_value_error)]


def _normalize_to_utc(v: object) -> datetime:
    """datetime / ISO-8601 文字列を UTC に正規化する（複数の field_validator 共通）。

    応答のモデルで DB の値を読むための関数。要求で受け取る日時には ``UtcDateTime``（``to_utc_or_value_error``）を使う。
    """
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
