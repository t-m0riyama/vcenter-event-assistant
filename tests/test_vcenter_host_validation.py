"""vCenter host SSRF バリデーション。"""

from __future__ import annotations

import pytest

from vcenter_event_assistant.services.vcenter_host_validation import validate_vcenter_host


def test_accepts_public_fqdn() -> None:
    assert validate_vcenter_host("vcenter.example.local") == "vcenter.example.local"


def test_rejects_loopback_ip() -> None:
    with pytest.raises(ValueError, match="blocked IP"):
        validate_vcenter_host("127.0.0.1")


def test_rejects_private_ip() -> None:
    with pytest.raises(ValueError, match="blocked IP"):
        validate_vcenter_host("10.0.0.1")


def test_rejects_metadata_ip() -> None:
    with pytest.raises(ValueError, match="blocked IP"):
        validate_vcenter_host("169.254.169.254")


def test_rejects_localhost_hostname() -> None:
    with pytest.raises(ValueError, match="blocked"):
        validate_vcenter_host("localhost")


def test_rejects_public_ip_when_suffix_allowlist_configured() -> None:
    with pytest.raises(ValueError, match="IP literals are not allowed"):
        validate_vcenter_host("8.8.8.8", allowed_suffixes=[".corp.local"])


def test_suffix_allowlist() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        validate_vcenter_host("evil.example.com", allowed_suffixes=[".corp.local"])
    assert (
        validate_vcenter_host("vc.corp.local", allowed_suffixes=[".corp.local"])
        == "vc.corp.local"
    )
