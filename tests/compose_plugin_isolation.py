"""Exercise the official Compose deployments against real uv and Unix sockets."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import socket
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from plugin_wheel_fixture import build_wheel
from vcenter_event_assistant_plugin_api.testing import stub_plugin_source

_INSTALLS = "/api/plugins/installed"
_FILENAME = "example_collector-0.1.0-py3-none-any.whl"
_SECRET = "issue-274-test-index-credential"


def make_sdist(wheel: bytes, *, record_attempt: bool = False) -> bytes:
    backend = f"""
import base64
from pathlib import Path
import os

def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    if {record_attempt!r}:
        Path('/tmp/source-only-build-attempt').touch()
    assert 'UV_DEFAULT_INDEX' not in os.environ
    assert 'VEA_SMOKE_APP_SECRET' not in os.environ
    name = {_FILENAME!r}
    Path(wheel_directory, name).write_bytes(base64.b64decode({base64.b64encode(wheel).decode()!r}))
    return name
"""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content in {
            "backend.py": backend,
            "pyproject.toml": '[build-system]\nrequires = []\nbuild-backend = "backend"\nbackend-path = ["."]\n',
        }.items():
            blob = content.encode()
            member = tarfile.TarInfo(f"example_collector-0.1.0/{name}")
            member.size = len(blob)
            archive.addfile(member, io.BytesIO(blob))
    return output.getvalue()


def http(port: int, method: str, path: str, payload=None, headers=None):
    request = Request(
        f"http://127.0.0.1:{port}{path}", data=payload, headers=headers or {}, method=method
    )
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, json.load(response)


def wait_for(predicate, *, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = predicate()
            if result:
                return result
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.5)
    raise AssertionError("service did not reach the expected state")


def start_index(compose, wheel: bytes) -> None:
    # The loopback registry is visible to the installer, without opening a port
    # or attaching the worker/builder to its network.
    broken_wheel = build_wheel(
        distribution="with-source-dependency", requires=("source-only==0.1.0",)
    )
    files = {
        _FILENAME: wheel,
        "with_source_dependency-0.1.0-py3-none-any.whl": broken_wheel,
        "source_only-0.1.0.tar.gz": make_sdist(wheel, record_attempt=True),
    }
    listings = {
        "example-collector": _FILENAME,
        "with-source-dependency": "with_source_dependency-0.1.0-py3-none-any.whl",
        "source-only": "source_only-0.1.0.tar.gz",
    }
    auth = base64.b64encode(f"test:{_SECRET}".encode()).decode()
    encoded = {name: base64.b64encode(data).decode() for name, data in files.items()}
    script = f"""
import base64
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.stderr = open("/tmp/index-test.log", "w", buffering=1)

