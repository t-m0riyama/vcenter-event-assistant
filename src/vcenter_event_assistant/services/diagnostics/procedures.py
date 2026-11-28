"""組み込みの対応手順と、インシデントに紐付いた写しからの候補。"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import DiagnosticTarget, IncidentAlert, IncidentEvent
from vcenter_event_assistant.services.alerting.alert_eval_common import parse_event_pattern_context_key
from vcenter_event_assistant.services.event_patterns.definitions import BUILTIN_PATTERNS, EventPattern


@dataclass(frozen=True, slots=True)
class ProcedureStep:
    text: str
    command_ids: tuple[str, ...] = ()


_CHECK_HOST = ProcedureStep(
    "表示されたホスト名や FQDN を調査対象のホストと照合し、接続先の取り違えがないことを確認します。",
    ("esxi.hostname",),
)
_MANAGEMENT_NETWORK = ProcedureStep(
    "vSphere Client で管理用と確かめた VMkernel の IPv4 アドレスをこの一覧で確認し、その VMkernel から"
    " vCenter の管理用 IPv4 アドレスへの疎通を確認します。一覧には VMkernel の用途は出ません。"
    "vCenter の IPv4 アドレスは、vSphere Client か名前解決で確かめます。",
    ("esxi.vmk", "esxi.ping"),
)
_MANAGEMENT_AGENTS = ProcedureStep(
    "ホストの管理エージェント（hostd）と vCenter のエージェント（vpxa）の稼働状態を確認します。",
    ("esxi.hostd", "esxi.vpxa"),
)
_UPTIME = ProcedureStep(
    "ホストの稼働時間（マイクロ秒）と障害が起きた時刻を照合し、再起動があったかを確認します。",
    ("esxi.uptime",),
)
_APD_STEPS = (
    _CHECK_HOST,
    ProcedureStep("タイムラインと影響範囲マップで、同じ時間帯にほかのホストでも APD が起きていたかを確認します。"),
    ProcedureStep(
        "すべてのデバイスのパスの一覧から、イベントに出たデバイスのパスを探し、状態を確認します。"
        "パスの多い環境では、出力が 64 KiB で切れることがあります。",
        ("esxi.paths",),
    ),
    ProcedureStep("イベントやパスの一覧で確認したデバイス ID を指定し、デバイスの状態を確認します。", ("esxi.device",)),
    ProcedureStep("該当するパスが使うストレージアダプタ（HBA）の状態を確認します。", ("esxi.adapters",)),
)

BUILTIN_PROCEDURES = {
    "host-conn-flapping": (_CHECK_HOST, _MANAGEMENT_NETWORK, _MANAGEMENT_AGENTS, _UPTIME),
    "host-reconnect-failed": (_CHECK_HOST, _UPTIME, _MANAGEMENT_NETWORK, _MANAGEMENT_AGENTS),
    "apd-timeout": _APD_STEPS,
    "apd-repeated": _APD_STEPS,
    "pdl": (
        _CHECK_HOST,
        ProcedureStep("タイムラインで、同じ時間帯にほかのホストでも同じデバイスの PDL が起きていたかを確認します。"),
        ProcedureStep(
            "検知に出たデバイス ID を指定し、デバイスの状態を確認します。"
            "ID が拒まれた場合は、次の手順のパスの一覧から探します。",
            ("esxi.device",),
        ),
        ProcedureStep("該当デバイスのストレージパスの状態を確認します。", ("esxi.paths",)),
        ProcedureStep("該当するパスが使うストレージアダプタ（HBA）の状態を確認します。", ("esxi.adapters",)),
    ),
    "nic-link-flapping": (
        _CHECK_HOST,
        ProcedureStep("イベントで該当する vmnic を特定し、物理 NIC の一覧でリンク状態と速度を確認します。", ("esxi.nic",)),
        ProcedureStep("該当する vmnic を指定し、送受信のエラー数を確認します。", ("esxi.nic-stats",)),
        ProcedureStep("接続先のスイッチポートのログを調べ、同じ時間帯にリンクの切断と復帰が繰り返されていないか確認します。"),
    ),
    "ha-failover": (
        ProcedureStep("タイムラインで障害が検知されたホストと、HA によって再起動された VM を確認します。"),
        ProcedureStep(
            "前の段で特定した障害ホストに接続していることを、ホスト名と FQDN で確認します。",
            ("esxi.hostname",),
        ),
        ProcedureStep(
            "障害ホストの HA エージェント（FDM）の稼働状態を確認します。HA が無効のホストでは not found になります。",
            ("esxi.fdm",),
        ),
        ProcedureStep(
            "障害ホストの稼働時間と障害時刻から再起動の有無を調べ、現在のメンテナンスモードの状態を確認します。",
            ("esxi.uptime", "esxi.maintenance"),
        ),
    ),
    "vmotion-failures": (
        ProcedureStep("失敗した移行タスクの結果を開き、エラーの詳細と移行元・移行先のホストを確認します。"),
        ProcedureStep(
            "移行元と移行先のそれぞれで、前の段で特定したホストに接続していることを、ホスト名と FQDN で確認します。",
            ("esxi.hostname",),
        ),
        ProcedureStep(
            "移行元と移行先で、vSphere Client で vMotion 用と確かめた VMkernel の IPv4 アドレスを、この一覧で確認します。"
            "一覧には VMkernel の用途は出ません。",
            ("esxi.vmk",),
        ),
        ProcedureStep(
            "移行元の vMotion 用 VMkernel を指定し、移行先の vMotion 用 IPv4 アドレスへの疎通を確認します。"
            "vMotion 専用の TCP/IP スタックに置いた VMkernel では、この確認は失敗することがあります"
            "（vmkping に -S vmotion の指定が要るため）。",
            ("esxi.ping",),
        ),
    ),
}

_PATTERNS_BY_ID = {pattern.id: pattern for pattern in BUILTIN_PATTERNS}
_EVENT_TYPES_BY_PATTERN = {
    pattern.id: frozenset().union(*(step.event_types for step in pattern.steps)) for pattern in BUILTIN_PATTERNS
}


@dataclass(frozen=True, slots=True)
class ProcedureReason:
    kind: Literal["alert", "event"]
    link_id: int


@dataclass(frozen=True, slots=True)
class ProcedureTarget:
    id: UUID
    host_name: str


@dataclass(frozen=True, slots=True)
class ProcedureCandidate:
    pattern: EventPattern
    reasons: list[ProcedureReason]
    target: ProcedureTarget | None


async def read_procedure_candidates(session: AsyncSession, incident_id: UUID) -> list[ProcedureCandidate]:
    """写しを照合し、ホストが一意に分かる手順には登録済みの対象を添える。"""
    reasons: defaultdict[str, list[ProcedureReason]] = defaultdict(list)
    hosts: defaultdict[str, set[tuple[UUID, str]]] = defaultdict(set)
    alerts = (await session.execute(
        select(IncidentAlert.id, IncidentAlert.context_key)
        .where(IncidentAlert.incident_id == incident_id, IncidentAlert.rule_type == "event_pattern")
        .order_by(IncidentAlert.id)
    )).tuples()
    for link_id, context_key in alerts:
        parsed = parse_event_pattern_context_key(context_key)
        if parsed is None:
            continue
        vcenter_id, moid, pattern_id = parsed
        pattern = _PATTERNS_BY_ID.get(pattern_id)
        if pattern is None:
            continue
        reasons[pattern_id].append(ProcedureReason("alert", link_id))
        if "HostSystem" in pattern.target.entity_types:
            hosts[pattern_id].add((vcenter_id, moid))

    events = (await session.execute(
        select(IncidentEvent.id, IncidentEvent.event_type, IncidentEvent.vcenter_id,
               IncidentEvent.entity_type, IncidentEvent.entity_moid)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.id)
    )).tuples()
    for link_id, event_type, vcenter_id, entity_type, moid in events:
        for pattern_id, event_types in _EVENT_TYPES_BY_PATTERN.items():
            if event_type in event_types:
                reasons[pattern_id].append(ProcedureReason("event", link_id))
                if entity_type == "HostSystem" and moid:
                    hosts[pattern_id].add((vcenter_id, moid))

    # 複数のホストが該当したら、登録済みの対象が 1 台でも運用者に選んでもらう。
    host_by_pattern = {pattern_id: next(iter(keys)) for pattern_id, keys in hosts.items() if len(keys) == 1}
    targets = {}
    if host_by_pattern:
        rows = (await session.execute(
            select(DiagnosticTarget.vcenter_id, DiagnosticTarget.host_moid, DiagnosticTarget.id,
                   DiagnosticTarget.host_name)
            .where(tuple_(DiagnosticTarget.vcenter_id, DiagnosticTarget.host_moid).in_(set(host_by_pattern.values())))
        )).tuples()
        targets = {(vcenter_id, moid): ProcedureTarget(id, name) for vcenter_id, moid, id, name in rows}

    return [
        ProcedureCandidate(pattern, reasons[pattern.id], targets.get(host_by_pattern.get(pattern.id)))
        for pattern in BUILTIN_PATTERNS if pattern.id in reasons
    ]
