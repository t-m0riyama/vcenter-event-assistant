"""Tests for the pyVmomi helpers.

pyVmomi 本体は使わず、``RetrieveContent`` / ``CreateContainerView`` の形だけを真似た
偽オブジェクトで確認する。型解決だけは実物の ``vim`` が要るので、その部分は
:func:`_fake_vim` を差し込んで検証する。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from vcenter_event_assistant_plugin_api import vmware


class FakeView:
    def __init__(self, objects: list[Any]) -> None:
        self.view = objects
        self.destroyed = 0

    def Destroy(self) -> None:  # noqa: N802 - pyVmomi の命名に合わせる
        self.destroyed += 1


class FakeServiceInstance:
    """``CreateContainerView`` の引数を記録する最小の ServiceInstance。"""

    def __init__(self, objects: dict[Any, list[Any]] | None = None) -> None:
        self._objects = objects or {}
        self.views: list[FakeView] = []
        self.calls: list[tuple[Any, Any, bool]] = []
        self.root = SimpleNamespace(name="rootFolder")
        content = SimpleNamespace(
            rootFolder=self.root,
            viewManager=SimpleNamespace(CreateContainerView=self._create),
        )
        self._content = content

    def RetrieveContent(self) -> Any:  # noqa: N802 - pyVmomi の命名に合わせる
        return self._content

    def _create(self, root: Any, types: Any, recursive: bool) -> FakeView:
        self.calls.append((root, tuple(types), recursive))
        objects: list[Any] = []
        for managed_type in types:
            objects.extend(self._objects.get(managed_type, []))
        view = FakeView(objects)
        self.views.append(view)
        return view


def fake_host(moid: str, name: str, *, connected: bool = True) -> Any:
    return SimpleNamespace(
        _moId=moid,
        name=name,
        runtime=SimpleNamespace(
            connectionState="connected" if connected else "disconnected"
        ),
    )


def fake_datastore(moid: str, name: str, *, accessible: bool = True) -> Any:
    return SimpleNamespace(
        _moId=moid, name=name, summary=SimpleNamespace(accessible=accessible)
    )


@pytest.fixture
def fake_vim(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``_vim()`` が返す名前空間を、名前を素通しする偽物に差し替える。

    これで型名の文字列がそのまま ``CreateContainerView`` へ渡り、
    :class:`FakeServiceInstance` の辞書キーとして使える。
    """

    class _Vim:
        HostSystem = "HostSystem"
        Datastore = "Datastore"

    vim = _Vim()
    monkeypatch.setattr(vmware, "_vim", lambda: vim)
    return vim


def test_container_view_destroys_the_view(fake_vim: Any) -> None:
    si = FakeServiceInstance({"HostSystem": [fake_host("host-1", "esxi-a")]})
    with vmware.container_view(si, ["HostSystem"]) as hosts:
        assert [host.name for host in hosts] == ["esxi-a"]
    assert si.views[0].destroyed == 1


def test_container_view_destroys_the_view_even_on_error(fake_vim: Any) -> None:
    si = FakeServiceInstance({"HostSystem": []})
    with pytest.raises(ZeroDivisionError):
        with vmware.container_view(si, ["HostSystem"]):
            raise ZeroDivisionError
    assert si.views[0].destroyed == 1


def test_container_view_returns_a_list_independent_of_the_view(fake_vim: Any) -> None:
    """ビューを Destroy した後も結果を使えること。"""
    si = FakeServiceInstance({"HostSystem": [fake_host("host-1", "esxi-a")]})
    with vmware.container_view(si, ["HostSystem"]) as hosts:
        pass
    view = si.views[0]
    view.view.clear()
    assert len(hosts) == 1


def test_container_view_defaults_to_the_root_folder_and_recursion(fake_vim: Any) -> None:
    si = FakeServiceInstance()
    with vmware.container_view(si, ["HostSystem"]):
        pass
    root, types, recursive = si.calls[0]
    assert root is si.root
    assert types == ("HostSystem",)
    assert recursive is True


def test_container_view_accepts_an_explicit_root_and_non_recursive(fake_vim: Any) -> None:
    si = FakeServiceInstance()
    other = SimpleNamespace(name="datacenter-1")
    with vmware.container_view(si, ["Datastore"], root=other, recursive=False):
        pass
    root, _types, recursive = si.calls[0]
    assert root is other
    assert recursive is False


def test_container_view_accepts_several_types(fake_vim: Any) -> None:
    si = FakeServiceInstance(
        {
            "HostSystem": [fake_host("host-1", "esxi-a")],
            "Datastore": [fake_datastore("ds-1", "store")],
        }
    )
    with vmware.container_view(si, ["HostSystem", "Datastore"]) as objects:
        assert [obj.name for obj in objects] == ["esxi-a", "store"]


