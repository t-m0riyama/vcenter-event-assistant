"""計画書の例と、伏せ方・重大度の境界を検証する。"""

from hashlib import sha256

import pytest

from vcenter_event_assistant.services.log_patterns import masking
from vcenter_event_assistant.services.log_patterns.severity import WARNING_SEVERITIES, severity_rank

EXAMPLES = (
    (
        'cpu12:2097612)NMP: nmp_ThrottleLogForDevice:3893: Cmd 0x2a (0x45b8c1234567) to dev "naa.600508b1001c4d5e" on path "vmhba64:C0:T0:L1" Failed: H:0x0 D:0x2 P:0x0 Valid sense data: 0x6 0x29 0x0.',
        'cpu<N>:<N>)NMP: nmp_ThrottleLogForDevice:<N>: Cmd 0x2a (<HEX>) to dev "<DEV>" on path "<HBAPATH>" Failed: H:0x0 D:0x2 P:0x0 Valid sense data: 0x6 0x29 0x0.',
    ),
    (
        'In(166) Hostd[2099123]: [Originator@6876 sub=Vimsvc.TaskManager opID=abc-12-ff user=vpxuser:<no user>] Task Created : haTask-ha-root-pool-vim.ResourcePool.updateConfig-123456',
        'In(<N>) Hostd[<N>]: [sub=Vimsvc.TaskManager] Task Created : haTask-ha-root-pool-vim.ResourcePool.updateConfig-<N>',
    ),
    (
        'info hostd[2099123] [Originator@6876 sub=Vmsvc.vm:/vmfs/volumes/5f1a2b3c-1234abcd-ef01-0050568a1b2c/web01/web01.vmx opID=x user=root] State Transition (VM_STATE_ON -> VM_STATE_OFF)',
        'info hostd[<N>] [sub=Vmsvc.vm:<PATH>] State Transition (VM_STATE_ON -> VM_STATE_OFF)',
    ),
    (
        'verbose vpxa[2100001] [Originator@6876 sub=vpxLro opID=lro-1] [VpxLRO] -- BEGIN lro-12345 -- vpxa -- vpxapi.VpxaService.retrieveChanges -- 52a3c3e1-8f1b-4e7c-9d2a-1234567890ab',
        'verbose vpxa[<N>] [sub=vpxLro] [VpxLRO] -- BEGIN lro-<N> -- vpxa -- vpxapi.VpxaService.retrieveChanges -- <UUID>',
    ),
    (
        'error vpxd[00123] [Originator@6876 sub=vpxdVdb] [VdbStatement] SQL execution failed: password=hunter2 at 2024-01-02T10:20:30Z after 523ms on 10.0.0.12:5432 (esx-01.lab) [datastore1] web01/web01.vmdk',
        'error vpxd[<N>] [sub=vpxdVdb] [VdbStatement] SQL execution failed: password=<SECRET> at <TIME> after <N>ms on <IP> (esx-<N>.lab) <PATH>',
    ),
    (
        'cpu3:2097152)WARNING: NFS: 1234: Lost connection to server 192.168.1.10 mount point /vmfs/volumes/abcd1234-5678efab dead:beef:0:1 fe80::1 00:50:56:8a:1b:2c 10:20:30 12345678 1234567 deadbeef12 https://vc.example/sdk?x=1',
        'cpu<N>:<N>)WARNING: NFS: <N>: Lost connection to server <IP> mount point <PATH> dead:beef:<N>:<N> <IP> <MAC> <TIME> <N> <N> <HEX> <URL>',
    ),
    (
        'cpu0:2097150)ScsiPath: 1234: Path vmhba2:C0:T1:L5 WWN 20:00:00:25:b5:00:00:0f on 2001:db8::10:20:30 at 10:20:30 Foo :: bar',
        'cpu<N>:<N>)ScsiPath: <N>: Path <HBAPATH> WWN <WWN> on <IP> at <TIME> Foo :: bar',
    ),
    (
        'info vpxd[1] cookie=abc; Authorization: Bearer eyJhbGciOi.x.y "password":"p@ss" password: x [HostCtl] host/foo.bar https://10.0.0.1:443/sdk?id=1',
        'info vpxd[<N>] cookie=<SECRET>; Authorization: <SECRET> <SECRET> "password":<SECRET> password: <SECRET> [HostCtl] host/foo.bar <URL>',
    ),
)


