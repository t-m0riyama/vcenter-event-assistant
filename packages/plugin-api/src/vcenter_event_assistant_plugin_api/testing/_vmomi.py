"""pyVmomi の managed object を模した偽オブジェクト。

実際の vCenter を用意せずにコレクタの :meth:`sample` / :meth:`fetch` を動かすための
最小限の形だけを持つ。:class:`FakeServiceInstance` は ``CreateContainerView`` で作った
ビューを記録するので、``Destroy()`` の呼び忘れをテストで検出できる。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "FakeContainerView",
    "FakeEventCollector",
    "FakeManagedObject",
    "FakeServiceInstance",
    "ViewLeakError",
    "fake_datastore",
    "fake_event",
    "fake_host",
    "fake_vm",
]


class ViewLeakError(AssertionError):
    """``CreateContainerView`` / ``CreateCollectorForEvents`` の後始末が漏れている。

    本番では vCenter 側にビューやコレクタが残り続けるが、手元では何も起きないため
    気づけない。:func:`~vcenter_event_assistant_plugin_api.testing.run_collect` が
    これを送出する。
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
        events: list[Any] | tuple[Any, ...] = (),
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
        #: ``eventManager`` が返すイベント。``createdTime`` で絞られる。
        self.events: list[Any] = list(events)
        #: 作られたビュー。生成順に並ぶ。
        self.views: list[FakeContainerView] = []
        #: 作られたイベントコレクタ。生成順に並ぶ。
        self.event_collectors: list[FakeEventCollector] = []
        #: ``CreateCollectorForEvents`` に渡されたフィルタの記録。
        self.event_filters: list[Any] = []
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

    def assert_all_event_collectors_destroyed(self) -> None:
        """未破棄のイベントコレクタがあれば :class:`ViewLeakError` を送出する。"""
        leaked = [c for c in self.event_collectors if not c.destroyed]
        if leaked:
            raise ViewLeakError(
                f"{len(leaked)} event collector(s) were not destroyed; "
                "call DestroyCollector() in a finally block"
            )

    def assert_no_leaks(self) -> None:
        """ビューとイベントコレクタの後始末をまとめて検査する。"""
        self.assert_all_views_destroyed()
        self.assert_all_event_collectors_destroyed()

    def _create_event_collector(self, filter_spec: Any) -> FakeEventCollector:
        self.event_filters.append(filter_spec)
        collector = FakeEventCollector(_filter_events(self.events, filter_spec))
        self.event_collectors.append(collector)
        return collector

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
        self.eventManager = _FakeEventManager(service_instance)  # noqa: N815


class _FakeViewManager:
    def __init__(self, service_instance: FakeServiceInstance) -> None:
        self._si = service_instance

    def CreateContainerView(  # noqa: N802 - pyVmomi の命名に合わせる
        self, container: Any, type: Any, recursive: bool
    ) -> FakeContainerView:
        return self._si._create_view(container, type, recursive)


class _FakeEventManager:
    def __init__(self, service_instance: FakeServiceInstance) -> None:
        self._si = service_instance

    def CreateCollectorForEvents(  # noqa: N802 - pyVmomi の命名に合わせる
        self, filter: Any
    ) -> FakeEventCollector:
        return self._si._create_event_collector(filter)


class FakeEventCollector:
    """``ReadNextEvents`` でページングし、``DestroyCollector`` を記録するコレクタ。"""

    def __init__(self, events: list[Any]) -> None:
        self._remaining = list(events)
        self.destroy_count = 0
        #: ``ReadNextEvents`` に渡されたページサイズの記録。
        self.page_sizes: list[int] = []

    @property
    def destroyed(self) -> bool:
        return self.destroy_count > 0

    def ReadNextEvents(self, maxCount: int) -> list[Any]:  # noqa: N802, N803
        self.page_sizes.append(maxCount)
        page = self._remaining[:maxCount]
        del self._remaining[:maxCount]
        return page

    def DestroyCollector(self) -> None:  # noqa: N802 - pyVmomi の命名に合わせる
        self.destroy_count += 1


def _filter_events(events: list[Any], filter_spec: Any) -> list[Any]:
    """``EventFilterSpec.time`` の ``beginTime`` / ``endTime`` で絞る。

    アプリと同じく ``createdTime`` を見る。カーソルが本当に効いているかを
    テストで確かめられるようにするため、ここは手を抜かない。
    """
    time_filter = getattr(filter_spec, "time", None)
    begin = getattr(time_filter, "beginTime", None) if time_filter else None
    end = getattr(time_filter, "endTime", None) if time_filter else None
    selected = []
    for event in events:
        created = getattr(event, "createdTime", None)
        if created is not None:
            if begin is not None and created < begin:
                continue
            if end is not None and created > end:
                continue
        selected.append(event)
    return selected


class _FakeEvent:
    """イベントの基底。``type(event).__name__`` がイベント種別になる。

    アプリの ``normalize_event`` はクラス名を ``event_type`` として使うため、
    :func:`fake_event` は種別ごとに動的な型を作る。
    """

    def __init__(self, **attributes: Any) -> None:
        self.__dict__.update(attributes)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(key={getattr(self, 'key', None)!r})"


def fake_event(
    key: int = 1,
    *,
    event_type: str = "VmPoweredOnEvent",
    message: str = "Virtual machine powered on",
    created_time: Any | None = None,
    severity: str | None = "info",
    user_name: str | None = "svc-collector@vsphere.local",
    chain_id: int | None = None,
    entity: Any | None = None,
    **attributes: Any,
) -> Any:
    """vCenter のイベントを模したオブジェクト。

    ``key`` は vCenter が振る**自然キー**であり、``EventInput.vmware_key`` に
    そのまま使うべき値である（ハッシュで作ると重複排除で静かに消える）。

    ``event_type`` はクラス名になる。アプリはイベント種別を ``type(event).__name__``
    から取るため、文字列属性ではなく型を作る必要がある。
    """
    from vcenter_event_assistant_plugin_api.timeutils import now_utc

    cls = type(event_type, (_FakeEvent,), {})
    return cls(
        key=key,
        createdTime=created_time if created_time is not None else now_utc(),
        fullFormattedMessage=message,
        severity=severity,
        userName=user_name,
        chainId=chain_id if chain_id is not None else key,
        entity=entity,
        **attributes,
    )


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
