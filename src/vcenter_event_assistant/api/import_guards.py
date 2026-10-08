"""JSON インポート API の破壊的操作ガード。"""

from __future__ import annotations

from fastapi import HTTPException, status

HTTP_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", status.HTTP_422_UNPROCESSABLE_ENTITY)


def reject_empty_destructive_import(
    *,
    item_count: int,
    delete_not_in_import: bool,
    resource_label: str,
) -> None:
    """空リスト + delete フラグによる全件削除を拒否する。"""
    if delete_not_in_import and item_count == 0:
        raise HTTPException(
            status_code=HTTP_422,
            detail=(
                f"Cannot delete all {resource_label} when import list is empty. "
                "Provide items or disable the delete flag."
            ),
        )
