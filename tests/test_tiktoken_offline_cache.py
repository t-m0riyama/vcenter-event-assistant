"""tiktoken オフラインキャッシュが CI で使えることを保証する。"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest


def test_tiktoken_cl100k_base_loads_from_vendored_cache_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同梱キャッシュのみで cl100k_base をロードできる（DNS 遮断）。"""
    cache_dir = Path(__file__).resolve().parent / "fixtures" / "tiktoken_cache"
    cache_key = "9b5ad71b2ce5302211f9c61530b329a4922fc6a4"
    assert (cache_dir / cache_key).is_file(), f"missing vendored cache {cache_key}"

    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(cache_dir))

    def _block_dns(*_args: object, **_kwargs: object) -> list:
        raise OSError("DNS blocked for tiktoken offline test")

    monkeypatch.setattr(socket, "getaddrinfo", _block_dns)

    import tiktoken
    import tiktoken.registry

    # 他テストで既にロード済みでも、ディスクキャッシュ経路を再実行する
    tiktoken.registry.ENCODINGS.pop("cl100k_base", None)

    enc = tiktoken.get_encoding("cl100k_base")
    assert len(enc.encode("hello world")) == 2
