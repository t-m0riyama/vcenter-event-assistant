"""Fixed read-only commands for BusyBox ESXi and Photon vCenter shells."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
import re
import shlex

from vcenter_event_assistant_plugin_api.logs import get_plugin_logger
from vcenter_event_assistant_plugin_api.network import resolve_ssh_address

from .config import PRESETS

logger = get_plugin_logger("vea.remote.logs")


class ShellAccessError(RuntimeError):
    """Authenticated vCenter session cannot execute a temporary Bash command."""


class LogFileChanged(ValueError):
    """A snapshot became invalid; retry from the unchanged committed cursor."""

    def __init__(self, message, *, bytes_read=0):
        super().__init__(message)
        self.bytes_read = bytes_read


@dataclass(frozen=True)
class RemoteFile:
    path: str
    identity: str
    size: int
    modified: int
    prefix: bytes
    active: bool
    disk_size: int = 0
    metadata_only: bool = False


def same_archived_file(state, file):
    return (
        state.get("done")
        and state.get("identity") == file.identity
        and state.get("disk_size") == file.disk_size
        and state.get("modified") == file.modified
    )


class SSHReader:
    def __init__(self, connection, source):
        self.connection = connection
        self.source = source
        self._shell_prefix = None
        self._validated_gzip = set()

    async def _vcenter_shell(self):
        import asyncssh

        if self._shell_prefix is not None:
            return self._shell_prefix
        # Probe with a fixed, read-only command; never retry a failed log read.
        # A Bash login has no `shell` command, while appliancesh requires it.
        probe = "printf VEA_REMOTE_LOG_SHELL_READY"
        for prefix in ("shell /bin/bash -c", "/bin/bash -c"):
            try:
                result = await self.connection.run(
                    f"{prefix} {shlex.quote(probe)}",
                    encoding=None, check=True, timeout=8,
                )
            except asyncssh.ProcessError:
                continue
            if result.stdout.strip() == b"VEA_REMOTE_LOG_SHELL_READY":
                self._shell_prefix = prefix
                return prefix
        raise ShellAccessError("vCenter Bash access is unavailable")

    async def command(self, script, limit=16384):
        if self.source.product == "vcenter":
            prefix = await self._vcenter_shell()
            script = "export PATH=/usr/sbin:/usr/bin:/sbin:/bin; " + script
            command = f"{prefix} {shlex.quote(script)}"
        else:
            command = script
        result = await self.connection.run(
            command, encoding=None, check=True, timeout=8
        )
        if len(result.stdout) > limit:
            raise ValueError("remote command output exceeds limit")
        return result.stdout

    async def read(self, path, offset, length):
        if offset < 0 or length < 0:
            raise ValueError("invalid byte range")
        quoted = shlex.quote(path)
        if path.endswith(".gz"):
            # Validate before piping: head can hide gzip failure via the pipeline exit status.
            pipeline = f"gzip -cd {quoted} | tail -c +{offset + 1}"
        else:
            pipeline = f"tail -c +{offset + 1} {quoted}"
        script = f"{pipeline} | head -c {length}"
        # Explicit readability check cannot be masked by the final pipeline stage.
        script = f"test -r {quoted} || exit 1; " + script
        if path.endswith(".gz"):
            if path not in self._validated_gzip:
                await self.command(f"gzip -t {quoted}")
                self._validated_gzip.add(path)
        return await self.command(script, limit=length)

    async def verify(self, file):
        output = await self.command(f"stat -L -c '%d:%i %s %Y' {shlex.quote(file.path)}")
        identity, size, modified = output.decode().strip().split()
        if (
            identity != file.identity
            or int(size) < file.disk_size
            or (
                not file.active
                and (int(size) != file.disk_size or int(modified) != file.modified)
            )
        ):
            logger.warning(
                "log snapshot changed path=%s active=%s before=%s/%s/%s after=%s/%s/%s",
                file.path, file.active, file.identity, file.disk_size, file.modified,
                identity, size, modified,
            )
            raise LogFileChanged("log rotated or truncated during read")

    async def files(self, kind, previous=None):
        self._validated_gzip.clear()
        base = PRESETS[self.source.product][kind]
        stem = base[:-4]
        # vpxd uses vpxd-N.log[.gz]; ESXi uses name.N[.gz] or name.log.N[.gz].
        patterns = f"{base} {stem}.[0-9]* {base}.[0-9]* {stem}-[0-9]*.log*"
        output = await self.command(
            f'for f in {patterns}; do if test -f "$f"; then stat -L -c \'%d:%i %s %Y %n\' "$f" || exit 1; fi; done'
        )
        allowed = re.compile(
            re.escape(stem) + r"(?:\.log|(?:\.log)?\.\d+(?:\.gz)?|-\d+\.log(?:\.gz)?)$"
        )
        metadata = []
        for line in output.decode().splitlines():
            identity, size, modified, path = line.split(" ", 3)
            if not allowed.fullmatch(path):
                continue
            disk_size = int(size)
            metadata.append(RemoteFile(path, identity, disk_size, int(modified), b"", path == base, disk_size))
        active_identities = {f.identity for f in metadata if f.active}
        # vpxd.log can link to the currently growing vpxd-N.log. Keep only the
        # active name, whose normal growth is allowed by verify().
        metadata = [f for f in metadata if f.active or f.identity not in active_identities]
        if len(metadata) > 64:
            raise ValueError("too many rotated files for one log stream")
        if not any(f.active for f in metadata):
            raise FileNotFoundError("required active log file is missing")
        files = []
        for file in metadata:
            path, disk_size = file.path, file.disk_size
            cached = next((s for s in (previous or {}).get("files", []) if same_archived_file(s, file)), None)
            if not file.active and (previous is None or cached is not None):
                # Bootstrap ignores historical files. Immutable, completed archives
                # are subsequently identified by inode, disk size and mtime.
                files.append(RemoteFile(path, file.identity, cached["offset"] if cached else 0,
                    file.modified, b"", False, disk_size, True))
                continue
            size = disk_size
            if path.endswith(".gz"):
                q = shlex.quote(path)
                logical = await self.command(
                    f"gzip -t {q} || exit 1; gzip -cd {q} | wc -c"
                )
                size = int(logical.strip())
                self._validated_gzip.add(path)
            prefix = await self.read(path, 0, min(int(size), 256))
            files.append(
                RemoteFile(
                    path,
                    file.identity,
                    int(size),
                    file.modified,
                    prefix,
                    path == base,
                    disk_size,
                )
            )
        # Oldest first, active last; numeric suffixes alone are not chronological.
        return sorted(files, key=lambda f: (f.active, f.modified, f.path))


@asynccontextmanager
async def open_reader(source):
    # Lazy import lets parsing and mock tests run without network dependencies.
    import asyncssh

    # Resolve and check once, then connect to that address: connecting by name would
    # resolve again and could reach loopback or cloud metadata (DNS rebinding, Issue #237).
    # The host key is still matched against the configured name.
    address = await resolve_ssh_address(source.host, source.port)
    async with asyncssh.connect(
        address,
        port=source.port,
        host_key_alias=source.host,
        username=source.username,
        client_keys=[source.private_key_file],
        known_hosts=source.known_hosts_file,
        agent_path=None,
        config=None,
        password_auth=False,
        kbdint_auth=False,
        connect_timeout=8,
        login_timeout=8,
    ) as connection:
        yield SSHReader(connection, source)
