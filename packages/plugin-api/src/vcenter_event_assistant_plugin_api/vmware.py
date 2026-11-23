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

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

from vcenter_event_assistant_plugin_api import limits

__all__ = [
    "EventEntityInput",
    "PyVmomiUnavailableError",
    "container_view",
    "datastore_is_accessible",
    "entity_priority",
    "event_entities",
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


@dataclass(frozen=True, slots=True)
class EventEntityInput:
    """vCenter イベントが指す管理対象。"""

    role: str
    position: int = 0
    entity_type: str | None = None
    entity_moid: str | None = None
    entity_name: str | None = None
    is_primary: bool = False


# pyVmomi 9.0.0.0 のインベントリの型と、それらを包む引数の型。
_MANAGED_ENTITY_TYPES = frozenset(
    {
        "ClusterComputeResource",
        "ComputeResource",
        "Datacenter",
        "Datastore",
        "DistributedVirtualPortgroup",
        "DistributedVirtualSwitch",
        "Folder",
        "HostSystem",
        "ManagedEntity",
        "Network",
        "OpaqueNetwork",
        "ResourcePool",
        "StoragePod",
        "VirtualApp",
        "VirtualMachine",
        "VmwareDistributedVirtualSwitch",
    }
)
_ENTITY_ARGUMENT_TYPES = frozenset(
    {
        "ComputeResourceEventArgument",
        "DatacenterEventArgument",
        "DatastoreEventArgument",
        "DvsEventArgument",
        "EntityEventArgument",
        "FolderEventArgument",
        "HostEventArgument",
        "ManagedEntityEventArgument",
        "NetworkEventArgument",
        "ResourcePoolEventArgument",
        "VmEventArgument",
    }
)

_PRIMARY_PRIORITIES = {
    "entity": (1, 0),
    "object": (1, 1),
    "managedObject": (1, 2),
    "vm": (2, 0),
    "ds": (4, 0),
    "net": (4, 1),
    "dvs": (4, 2),
    "host": (5, 0),
    "computeResource": (6, 0),
    "datacenter": (7, 0),
}
_CHILD_PRIORITIES = {
    role: index
    for index, role in enumerate(
        (
            "failedHost",
            "isolatedHost",
            "hostJoined",
            "hostLeft",
            "hostBackInSync",
            "hostMember",
            "hostOutOfSync",
            "datastore",
            "resourcePool",
            "referenceHost",
            "info.entity",
        )
    )
}
_FALLBACK_PREFIXES = ("source", "src", "old", "prev", "conflicted", "dest", "dst")
_FALLBACK_ROLES = {"parent", "newParent", "connectee"}


def entity_priority(entity: EventEntityInput) -> tuple[int, int, str, int]:
    """主な対象を選ぶ順に並べ替えるためのキーを返す。"""
    role = entity.role
    if role in _PRIMARY_PRIORITIES:
        tier, order = _PRIMARY_PRIORITIES[role]
    elif role in _FALLBACK_ROLES or role.startswith(_FALLBACK_PREFIXES):
        tier, order = 8, 0
    else:
        tier, order = 3, _CHILD_PRIORITIES.get(role, len(_CHILD_PRIORITIES))
    return tier, order, role, entity.position


def _instance_vars(value: Any) -> dict[str, Any]:
    try:
        attributes: dict[str, Any] = vars(value)
        return attributes
    except TypeError:
        return {}


def _property_names(value: Any) -> Iterable[str]:
    properties = getattr(value, "_GetPropertyList", None)
    if properties is not None:
        return (prop.name for prop in properties())
    return _instance_vars(value)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _managed_entity(
    value: Any,
    role: str,
    position: int,
    name: str | None,
) -> EventEntityInput | None:
    if not hasattr(value, "_moId"):
        return None
    # SOAP の参照から属性を読むと通信が起きる。名前はイベントのデータか偽オブジェクトの
    # インスタンス辞書から取る。
    entity_type = getattr(value, "_wsdlName", None)
    class_name = type(value).__name__
    if entity_type is None and class_name.startswith("vim."):
        entity_type = class_name.removeprefix("vim.")
    if entity_type is not None and entity_type not in _MANAGED_ENTITY_TYPES:
        return None
    raw_moid = value._moId
    entity_moid = str(raw_moid) if raw_moid is not None else ""
    if not entity_moid and name is None:
        return None
    return EventEntityInput(
        role,
        position,
        entity_type,
        entity_moid or None,
        name,
    )


def _argument_entity(value: Any, role: str, position: int) -> EventEntityInput | None:
    if hasattr(value, "_moId"):
        return None
    argument_type = getattr(value, "_wsdlName", type(value).__name__.rsplit(".", 1)[-1])
    if argument_type not in _ENTITY_ARGUMENT_TYPES:
        return None
    name = _text(getattr(value, "name", None))
    for field in _property_names(value):
        ref = getattr(value, field, None)
        if hasattr(ref, "_moId"):
            return _managed_entity(ref, role, position, name)
    if name is None:
        return None
    return EventEntityInput(role, position, entity_name=name)


def _event_ex_object(event: Any) -> EventEntityInput | None:
    entity_moid = _text(getattr(event, "objectId", None))
    name = _text(getattr(event, "objectName", None))
    if entity_moid is None and name is None:
        return None

    object_type = getattr(event, "objectType", None)
    if isinstance(object_type, str):
        entity_type = object_type.removeprefix("vim.") if object_type else None
    elif isinstance(object_type, type):
        entity_type = _text(getattr(object_type, "_wsdlName", None))
    else:
        entity_type = None
    if entity_type is not None and entity_type not in _MANAGED_ENTITY_TYPES:
        return None
    return EventEntityInput(
        "object",
        entity_type=entity_type,
        entity_moid=entity_moid,
        entity_name=name,
    )


def _fit_entity_limits(entity: EventEntityInput, *, primary: bool) -> EventEntityInput:
    entity_type = entity.entity_type
    entity_moid = entity.entity_moid
    name = entity.entity_name
    return replace(
        entity,
        entity_type=entity_type
        if entity_type and len(entity_type) <= limits.MAX_EVENT_ENTITY_TYPE
        else None,
        entity_moid=entity_moid
        if entity_moid and len(entity_moid) <= limits.MAX_ENTITY_MOID
        else None,
        entity_name=limits.truncate(name, limits.MAX_ENTITY_NAME)
        if name is not None
        else None,
        is_primary=primary,
    )


def event_entities(event: Any) -> tuple[EventEntityInput, ...]:
    """イベントの対象をすべて返す。空でなければ、is_primary が真のものがちょうど 1 つある。"""
    if hasattr(event, "_moId"):
        return ()
    entities: list[EventEntityInput] = []
    managed_entities: list[EventEntityInput] = []
    if (
        getattr(event, "_wsdlName", type(event).__name__.rsplit(".", 1)[-1])
        == "EventEx"
    ):
        obj = _event_ex_object(event)
        if obj is not None:
            entities.append(obj)

    for role in _property_names(event):
        if role in {"reason", "fault"}:
            continue
        value = getattr(event, role, None)
        items = value if isinstance(value, (list, tuple)) else (value,)
        for position, item in enumerate(items):
            if item is None:
                continue
            role_name = role
            if hasattr(item, "_moId"):
                name = _text(getattr(event, f"{role}Name", None))
            elif role == "connectee":
                item, name = getattr(item, "connectedEntity", None), None
            elif role == "info":
                item, name = (
                    getattr(item, "entity", None),
                    _text(getattr(item, "entityName", None)),
                )
                role_name = "info.entity"
            else:
                if role == "hostOutOfSync":
                    item = getattr(item, "outOfSyncHost", None)
                argument = _argument_entity(item, role, position)
                if argument is not None:
                    entities.append(argument)
                continue
            # 管理対象の name プロパティは vCenter への問い合わせを起こす。
            name = name or _text(_instance_vars(item).get("name"))
            managed = _managed_entity(item, role_name, position, name)
            if managed is not None:
                managed_entities.append(managed)

    # moid を列長に合わせる前に、別の役割で得られた名前を補う。
    names_by_moid: dict[str, str] = {}
    for entity in sorted(entities + managed_entities, key=entity_priority):
        if entity.entity_moid is not None and entity.entity_name is not None:
            names_by_moid.setdefault(entity.entity_moid, entity.entity_name)
    for entity in managed_entities:
        if entity.entity_name is None and entity.entity_moid in names_by_moid:
            entity = replace(entity, entity_name=names_by_moid[entity.entity_moid])
        entities.append(entity)
    entities.sort(key=entity_priority)
    return tuple(
        _fit_entity_limits(entity, primary=index == 0)
        for index, entity in enumerate(entities)
    )


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
