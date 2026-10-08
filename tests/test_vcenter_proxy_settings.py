"""Tests for VCENTER_HTTP_PROXY setting."""

from __future__ import annotations

import os
from unittest.mock import patch

from vcenter_event_assistant.settings import Settings


class TestVcenterHttpProxySetting:
    """vcenter_http_proxy field parsing."""

    def test_default_is_none(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            s = Settings(database_url="sqlite+aiosqlite:///:memory:")
            assert s.vcenter_http_proxy is None

    def test_reads_from_env(self) -> None:
        with patch.dict(os.environ, {"VCENTER_HTTP_PROXY": "http://proxy.local:3128"}, clear=False):
            s = Settings(database_url="sqlite+aiosqlite:///:memory:")
            assert s.vcenter_http_proxy == "http://proxy.local:3128"

    def test_empty_string_becomes_none(self) -> None:
        with patch.dict(os.environ, {"VCENTER_HTTP_PROXY": "  "}, clear=False):
            s = Settings(database_url="sqlite+aiosqlite:///:memory:")
            assert s.vcenter_http_proxy is None
