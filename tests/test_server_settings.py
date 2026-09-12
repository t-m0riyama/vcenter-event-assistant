"""API サーバーの待受設定に関するテスト。"""

import importlib
from pathlib import Path
from unittest.mock import Mock

import pytest
import uvicorn
from pydantic import ValidationError

import vcenter_event_assistant
from vcenter_event_assistant.settings import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_uvicorn_port_defaults_to_8000(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UVICORN_PORT", raising=False)

    assert Settings().uvicorn_port == 8000


def test_uvicorn_port_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UVICORN_PORT", "9000")

    assert Settings().uvicorn_port == 9000


@pytest.mark.parametrize("value", ["0", "65536", "not-a-number"])
def test_uvicorn_port_rejects_invalid_environment_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("UVICORN_PORT", value)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(("value", "expected"), [(None, 8000), ("9000", 9000)])
def test_main_passes_configured_port_to_uvicorn(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: int
) -> None:
    if value is None:
        monkeypatch.delenv("UVICORN_PORT", raising=False)
    else:
        monkeypatch.setenv("UVICORN_PORT", value)
    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    get_settings.cache_clear()
    entrypoint_main = importlib.reload(vcenter_event_assistant).main

    try:
        entrypoint_main()
    finally:
        get_settings.cache_clear()

    run.assert_called_once()
    assert run.call_args.kwargs["port"] == expected


@pytest.mark.parametrize(
    "compose_file", ["docker-compose.sqlite.yml", "docker-compose.postgres.yml"]
)
def test_compose_uses_same_configurable_port_for_app_and_publish(compose_file: str) -> None:
    compose = (REPO_ROOT / compose_file).read_text(encoding="utf-8")

    assert '"127.0.0.1:${UVICORN_PORT:-8000}:${UVICORN_PORT:-8000}"' in compose
    assert "UVICORN_PORT: ${UVICORN_PORT:-8000}" in compose