@pytest.mark.parametrize(("message", "template"), EXAMPLES)
def test_log_pattern_examples(message, template):
    assert masking.mask_message("2026-11-24T10:00:04.000+09:00 " + message) == template


def test_log_pattern_key(monkeypatch):
    key = masking.pattern_key(" Hostd ", "Task <N>")
    assert key == sha256(b"1\x00hostd\x00Task <N>").hexdigest()[:32]
    assert key == masking.pattern_key("hostd", "Task <N>")
    assert key != masking.pattern_key("vpxa", "Task <N>")
    monkeypatch.setattr(masking, "MASK_VERSION", 2)
    assert key != masking.pattern_key("hostd", "Task <N>")


def test_log_pattern_limits_and_failure():
    assert masking.mask_message("one 12\npassword=secret") == "one <N>"
    assert masking.mask_message(" " * 1999 + "9discarded") == "<N>"
    assert masking.mask_message("z" * 600) == "z" * 500
    assert masking.mask_message(None) == "<UNPARSED>"


def test_log_pattern_additional_masks():
    assert masking.mask_message(
        "'token' = 'two words'; user=alice opID=alpha /var/log/2024-01-02.log"
        " 2001:db8:0:0:0:0:0:1 00-50-56-8a-1b-2c 1a2b 0x2a <UUID>"
    ) == (
        "'token' = <SECRET>; user=<USER> opID=<ID> <PATH>"
        " <IP> <MAC> <N>a<N>b 0x2a <UUID>"
    )


@pytest.mark.parametrize(("field", "expected"), [
    ('Authorization: "Bearer token with spaces"', 'Authorization: <SECRET>'),
    ('password="<TIME> two words";', 'password=<SECRET>;'),
    ("Bearer token; trailing", "Bearer <SECRET>; trailing"),
    ("Authorization: Basic dXNlcjpwYXNz", "Authorization: <SECRET> <SECRET>"),
    ("db_password=hunter2", "db_password=<SECRET>"),
    ("access_token=abc123", "access_token=<SECRET>"),
    ("client_secret=zzz", "client_secret=<SECRET>"),
    ("x_api_key=kkk", "x_api_key=<SECRET>"),
    ('password="short ' + "z" * 1983 + '\\discarded', "password=<SECRET>"),
])
def test_log_pattern_secret_is_masked_in_full(field, expected):
    assert masking.mask_message(field) == expected


def test_log_pattern_severity():
    groups = [
        ("debug", "verbose", "trivia"),
        ("info", "notice", "unknown", None),
        ("warning", "warn"),
        ("error", "err"),
        ("critical", "crit", "fatal", "panic", "alert", "emerg"),
    ]
    for rank, words in enumerate(groups):
        for word in words:
            assert severity_rank(f" {word.upper()} " if word else None) == rank
    assert WARNING_SEVERITIES == set().union(*groups[2:])



@pytest.mark.parametrize(("message", "expected"), [
    ("Bearer opaque-value", "Bearer <SECRET>"),
    ("vmnic0 auto-negotiate enabled", "vmnic<N> auto-negotiate enabled"),
    ("Using basic mode for disk", "Using basic mode for disk"),
    ("content digest mismatch on file", "content digest mismatch on file"),
    ("Negotiate failed with peer", "Negotiate failed with peer"),
    ("NTLM authentication failed", "NTLM authentication failed"),
])
def test_log_pattern_authentication_scheme_without_label(message, expected):
    assert masking.mask_message(message) == expected


def test_log_pattern_normalization_matches_sql():
    assert masking.normalize_log_kind(" HOSTD\t ") == "hostd\t"
    assert masking.normalize_log_kind(" HOSTD\u00a0 ") == "hostd\u00a0"
    assert masking.normalize_log_kind(" ÄHOSTD ") == "Ähostd"
    assert masking.pattern_key("hostd\t", "Task") != masking.pattern_key("hostd", "Task")
    assert severity_rank(" WARn\t ") == 1
    assert severity_rank(" WARn\u00a0 ") == 1
    assert severity_rank(" WARn ") == 2
