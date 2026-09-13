"""pyVmomi の managed object を模した偽オブジェクト。

実際の vCenter を用意せずにコレクタの :meth:`sample` / :meth:`fetch` を動かすための
最小限の形だけを持つ。:class:`FakeServiceInstance` は ``CreateContainerView`` で作った
ビューを記録するので、``Destroy()`` の呼び忘れをテストで検出できる。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "FakeContainerView",
    "FakeManagedObject",
    "FakeServiceInstance",
    "ViewLeakError",
    "fake_datastore",
    "fake_host",
    "fake_vm",
]


class ViewLeakError(AssertionError):
    """``CreateContainerView`` で作ったビューが ``Destroy()`` されていない。

    本番では vCenter 側にビューが残り続けるが、手元では何も起きないため気づけない。
    :func:`~vcenter_event_assistant_plugin_api.testing.run_collect` がこれを送出する。
    """


class FakeManagedObject:
    """MOID と任意の属性を持つ managed object。

    pyVmomi は MOID を ``_moId`` に持つので、それに合わせている。
    ``vmware.moid()`` がそのまま使える。
    """

    def __init__(self, moid: str, **attributes: Any) -> None:
        self._moId = moid  # noqa: N803 - pyVmomi の命名に合わせる
        for name, value in attributes.items():
            setattr(self, name, value)

    def __repr__(self) -> str:
        name = getattr(self, "name", None)
        return f"{type(self).__name__}({self._moId!r}, name={name!r})"


class FakeContainerView:
    """``Destroy()`` の呼び出し回数を数える ContainerView。"""

    def __init__(self, objects: list[Any], *, type_names: tuple[str, ...]) -> None:
        self.view = objects
        self.type_names = type_names
        self.destroy_count = 0

    @property
    def destroyed(self) -> bool:
        return self.destroy_count > 0

    def Destroy(self) -> None:  # noqa: N802 - pyVmomi の命名に合わせる
        self.destroy_count += 1


def _type_name(managed_type: Any) -> str:
    """``vim.HostSystem`` / ``"HostSystem"`` のどちらからでも短い型名を得る。

    ``vmware.container_view`` は型名の文字列を pyVmomi の型へ解決してから
    ``CreateContainerView`` を呼ぶ。その型の ``__name__`` は ``"vim.HostSystem"``
    なので、末尾のセグメントだけを取る。pyVmomi の無い環境で文字列がそのまま
    渡ってくる場合にも対応する。
    """
    name = getattr(managed_type, "__name__", None) or str(managed_type)
    return name.rsplit(".", 1)[-1]


class FakeServiceInstance:
    """``RetrieveContent`` と ``CreateContainerView`` だけを持つ ServiceInstance。

    ``vmware.container_view`` / ``vmware.iter_hosts`` / ``vmware.iter_datastores``
    から使える。作ったビューは :attr:`views` に残るので、``Destroy()`` 漏れを
    :meth:`assert_all_views_destroyed` で検査できる。

    Note:
        ``vmware`` ヘルパ経由で使う場合、型名の解決に pyVmomi が必要である
        （``vcenter-event-assistant-plugin-api[vmware]``）。pyVmomi を入れずに
        テストしたい場合は、``si.objects_of("HostSystem")`` を直接使うか、
        ``mock_mode=True`` の経路だけを試すこと。
    """

    def __init__(
        self,
        *,
        hosts: list[Any] | tuple[Any, ...] = (),
        datastores: list[Any] | tuple[Any, ...] = (),
        vms: list[Any] | tuple[Any, ...] = (),
        objects: dict[str, list[Any]] | None = None,
        about: Any | None = None,
    ) -> None:
        self._objects: dict[str, list[Any]] = {
            "HostSystem": list(hosts),
            "Datastore": list(datastores),
            "VirtualMachine": list(vms),
        }
        for type_name, items in (objects or {}).items():
            self._objects.setdefault(type_name, []).extend(items)
        #: 作られたビュー。生成順に並ぶ。
        self.views: list[FakeContainerView] = []
        #: ``CreateContainerView`` の引数（root, 型名, recursive）の記録。
        self.view_calls: list[tuple[Any, tuple[str, ...], bool]] = []
        #: ``RetrieveContent`` の呼び出し回数。
        self.retrieve_count = 0
        self.root_folder = FakeManagedObject("group-d1", name="Datacenters")
        self.about = about

    def objects_of(self, type_name: str) -> list[Any]:
        """指定した型のオブジェクトを返す（ビューを介さない直接アクセス）。"""
        return list(self._objects.get(type_name, []))

    def RetrieveContent(self) -> Any:  # noqa: N802 - pyVmomi の命名に合わせる
        self.retrieve_count += 1
        return _FakeContent(self)

    def assert_all_views_destroyed(self) -> None:
        """未破棄のビューがあれば :class:`ViewLeakError` を送出する。"""
        leaked = [view for view in self.views if not view.destroyed]
        if leaked:
            names = ", ".join("+".join(view.type_names) for view in leaked)
            raise ViewLeakError(
                f"{len(leaked)} container view(s) were not destroyed: {names}; "
                "use vmware.container_view() or call view.Destroy() in a finally block"
            )

    def _create_view(self, root: Any, types: Any, recursive: bool) -> FakeContainerView:
        type_names = tuple(_type_name(item) for item in types)
        self.view_calls.append((root, type_names, bool(recursive)))
        objects: list[Any] = []
        for type_name in type_names:
            objects.extend(self._objects.get(type_name, []))
        view = FakeContainerView(objects, type_names=type_names)
        self.views.append(view)
        return view


class _FakeContent:
    """``si.RetrieveContent()`` が返すもの。"""

    def __init__(self, service_instance: FakeServiceInstance) -> None:
        self._si = service_instance
        self.rootFolder = service_instance.root_folder  # noqa: N815 - pyVmomi の命名
        self.about = service_instance.about
        self.viewManager = _FakeViewManager(service_instance)  # noqa: N815


class _FakeViewManager:
    def __init__(self, service_instance: FakeServiceInstance) -> None:
        self._si = service_instance

    def CreateContainerView(  # noqa: N802 - pyVmomi の命名に合わせる
        self, container: Any, type: Any, recursive: bool
    ) -> FakeContainerView:
        return self._si._create_view(container, type, recursive)


def fake_host(
    moid: str = "host-1",
    name: str = "esxi-01.example.com",
    *,
    connected: bool = True,
    **attributes: Any,
) -> FakeManagedObject:
    """``HostSystem`` を模したオブジェクト。

    ``vmware.host_is_connected`` が見る ``runtime.connectionState`` を持つ。
    """
    runtime = _Namespace(connectionState="connected" if connected else "disconnected")
    return FakeManagedObject(moid, name=name, runtime=runtime, **attributes)


def fake_datastore(
    moid: str = "datastore-1",
    name: str = "datastore-01",
    *,
    capacity: int = 1024**4,
    free_space: int = 512 * 1024**3,
    accessible: bool = True,
    **attributes: Any,
) -> FakeManagedObject:
    """``Datastore`` を模したオブジェクト。``summary`` に容量を持つ。"""
    summary = _Namespace(
        name=name, capacity=capacity, freeSpace=free_space, accessible=accessible
    )
    return FakeManagedObject(moid, name=name, summary=summary, **attributes)


def fake_vm(
    moid: str = "vm-1",
    name: str = "vm-01",
    *,
    power_state: str = "poweredOn",
    **attributes: Any,
) -> FakeManagedObject:
    """``VirtualMachine`` を模したオブジェクト。"""
    runtime = _Namespace(powerState=power_state)
    return FakeManagedObject(moid, name=name, runtime=runtime, **attributes)


class _Namespace:
    """``SimpleNamespace`` 相当。属性アクセスだけを提供する。"""

    def __init__(self, **attributes: Any) -> None:
        self.__dict__.update(attributes)

    def __repr__(self) -> str:
        pairs = ", ".join(f"{key}={value!r}" for key, value in self.__dict__.items())
        return f"({pairs})"
