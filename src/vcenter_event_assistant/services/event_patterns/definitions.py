"""組み込みの障害パターン。"""

from dataclasses import dataclass
from typing import Literal

PatternLevel = Literal["critical", "error", "warning"]
PatternKind = Literal["repeat", "sequence"]


@dataclass(frozen=True, slots=True)
class TargetRule:
    roles: frozenset[str]
    entity_types: frozenset[str]


@dataclass(frozen=True, slots=True)
class PatternStep:
    event_types: frozenset[str]


@dataclass(frozen=True, slots=True)
class EventPattern:
    id: str
    title: str
    description: str
    level: PatternLevel
    kind: PatternKind
    steps: tuple[PatternStep, ...]
    target: TargetRule
    within_minutes: int
    min_count: int | None = None
    collapse_seconds: int = 0


def _step(*event_types: str) -> PatternStep:
    return PatternStep(frozenset(event_types))


_HOST = TargetRule(frozenset({"host", "object", "managedObject"}), frozenset({"HostSystem"}))
_CLUSTER = TargetRule(frozenset({"computeResource"}), frozenset({"ClusterComputeResource"}))
_HOST_CONNECTION_LOST = _step("vim.event.HostConnectionLostEvent")
_APD_START = _step("esx.problem.storage.apd.start")

BUILTIN_PATTERNS = (
    EventPattern(
        id="host-conn-flapping",
        title="ホストの切断の繰り返し",
        description="同じホストと vCenter の接続が短時間に繰り返し切れています。まず管理ネットワークの疎通とホストの管理エージェントの状態を確認してください。",
        level="error",
        kind="repeat",
        steps=(_HOST_CONNECTION_LOST,),
        target=_HOST,
        within_minutes=60,
        min_count=3,
    ),
    EventPattern(
        id="host-reconnect-failed",
        title="ホストの切断後の再接続の失敗",
        description="ホストとの接続が切れたあと、vCenter からの再接続に失敗しています。まずホストの稼働状態と管理ネットワークの疎通を確認してください。",
        level="error",
        kind="sequence",
        steps=(_HOST_CONNECTION_LOST, _step("vim.event.HostReconnectionFailedEvent")),
        target=_HOST,
        within_minutes=30,
    ),
    EventPattern(
        id="apd-timeout",
        title="APD のタイムアウト",
        description="ホストからストレージデバイス（LUN）への全パスが失われ、APD がタイムアウトに達しました。まず同じ時間帯のほかのホストの APD とストレージのパスを確認してください。",
        level="critical",
        kind="sequence",
        steps=(_APD_START, _step("esx.problem.storage.apd.timeout")),
        target=_HOST,
        within_minutes=10,
    ),
    EventPattern(
        id="apd-repeated",
        title="APD の繰り返し",
        description="同じホストでストレージデバイス（LUN）への全パスが繰り返し失われています。まず同じ時間帯のほかのホストの APD とストレージのパスを確認してください。",
        level="error",
        kind="repeat",
        steps=(_APD_START,),
        target=_HOST,
        within_minutes=60,
        min_count=2,
        collapse_seconds=120,
    ),
    EventPattern(
        id="nic-link-flapping",
        title="NIC のリンクの不安定",
        description="同じホストの物理 NIC でリンクダウンが繰り返し起きています。まず該当する vmnic と接続先のスイッチポートのログを確認してください。",
        level="warning",
        kind="repeat",
        steps=(_step("esx.problem.net.vmnic.linkstate.down"),),
        target=_HOST,
        within_minutes=30,
        min_count=3,
        collapse_seconds=60,
    ),
    EventPattern(
        id="ha-failover",
        title="HA によるフェイルオーバー",
        description="HA がホストの障害を検知したあと、同じクラスタで VM が再起動しています。まず再起動した VM と障害ホストの状態を確認してください。",
        level="critical",
        kind="sequence",
        steps=(
            _step("vim.event.DasHostFailedEvent", "com.vmware.vc.HA.DasHostFailedEvent"),
            _step("com.vmware.vc.ha.VmRestartedByHAEvent", "vim.event.VmRestartedOnAlternateHostEvent"),
        ),
        target=_CLUSTER,
        within_minutes=30,
    ),
    EventPattern(
        id="vmotion-failures",
        title="vMotion の連続失敗",
        description="同じホストに関係する vMotion が繰り返し失敗しています。まず失敗した移行タスクの詳細と、移行元・移行先の vMotion ネットワークを確認してください。",
        level="warning",
        kind="repeat",
        steps=(_step("vim.event.VmFailedMigrateEvent"),),
        target=_HOST,
        within_minutes=60,
        min_count=3,
    ),
)
