"""Explicit sources; credentials never come from the vCenter API connection."""

from dataclasses import dataclass
from pathlib import Path
import re
from uuid import UUID

PRESETS = {
    "esxi": {
        kind: f"/var/run/log/{kind}.log" for kind in ("vmkernel", "hostd", "vpxa")
    },
    "vcenter": {"vpxd": "/var/log/vmware/vpxd/vpxd.log"},
}


@dataclass(frozen=True)
class Source:
    id: str
    vcenter_id: UUID
    product: str
    host: str
    port: int
    username: str
    private_key_file: str
    known_hosts_file: str


def sources_from_config(config):
    sources = []
    seen = set()
    for item in config.get("sources", []):
        source = Source(
            id=str(item["id"]),
            vcenter_id=UUID(str(item["vcenter_id"])),
            product=str(item["product"]),
            host=str(item["host"]),
            port=int(item.get("port", 22)),
            username=str(item["username"]),
            private_key_file=str(item["private_key_file"]),
            known_hosts_file=str(item["known_hosts_file"]),
        )
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", source.id) or source.id in seen:
            raise ValueError("source IDs must be unique stable identifiers")
        if source.product not in PRESETS or not 1 <= source.port <= 65535:
            raise ValueError("invalid product or SSH port")
        if not source.host or len(source.host) > 512 or not source.username:
            raise ValueError("host and SSH username are required")
        for name in (source.private_key_file, source.known_hosts_file):
            if not name or not Path(name).is_file():
                raise ValueError("SSH key and known_hosts files must exist")
        seen.add(source.id)
        sources.append(source)
    if not sources:
        raise ValueError("at least one explicit source is required")
    return sources
