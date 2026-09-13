"""pyVmomi を使ったインベントリ走査のヘルパ。

**このモジュールは import しただけでは pyVmomi を読み込まない。** 実際に必要な関数の
中でだけ遅延 import する。コアの依存ゼロという方針を保ちつつ、pyVmomi が無い環境では
:class:`PyVmomiUnavailableError` で理由を明示するためである。

型を**名前文字列**（``"HostSystem"`` など）で受け取るのが要点で、プラグイン側は
``from pyVmomi import vim`` を書かずに済む。pyVmomi への依存境界がこの 1 ファイルに閉じる。

実行時、pyVmomi はアプリ本体の依存としてコレクタワーカーの ``sys.path`` に既に見えて
いるため、プラグインが追加でインストールする必要はない（オフラインの ``--no-deps``
導入でも動く）。アプリの外でプラグイン単体を import してテストする場合だけ、
``vcenter-event-assistant-plugin-api[vmware]`` で pyVmomi を入れること。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

__all__ = [
    "PyVmomiUnavailableError",
    "container_view",
    "datastore_is_accessible",
    "host_is_connected",
    "iter_datastores",
    "iter_hosts",
    "moid",
]

#: ``HostSystem.runtime.connectionState`` が接続中を表す値。
#:
#: pyVmomi の enum は ``str`` の派生なので、この比較は pyVmomi を import せずに成立する
#: （``vim.HostSystem.ConnectionState.connected == "connected"`` は真）。おかげで
#: :func:`host_is_connected` はテスト用の偽オブジェクトに対しても使える。
_CONNECTED = "connected"


class PyVmomiUnavailableError(RuntimeError):
    """pyVmomi が import できない。

    アプリのコレクタワーカー内では起きない（アプリ本体の依存として入っている）。
    アプリの外でプラグインを単体テストするときに、extra を入れ忘れると起きる。
    """


def _vim() -> Any:
    try:
        from pyVmomi import vim
    except ImportError as exc:  # pragma: no cover - 導入済み環境では通らない
        raise PyVmomiUnavailableError(
            "pyVmomi is required for vcenter_event_assistant_plugin_api.vmware; "
            "install vcenter-event-assistant-plugin-api[vmware] to use it outside the app"
        ) from exc
    return vim


def _resolve_types(types: Sequence[str]) -> list[Any]:
    """``"HostSystem"`` のような名前を ``vim`` の型へ解決する。"""
    vim = _vim()
    resolved: list[Any] = []
    for name in types:
        managed_type = getattr(vim, name, None)
        if managed_type is None:
            raise ValueError(f"unknown managed object type: {name}")
        resolved.append(managed_type)
    return resolved


@contextmanager
def container_view(
    si: Any,
    types: Sequence[str],
    *,
    root: Any | None = None,
    recursive: bool = True,
) -> Iterator[list[Any]]:
    """ContainerView を開き、**必ず** ``Destroy()`` して閉じる。

    ``Destroy()`` を忘れるとビューが vCenter 側に残り続けるため、この
    コンテキストマネージャ経由で使うこと。

    Args:
        si: 接続済みの ServiceInstance。
        types: ``"HostSystem"`` / ``"Datastore"`` などの型名。
        root: 走査の起点。省略時は ``rootFolder``。
        recursive: 配下を再帰的にたどるか。

    Yields:
        見つかった managed object のリスト（ビューの生存期間に依存しないよう、
        ``list()`` に確定済み）。
    """
    # 型の解決を先に済ませる。pyVmomi が無い環境や型名の誤りが、セッションを触る前に
    # `PyVmomiUnavailableError` / `ValueError` として出る。
    managed_types = _resolve_types(types)
    content = si.RetrieveContent()
    view = content.viewManager.CreateContainerView(
        root if root is not None else content.rootFolder,
        managed_types,
        recursive,
    )
    try:
        yield list(view.view)
    finally:
        view.Destroy()


def moid(managed_object: Any) -> str:
    """managed object の MOID を返す。

    pyVmomi は MOID を private 風の ``_moId`` で持つ。その参照をここ 1 箇所に閉じる。
    """
    return str(managed_object._moId)


def host_is_connected(host: Any) -> bool:
    """``HostSystem`` が接続状態か。切断中のホストは統計を返さない。"""
    runtime = getattr(host, "runtime", None)
    if runtime is None:
        return False
    return getattr(runtime, "connectionState", None) == _CONNECTED


def datastore_is_accessible(datastore: Any) -> bool:
    """``Datastore`` がアクセス可能か。``summary`` が無い場合は False。"""
    summary = getattr(datastore, "summary", None)
    if summary is None:
        return False
    return bool(getattr(summary, "accessible", False))


def iter_hosts(si: Any, *, connected_only: bool = True) -> list[Any]:
    """インベントリ全体の ``HostSystem`` を返す。

    既定で切断中のホストを除く。切断中のホストは ``summary.quickStats`` が空だったり
    属性アクセスで例外になったりするため、含めても使えないことが多い。
    """
    with container_view(si, ["HostSystem"]) as hosts:
        if not connected_only:
            return hosts
        return [host for host in hosts if host_is_connected(host)]


def iter_datastores(si: Any, *, accessible_only: bool = True) -> list[Any]:
    """インベントリ全体の ``Datastore`` を返す。既定でアクセス不能なものを除く。"""
    with container_view(si, ["Datastore"]) as datastores:
        if not accessible_only:
            return datastores
        return [ds for ds in datastores if datastore_is_accessible(ds)]
