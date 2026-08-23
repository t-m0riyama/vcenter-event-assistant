"""モックモード用の vCenter 接続テスト応答。"""

from __future__ import annotations

from vcenter_event_assistant.collectors.connection import ConnectionInfo

_MOCK_INSTANCE_UUID = "00000000-0000-4000-8000-000000000001"


def mock_connection_info() -> ConnectionInfo:
    """接続テスト API 向けの固定製品情報を返す。"""
    return ConnectionInfo(
        product_name="VMware vCenter Server (mock)",
        product_version="8.0.0-mock",
        api_version="8.0.0",
        instance_uuid=_MOCK_INSTANCE_UUID,
    )