def test_container_view_rejects_an_unknown_type_name(fake_vim: Any) -> None:
    si = FakeServiceInstance()
    with pytest.raises(ValueError, match="unknown managed object type: NoSuchThing"):
        with vmware.container_view(si, ["NoSuchThing"]):
            pass
    # 型解決に失敗した時点でビューは作られない（Destroy 漏れもない）。
    assert si.views == []


def test_iter_hosts_skips_disconnected_hosts_by_default(fake_vim: Any) -> None:
    si = FakeServiceInstance(
        {
            "HostSystem": [
                fake_host("host-1", "esxi-a"),
                fake_host("host-2", "esxi-b", connected=False),
            ]
        }
    )
    assert [host.name for host in vmware.iter_hosts(si)] == ["esxi-a"]
    assert si.views[0].destroyed == 1


def test_iter_hosts_can_include_disconnected_hosts(fake_vim: Any) -> None:
    si = FakeServiceInstance(
        {
            "HostSystem": [
                fake_host("host-1", "esxi-a"),
                fake_host("host-2", "esxi-b", connected=False),
            ]
        }
    )
    hosts = vmware.iter_hosts(si, connected_only=False)
    assert [host.name for host in hosts] == ["esxi-a", "esxi-b"]


def test_iter_datastores_skips_inaccessible_datastores_by_default(fake_vim: Any) -> None:
    si = FakeServiceInstance(
        {
            "Datastore": [
                fake_datastore("ds-1", "store-a"),
                fake_datastore("ds-2", "store-b", accessible=False),
            ]
        }
    )
    assert [ds.name for ds in vmware.iter_datastores(si)] == ["store-a"]


def test_iter_datastores_can_include_inaccessible_datastores(fake_vim: Any) -> None:
    si = FakeServiceInstance(
        {"Datastore": [fake_datastore("ds-2", "store-b", accessible=False)]}
    )
    assert len(vmware.iter_datastores(si, accessible_only=False)) == 1


def test_host_is_connected() -> None:
    assert vmware.host_is_connected(fake_host("host-1", "esxi-a")) is True
    assert vmware.host_is_connected(fake_host("host-1", "esxi-a", connected=False)) is False


def test_host_is_connected_without_runtime() -> None:
    """`runtime` が無い／None のホストは未接続とみなす。"""
    assert vmware.host_is_connected(SimpleNamespace(name="esxi-a")) is False
    assert vmware.host_is_connected(SimpleNamespace(runtime=None)) is False
    assert vmware.host_is_connected(SimpleNamespace(runtime=SimpleNamespace())) is False


def test_datastore_is_accessible() -> None:
    assert vmware.datastore_is_accessible(fake_datastore("ds-1", "a")) is True
    assert vmware.datastore_is_accessible(fake_datastore("ds-1", "a", accessible=False)) is False
    assert vmware.datastore_is_accessible(SimpleNamespace()) is False
    assert vmware.datastore_is_accessible(SimpleNamespace(summary=None)) is False


def test_moid_reads_the_private_attribute() -> None:
    assert vmware.moid(fake_host("host-42", "esxi-a")) == "host-42"


def test_pyvmomi_unavailable_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """pyVmomi が無い環境では、何を入れればよいかが分かるメッセージになる。"""
    monkeypatch.setitem(sys.modules, "pyVmomi", None)
    with pytest.raises(vmware.PyVmomiUnavailableError, match=r"\[vmware\]"):
        vmware._vim()


def test_pyvmomi_unavailable_is_raised_before_touching_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """セッションに触る前に落ちるので、原因の分かる例外が出る。"""
    monkeypatch.setitem(sys.modules, "pyVmomi", None)

    def explode() -> Any:
        raise AssertionError("the session must not be touched")

    with pytest.raises(vmware.PyVmomiUnavailableError):
        with vmware.container_view(SimpleNamespace(RetrieveContent=explode), ["HostSystem"]):
            pass


def test_the_connected_constant_matches_pyvmomi() -> None:
    """pyVmomi の enum と文字列比較が成立することを実物で確認する。

    これが崩れると `host_is_connected` が常に False になり、**メトリクスが静かに
    空になる**。pyVmomi が無い環境（plugin-api 単体）ではスキップする。
    """
    vim = pytest.importorskip("pyVmomi").vim
    assert vim.HostSystem.ConnectionState.connected == vmware._CONNECTED


def test_importing_the_module_does_not_import_pyvmomi() -> None:
    """遅延 import の回帰防止。別インタプリタで確かめる。"""
    import subprocess

    code = (
        "import sys;"
        "import vcenter_event_assistant_plugin_api.vmware;"
        "assert 'pyVmomi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
