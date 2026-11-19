"""Small wheel fixture shared by the app and Compose plugin tests."""

from __future__ import annotations

import base64
import hashlib
import io
import zipfile

from vcenter_event_assistant_plugin_api.testing import stub_plugin_source

#: 配布物に入れるコレクタのソース。空のバッチを返すだけの最小実装。
#: plugin-api 側に 1 つだけ置いてあるので、テスト間で細部がずれない。
_COLLECTOR_MODULE = stub_plugin_source(emit_metric=False, next_cursor=None)


def _record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"{name},sha256={digest.decode()},{len(data)}"


def build_wheel(
    *,
    distribution: str = "example-collector",
    version: str = "0.1.0",
    with_entry_point: bool = True,
    requires: tuple[str, ...] = (),
    module_body: str | None = None,
) -> bytes:
    """最小限の PEP 427 wheel をメモリ上に組み立てる。"""
    module_name = "example_collector"
    dist_info = f"{distribution.replace('-', '_')}-{version}.dist-info"
    requires_lines = "".join(f"Requires-Dist: {item}\n" for item in requires)
    files: dict[str, bytes] = {
        f"{module_name}.py": (module_body or _COLLECTOR_MODULE).encode(),
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n"
            f"{requires_lines}"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    if with_entry_point:
        files[f"{dist_info}/entry_points.txt"] = (
            b"[vcenter_event_assistant.collectors]\n"
            b"example.temperature = example_collector:build_collector\n"
        )

    record = "\n".join(_record_line(name, data) for name, data in files.items())
    record += f"\n{dist_info}/RECORD,,\n"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr(f"{dist_info}/RECORD", record)
    return buffer.getvalue()
