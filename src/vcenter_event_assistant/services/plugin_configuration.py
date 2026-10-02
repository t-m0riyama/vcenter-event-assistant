"""Declarative configuration validation and non-persisting setup actions."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
from uuid import UUID

from jsonschema import Draft202012Validator
from sqlalchemy import select
from vcenter_event_assistant_plugin_api import CollectionContext, VCenterTarget

from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.plugins.remote import RemoteCollectorPlugin
from vcenter_event_assistant.plugins.runtime import _connection_params, _open_connection
from vcenter_event_assistant.services.ssh_management import materialize_ssh

_TYPES = {"object", "array", "string", "number", "integer", "boolean"}
_WIDGETS = {"vcenter", "esxi-host", "ssh-connection"}
_KEYWORDS = {
    "$schema",
    "type",
    "properties",
    "items",
    "required",
    "enum",
    "title",
    "description",
    "default",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "additionalProperties",
    "x-vea-widget",
    "x-vea-ssh-connection",
    "x-vea-generated-id",
    "x-vea-vcenter-field",
    "x-vea-host-field",
}


def schema_error(schema):
    if not isinstance(schema, dict):
        return "設定定義がありません。従来のTOML設定を使用してください。"
    try:
        Draft202012Validator.check_schema(schema)

        def check(node):
            if set(node) - _KEYWORDS or node.get("type") not in _TYPES:
                raise ValueError()
            if node.get("x-vea-widget") and node["x-vea-widget"] not in _WIDGETS:
                raise ValueError()
            if "additionalProperties" in node and not isinstance(
                node["additionalProperties"], bool
            ):
                raise ValueError()
            if any(isinstance(value, (dict, list)) for value in node.get("enum", [])):
                raise ValueError()
            for child in node.get("properties", {}).values():
                check(child)
            if "items" in node:
                check(node["items"])

        check(schema)
    except Exception:
        return "この設定定義には未対応の項目があります。TOML設定を使用してください。"
    return None


def validate_values(config, schema):
    reason = schema_error(schema)
    if reason:
        raise ValueError(reason)
    errors = list(Draft202012Validator(schema).iter_errors(config))
    if errors:
        paths = [
            ".".join(str(p) for p in e.absolute_path) or "設定" for e in errors[:10]
        ]
        raise ValueError("入力を確認してください: " + ", ".join(paths))


def vcenter_ids(value, schema):
    if schema.get("x-vea-widget") == "vcenter" and value:
        yield UUID(str(value))
    if isinstance(value, dict):
        for name, child in schema.get("properties", {}).items():
            if name in value:
                yield from vcenter_ids(value[name], child)
    elif isinstance(value, list):
        for child in value:
            yield from vcenter_ids(child, schema.get("items", {}))


async def validate_targets(session, config, schema):
    for identifier in set(vcenter_ids(config, schema)):
        vc = await session.get(VCenter, identifier)
        if not vc or not vc.is_enabled:
            raise ValueError("有効なvCenterを選択してください。")


async def run_setup(settings, registration, config, action):
    schema = registration.plugin.manifest.configuration_schema
    validate_values(config, schema)
    async with session_scope(settings=settings) as session:
        await validate_targets(session, config, schema)
        identifiers = set(vcenter_ids(config, schema))
        if not identifiers:
            identifiers = set(
                (
                    await session.scalars(
                        select(VCenter.id).where(VCenter.is_enabled.is_(True))
                    )
                ).all()
            )
        targets = []
        for identifier in sorted(identifiers, key=str):
            vc = await session.get(VCenter, identifier)
            targets.append(
                (
                    VCenterTarget(
                        vc.id,
                        vc.name,
                        vc.host,
                        vc.protocol,
                        vc.port,
                        vc.username,
                        vc.verify_ssl,
                    ),
                    _connection_params(vc, settings),
                )
            )
    if not targets:
        raise ValueError("有効なvCenterを登録してください。")
    checks, samples, warnings = [], [], []
    for target, params in targets:
        async with materialize_ssh(settings, config, schema, target.id) as resolved:
            context = CollectionContext(
                target,
                resolved,
                None,
                lambda: _open_connection(params),
                settings.mock_mode,
            )
            plugin = registration.plugin
            timeout = registration.config.timeout_seconds
            try:
                if isinstance(plugin, RemoteCollectorPlugin):
                    result = await plugin.setup_with_connection(
                        context, params, action, timeout=timeout
                    )
                else:
                    async with asyncio.timeout(timeout):
                        result = asdict(await plugin.setup(context, action))
                checks.extend(result.get("checks", []))
                samples.extend(result.get("samples", [])[:20])
                warnings.extend(result.get("warnings", []))
            except Exception:
                checks.append(
                    {
                        "id": str(target.id),
                        "label": target.name,
                        "ok": False,
                        "message": "接続テストを完了できません。SSH設定・権限・タイムアウトを確認してください。",
                    }
                )
    result = {"checks": checks, "samples": samples[:20], "warnings": warnings}
    if len(json.dumps(result).encode()) > 256 * 1024:
        result["samples"] = []
        result["warnings"].append("表示上限を超えたためサンプルは省略しました。")
    return result