class Index(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self.headers.get('Authorization') != 'Basic {auth}':
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm=pytest')
            self.end_headers()
            return
        for command in Path('/proc').glob('[0-9]*/cmdline'):
            try:
                argv = command.read_bytes().split(b'\\0')
            except OSError:
                continue
            if argv and argv[0].rsplit(b'/', 1)[-1] == b'uv':
                assert base64.b64decode({auth!r}).split(b':', 1)[1] not in b' '.join(argv)
        name = self.path.rstrip('/').rsplit('/', 1)[-1]
        files = {encoded!r}
        listings = {listings!r}
        if name in listings:
            data = ('<a href="/files/' + listings[name] + '">' + listings[name] + '</a>').encode()
            content_type = 'text/html'
        elif name in files:
            data = base64.b64decode(files[name])
            content_type = 'application/octet-stream'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

HTTPServer(('127.0.0.1', 8765), Index).serve_forever()
"""
    compose("exec", "-d", "plugin-installer", "python", "-c", script)
    compose(
        "exec", "-T", "plugin-installer", "python", "-c",
        "import socket, time\n"
        "for _ in range(30):\n"
        "    try:\n"
        "        socket.create_connection(('127.0.0.1', 8765), timeout=1).close()\n"
        "        break\n"
        "    except OSError:\n"
        "        time.sleep(.2)\n"
        "else:\n"
        "    raise SystemExit('test registry did not start')\n",
    )


def smoke(database: str, image: str | None) -> None:
    project = f"vea274-{database}-{uuid.uuid4().hex[:8]}"
    collector = stub_plugin_source(emit_metric=False, next_cursor=None).replace(
        "    async def collect(self, context):\n",
        """    async def collect(self, context):
        from pathlib import Path
        for field, expected in (
            ('private_key_file', b'fixture key'),
            ('known_hosts_file', b'fixture host key'),
        ):
            path = Path(context.config[field])
            assert path.read_bytes() == expected
            assert path.stat().st_mode & 0o777 == 0o400
""",
    )
    wheel = build_wheel(module_body=collector)
    sdist = make_sdist(wheel)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="vea274-compose-") as temp:
        config = Path(temp) / "app.env"
        config.write_text(
            "VEA_AUTH_ENABLED=false\nSCHEDULER_ENABLED=false\n"
            "VEA_PLUGIN_MANAGEMENT_ENABLED=true\nVEA_PLUGIN_ALLOW_INDEX_INSTALL=true\n"
            f"VEA_PLUGIN_INDEX_URL=http://test:{_SECRET}@127.0.0.1:8765/simple\n"
            "VEA_SMOKE_APP_SECRET=vea274-app-secret\n",
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "POSTGRES_PASSWORD": "vea274-local-test",
            "VEA_ENV_FILE": str(config),
            "UVICORN_PORT": str(port),
        }
        if image:
            env["VEA_IMAGE"] = image
        command = ["docker", "compose", "-p", project, "-f", f"docker-compose.{database}.yml"]

        def compose(*args, capture=False):
            return subprocess.run(
                [*command, *args], check=True, env=env, text=True, capture_output=capture
            ).stdout

        def installed(distribution="example-collector"):
            status, result = http(port, "GET", _INSTALLS)
            assert status == 200, result
            return next((row for row in result["plugins"] if row["distribution"] == distribution), {})

        def finished(distribution="example-collector"):
            def terminal():
                row = installed(distribution)
                return row if row.get("status") in ("installed", "failed") else None

            return wait_for(terminal)

        def upload(name, data):
            boundary = "vea274-upload"
            content = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
            status, result = http(
                port, "POST", f"{_INSTALLS}/upload", content,
                {"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            assert status == 202, result
            return finished()

        try:
            if not image:
                compose("build", "app")
            compose(
                "run", "--rm", "--no-deps", "--entrypoint", "sh",
                "-v", f"{project}_vea_data:/legacy-data", "app", "-ec",
                "mkdir -p /legacy-data/plugins/manual/0.1 /legacy-data/plugins/.staging/partial; "
                "printf manual > /legacy-data/plugins/manual/0.1/marker",
            )
            compose("run", "--rm", "--no-deps", "plugin-migrate")
            compose("run", "--rm", "--no-deps", "plugin-migrate")
            compose("up", "-d", "--no-build")
            wait_for(lambda: http(port, "GET", "/health")[0] == 200)
            start_index(compose, wheel)
            compose("exec", "-T", "-e", "UV_OFFLINE=true", "app", "python", "-c", """
import asyncio
from vcenter_event_assistant.plugins.installer import PluginInstallError, install_plugin
from vcenter_event_assistant.settings import get_settings

try:
    asyncio.run(install_plugin(get_settings(), source='example-collector==0.1.0', from_index=True))
except PluginInstallError:
    pass
else:
    raise AssertionError('the offline install fetched a package')
""")
            compose("exec", "-T", "plugin-installer", "test", "!", "-s", "/tmp/index-test.log")

            database_endpoints = []
            if database == "postgres":
                database_endpoints.extend(
                    f"{address}:5432"
                    for address in compose(
                        "exec", "-T", "postgres", "hostname", "-i", capture=True,
                    ).split()
                )
            compose(
                "exec", "-T", "plugin-worker", "python", "-c",
                "import glob, os, socket, sys\n"
                "assert os.getuid() == 1001\n"
                "assert not os.environ.get('VEA_SMOKE_APP_SECRET')\n"
                "assert not glob.glob('/data/vea.db*') and not os.path.exists('/app/.env')\n"
                "assert not os.path.exists('/sockets/installer/service.sock')\n"
                "assert not os.path.exists('/sockets/builder/service.sock')\n"
                "for host in ('app', 'postgres'):\n"
                "    try: socket.getaddrinfo(host, 8000)\n"
                "    except socket.gaierror: pass\n"
                "    else: raise AssertionError(host)\n"
                "for endpoint in sys.argv[1:]:\n"
                "    host, port = endpoint.rsplit(':', 1)\n"
                "    try: socket.create_connection((host, int(port)), timeout=.5).close()\n"
                "    except OSError: pass\n"
                "    else: raise AssertionError(endpoint)\n"
                "with socket.socket(socket.AF_UNIX) as own_socket:\n"
                "    own_socket.settimeout(2)\n"
                "    own_socket.connect('/sockets/worker/service.sock')\n"
                "    assert own_socket.recv(1) == b''\n"
                "path, = glob.glob('/data/plugins/.generations/*/marker')\n"
                "assert open(path).read() == 'manual'\n"
                "try: open(path, 'w')\n"
                "except OSError: pass\n"
                "else: raise AssertionError('worker wrote a published file')\n",
                *database_endpoints,
            )

            assert upload(_FILENAME, wheel)["status"] == "installed"
            assert upload("example_collector-0.1.0.tar.gz", sdist)["status"] == "installed"
            assert upload(_FILENAME, build_wheel(with_entry_point=False))["status"] == "failed"
            status, result = http(port, "POST", "/api/plugins/collectors/reload")
            assert status == 200, result
            status, result = http(port, "GET", "/api/plugins/collectors")
            assert status == 200 and any(
                row["id"] == "example.temperature" for row in result["collectors"]
            ), result
            compose("exec", "-T", "app", "python", "-c", """
import asyncio
from uuid import UUID
from vcenter_event_assistant.plugins.remote import _verify_worker_listener, build_remote_plugins
from vcenter_event_assistant.plugins.request_files import encode_file
from vcenter_event_assistant.plugins.wire import ConnectionParams
from vcenter_event_assistant_plugin_api import CollectionContext, VCenterTarget

plugins, errors = build_remote_plugins('/data/plugins')
collector, = [plugin for plugin in plugins if plugin.manifest.id == 'example.temperature']

async def collect():
    await _verify_worker_listener()
    target = VCenterTarget(UUID(int=1), 'fixture', 'fixture.example', 'https', 443, 'fixture', True)
    config = {'private_key_file': '/app-only/key', 'known_hosts_file': '/app-only/known_hosts'}
    context = CollectionContext(target, config, None, lambda: None)
    files = {
        config['private_key_file']: encode_file(b'fixture key'),
        config['known_hosts_file']: encode_file(b'fixture host key'),
    }
    connection = ConnectionParams('fixture.example', 'https', 443, 'fixture', 'fixture', True)
    await collector.start()
    try:
        batch = await collector.collect_with_connection(
            context, connection, timeout=10, worker_files=files,
        )
        assert not batch.metrics
    finally:
        await collector.stop()

asyncio.run(collect())
""")

            for distribution, expected in (
                ("example-collector", "installed"), ("with-source-dependency", "failed")
            ):
                status, result = http(
                    port, "POST", _INSTALLS,
                    json.dumps({"requirement": f"{distribution}==0.1.0"}).encode(),
                    {"Content-Type": "application/json"},
                )
                assert status == 202, result
                row = finished(distribution)
                assert row["status"] == expected, row
            compose("exec", "-T", "plugin-installer", "test", "!", "-e", "/tmp/source-only-build-attempt")
            assert _SECRET not in compose("logs", "--no-color", capture=True)

            compose("restart", "app")
            wait_for(lambda: http(port, "GET", "/health")[0] == 200)
            assert installed()["status"] == "installed"
            assert http(port, "DELETE", f"{_INSTALLS}/example-collector")[0] == 200
            assert http(port, "POST", "/api/plugins/collectors/reload")[0] == 200
            compose("stop", "plugin-worker")
            assert http(port, "POST", "/api/plugins/collectors/reload")[0] == 503
            assert http(port, "GET", "/health")[0] == 200
        except Exception:
            compose("logs", "--no-color", "--tail", "120")
            try:
                compose("exec", "-T", "plugin-installer", "cat", "/tmp/index-test.log")
            except subprocess.CalledProcessError:
                pass
            for log in ("app.log", "uvicorn.log"):
                destination = Path(temp) / log
                try:
                    compose("cp", f"app:/var/log/vea/{log}", str(destination))
                except subprocess.CalledProcessError:
                    continue
                print(destination.read_text(errors="replace")[-8000:].replace(_SECRET, "[redacted]"))
            raise
        finally:
            compose("down", "--volumes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", choices=("sqlite", "postgres"))
    parser.add_argument("--image")
    args = parser.parse_args()
    smoke(args.database, args.image)
