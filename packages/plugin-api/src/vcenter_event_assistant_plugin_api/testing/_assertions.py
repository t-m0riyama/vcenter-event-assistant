"""コレクタを 1 行で回して検証するためのアサーション。

``run_collect`` はアプリが本番で行うことを手元で再現する。``start`` → ``collect`` →
``stop`` を回し、返ってきたバッチをアプリと**同一の規則**で検証し、さらに接続の
リークと ContainerView の破棄漏れを検査する。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectionContext,
    CollectorManifest,
)
from vcenter_event_assistant_plugin_api.testing._connection import ConnectionLog
from vcenter_event_assistant_plugin_api.testing._context import make_context
from vcenter_event_assistant_plugin_api.testing._vmomi import FakeServiceInstance
from vcenter_event_assistant_plugin_api.validation import (
    Issue,
    check_batch,
    check_manifest,
)

__all__ = ["assert_batch_valid", "assert_manifest_valid", "run_collect"]


def _format(issues: tuple[Issue, ...]) -> str:
    return "\n".join(f"  [{issue.severity}] {issue.code}: {issue.message}" for issue in issues)


def assert_manifest_valid(manifest: CollectorManifest) -> None:
    """マニフェストがアプリの登録検証を通ることを確認する。

    宣言的な基底クラスを使っている場合、これはクラス定義の時点で済んでいる。
    ``manifest`` を手書きしている場合はここで確認する。
    """
    issues = check_manifest(manifest)
    if issues:
        raise AssertionError(f"manifest is not valid:\n{_format(issues)}")


def assert_batch_valid(
    manifest: CollectorManifest,
    batch: CollectionBatch,
    *,
    allow_warnings: bool = False,
) -> None:
    """バッチがアプリに受理される形であることを確認する。

    ``allow_warnings=False``（既定）では warning でも失敗する。アプリは warning を
    拒否しないが、warning はいずれも**本番でデータが静かに失われる**もの
    （列長超過、``vmware_key`` の 32 bit 範囲外、バッチ内の重複排除キー衝突など）
    なので、テストでは落ちてくれた方がよい。
    """
    issues = check_batch(manifest, batch)
    if allow_warnings:
        issues = tuple(issue for issue in issues if issue.severity != "warning")
    if issues:
        raise AssertionError(f"batch would be rejected or lose data:\n{_format(issues)}")


async def run_collect(
    plugin: Any,
    context: CollectionContext | None = None,
    *,
    validate: bool = True,
    allow_warnings: bool = False,
    check_connection: bool = True,
    **context_kwargs: Any,
) -> CollectionBatch:
    """``start`` → ``collect`` → ``stop`` を回してバッチを検証する。

    Args:
        plugin: コレクタのインスタンス。
        context: 使う :class:`CollectionContext`。省略時は ``context_kwargs`` を
            :func:`make_context` に渡して組み立てる。
        validate: バッチをアプリと同一の規則で検証するか。
        allow_warnings: warning を許すか（既定は許さない）。
        check_connection: 接続の開閉が釣り合っているか、ContainerView が
            破棄されているかを検査するか。
        **context_kwargs: :func:`make_context` への引数。``context`` と併用できない。

    Returns:
        コレクタが返した :class:`CollectionBatch`。

    ``stop()`` は ``collect()`` が失敗しても必ず呼ぶ。アプリも同様に振る舞う。
    """
    if context is not None and context_kwargs:
        raise TypeError("pass either context or make_context() keyword arguments")
    if context is None:
        context = make_context(**context_kwargs)

    log = ConnectionLog()
    opened: list[Any] = []
    original = context.open_vcenter_connection

    @asynccontextmanager
    async def _recording() -> AsyncIterator[Any]:
        log.enters += 1
        try:
            async with original() as service_instance:
                opened.append(service_instance)
                yield service_instance
        finally:
            log.exits += 1

    context = replace(context, open_vcenter_connection=_recording)

    await plugin.start()
    try:
        batch: CollectionBatch = await plugin.collect(context)
    finally:
        await plugin.stop()

    if check_connection:
        log.assert_balanced()
        for service_instance in opened:
            if isinstance(service_instance, FakeServiceInstance):
                service_instance.assert_all_views_destroyed()
    if validate:
        assert_batch_valid(plugin.manifest, batch, allow_warnings=allow_warnings)
    return batch
