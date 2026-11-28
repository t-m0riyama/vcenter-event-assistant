"""診断コマンドの雛形の確認と引数の組み立て。"""

import re
import shlex
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address

from vcenter_event_assistant.device_ids import DEVICE_ID_PATTERN

_PARAMETER_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
_PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
_PARAMETER_PATTERNS = {
    "vmnic": re.compile(r"vmnic[0-9]{1,3}"),
    "vmk": re.compile(r"vmk[0-9]{1,3}"),
    "device": DEVICE_ID_PATTERN,
}
PARAMETER_TYPES = ("vmnic", "vmk", "ipv4", "device")


class TemplateError(ValueError):
    def __init__(self, reason: str, parameter: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.parameter = parameter


class ParameterError(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("引数を確認してください。")
        self.errors = errors


def validate_template(
    template: str, param_definitions: Sequence[Mapping[str, str]]
) -> None:
    if any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in template):
        raise TemplateError("control_character")
    if len(param_definitions) > 8:
        raise TemplateError("too_many_parameters")

    names: set[str] = set()
    for definition in param_definitions:
        name = definition["name"]
        if not _PARAMETER_NAME.fullmatch(name):
            raise TemplateError("invalid_parameter_name", name)
        if name in names:
            raise TemplateError("duplicate_parameter", name)
        if definition["type"] not in PARAMETER_TYPES:
            raise TemplateError("unknown_parameter_type", name)
        names.add(name)

    used: set[str] = set()
    for match in _PLACEHOLDER.finditer(template):
        name = match[1]
        if name not in names:
            raise TemplateError("undefined_parameter", name)
        prefix = template[match.start() - 1] if match.start() else ""
        if prefix == "$":
            raise TemplateError("dollar_prefix", name)
        if prefix == "\\":
            raise TemplateError("backslash_prefix", name)
        used.add(name)
    for definition in param_definitions:
        if definition["name"] not in used:
            raise TemplateError("unused_parameter", definition["name"])


def normalize_parameter(kind: str, value: str) -> str:
    if kind == "ipv4":
        return str(IPv4Address(value))
    pattern = _PARAMETER_PATTERNS.get(kind)
    if pattern is None or not pattern.fullmatch(value):
        raise ValueError("引数の値を確認してください。")
    return value


def render_command(
    template: str,
    param_definitions: Sequence[Mapping[str, str]],
    params: Mapping[str, str],
) -> str:
    """保存済みの雛形を再検証し、照合・正規化した引数を差し込む。"""
    validate_template(template, param_definitions)
    types = {definition["name"]: definition["type"] for definition in param_definitions}
    errors = {name: "unknown" for name in params.keys() - types.keys()}
    quoted: dict[str, str] = {}
    for name, kind in types.items():
        if name not in params:
            errors[name] = "missing"
            continue
        try:
            quoted[name] = shlex.quote(normalize_parameter(kind, params[name]))
        except ValueError:
            errors[name] = "invalid_value"
    if errors:
        raise ParameterError(errors)
    return _PLACEHOLDER.sub(lambda match: quoted[match[1]], template)


@dataclass(frozen=True)
class BuiltinCommand:
    id: str
    product: str
    title: str
    description: str
    template: str
    param_definitions: tuple[dict[str, str], ...]
    mock_stdout: str


def _builtin(
    id: str,
    title: str,
    description: str,
    template: str,
    mock_stdout: str,
    *parameters: str,
) -> BuiltinCommand:
    return BuiltinCommand(
        id,
        id.split(".")[0],
        title,
        description,
        template,
        tuple({"name": name, "type": name} for name in parameters),
        mock_stdout + "\n",
    )


BUILTIN_COMMANDS = {
    command.id: command
    for command in (
        _builtin(
            "esxi.hostname",
            "ホスト名",
            "ドメイン名、FQDN、ホスト名の 3 行を表示します。",
            "esxcli system hostname get",
            "   Domain Name: example.com\n   Fully Qualified Domain Name: esx01.example.com\n   Host Name: esx01",
        ),
        _builtin(
            "esxi.version",
            "版とビルド",
            "製品、版、ビルド、更新、パッチの 5 行を表示します。",
            "esxcli system version get",
            "   Product: VMware ESXi\n   Version: 8.0.3\n   Build: Releasebuild-24262298\n   Update: 3\n   Patch: 0",
        ),
        _builtin(
            "esxi.uptime",
            "稼働時間",
            "起動してからの時間をマイクロ秒の数字 1 つで表示します。",
            "esxcli system stats uptime get",
            "1643109302446",
        ),
        _builtin(
            "esxi.maintenance",
            "メンテナンスモード",
            "Disabled または Enabled を表示します。",
            "esxcli system maintenanceMode get",
            "Disabled",
        ),
        _builtin(
            "esxi.hostd",
            "管理エージェント",
            "hostd の稼働状態を表示します。",
            "/etc/init.d/hostd status",
            "hostd is running.",
        ),
        _builtin(
            "esxi.vpxa",
            "vCenter エージェント",
            "vpxa の稼働状態を表示します。",
            "/etc/init.d/vpxa status",
            "vpxa is running",
        ),
        _builtin(
            "esxi.fdm",
            "HA エージェント",
            "HA が無効のホストでは not found（終了コード 127）になります。",
            "/etc/init.d/vmware-fdm status",
            "vmware-fdm is running",
        ),
        _builtin(
            "esxi.vmk",
            "VMkernel のアドレス",
            "VMkernel ごとの IPv4 アドレス、ネットマスク、ゲートウェイなどを表示します。",
            "esxcli network ip interface ipv4 get",
            "Name  IPv4 Address  IPv4 Netmask   IPv4 Broadcast  Address Type  Gateway     DHCP DNS\n"
            "vmk0  192.0.2.10    255.255.255.0  192.0.2.255     STATIC        192.0.2.1   false",
        ),
        _builtin(
            "esxi.ping",
            "VMkernel の疎通",
            "指定した VMkernel から IPv4 へ ICMP を 3 回送ります。約 3 秒で応答と統計を表示します。",
            "vmkping -c 3 -I {{vmk}} {{ipv4}}",
            "64 bytes from 192.0.2.20: icmp_seq=0 ttl=64 time=0.3 ms\n"
            "64 bytes from 192.0.2.20: icmp_seq=1 ttl=64 time=0.4 ms\n"
            "64 bytes from 192.0.2.20: icmp_seq=2 ttl=64 time=0.3 ms\n"
            "3 packets transmitted, 3 packets received, 0% packet loss",
            "vmk",
            "ipv4",
        ),
        _builtin(
            "esxi.nic",
            "NIC の一覧",
            "物理 NIC ごとのリンクの状態、速度、MTU などを表示します。",
            "esxcli network nic list",
            "Name    Link  Speed  MTU\nvmnic0  Up    10000  1500",
        ),
        _builtin(
            "esxi.nic-stats",
            "NIC の統計",
            "送受信のパケット数、バイト数、種類別のエラー数を表示します。",
            "esxcli network nic stats get -n {{vmnic}}",
            "Packets received: 4529\nPackets sent: 3861\nReceive errors: 0\nTransmit errors: 0",
            "vmnic",
        ),
        _builtin(
            "esxi.paths",
            "ストレージのパス",
            "パス 1 本につき約 800 バイトです。80 本を超える環境では 64 KiB で出力が切れます。",
            "esxcli storage core path list",
            "Runtime Name: vmhba64:C0:T0:L0\nState: active",
        ),
        _builtin(
            "esxi.device",
            "ストレージのデバイス",
            "naa. や t10.NVMe などのデバイス ID を指定します。"
            "存在しない ID は Unable to find device with name と表示し、終了コード 1 になります。",
            "esxcli storage core device list -d {{device}}",
            "naa.6000000000000001\n   Display Name: Example Disk\n   Status: on",
            "device",
        ),
        _builtin(
            "esxi.adapters",
            "ストレージのアダプタ",
            "HBA ごとに 1 行でアダプタの状態を表示します。",
            "esxcli storage core adapter list",
            "HBA Name  Driver     Link State\nvmhba64   iscsi_vmk  link-up",
        ),
        _builtin(
            "vcenter.hostname",
            "ホスト名",
            "FQDN を 1 行で表示します。",
            "hostname -f",
            "vc01.example.com",
        ),
        _builtin(
            "vcenter.services",
            "vCenter のサービス",
            "Running と Stopped に分けてサービス名を表示します。"
            "vCenter HA を構成していなければ vmware-vcha が Stopped に出るのは正常です。",
            "service-control --status --all",
            "\nRunning:\n vmware-vpxd vmware-vpostgres\nStopped:\n vmware-vcha",
        ),
        _builtin(
            "vcenter.disk",
            "ディスクの空き",
            "ファイルシステムやコンテナごとの空きを表示します。",
            "df -h",
            "Filesystem             Size  Used Avail Use% Mounted on\n/dev/mapper/log_vg-log   50G  6.5G   42G  14% /storage/log",
        ),
        _builtin(
            "vcenter.memory",
            "メモリ",
            "メモリとスワップの使用状況を MiB で表示します。",
            "free -m",
            "               total        used        free      shared  buff/cache   available\n"
            "Mem:           16384        9728        2048         128        4608        6144",
        ),
        _builtin(
            "vcenter.uptime",
            "稼働時間と負荷",
            "稼働時間とロードアベレージを表示します。",
            "uptime",
            " 09:20:00 up 19 days,  0 users,  load average: 0.18, 0.21, 0.17",
        ),
    )
}
