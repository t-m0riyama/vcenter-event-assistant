"""診断コマンドの雛形と引数が守る条件を検証する。"""

import re
import shlex
import shutil
import subprocess

import pytest

from vcenter_event_assistant.services.diagnostics.catalog import (
    PARAMETER_TYPES,
    ParameterError,
    TemplateError,
    normalize_parameter,
    render_command,
    validate_template,
)

DEVICE = [{"name": "x", "type": "device"}]


@pytest.mark.parametrize(
    ("template", "definitions", "reason", "name"),
    [
        ("echo {{x}}", [], "undefined_parameter", "x"),
        (
            "echo {{Vmk}}",
            [{"name": "vmk", "type": "vmk"}],
            "undefined_parameter",
            "Vmk",
        ),
        ("echo", DEVICE, "unused_parameter", "x"),
        ("echo ${{x}}", DEVICE, "dollar_prefix", "x"),
        ('echo "${{x}}"', DEVICE, "dollar_prefix", "x"),
        (r"echo $'\{{x}}'", DEVICE, "backslash_prefix", "x"),
        (r"echo \{{x}}", DEVICE, "backslash_prefix", "x"),
        ("echo {{x}}", DEVICE * 2, "duplicate_parameter", "x"),
        (
            "echo",
            [{"name": "bad-name", "type": "device"}],
            "invalid_parameter_name",
            "bad-name",
        ),
        ("echo", [{"name": "x", "type": "text"}], "unknown_parameter_type", "x"),
        (
            "echo",
            [{"name": f"p{i}", "type": "device"} for i in range(9)],
            "too_many_parameters",
            None,
        ),
        *[
            ("echo" + c, [], "control_character", None)
            for c in (
                "\n",
                "\r",
                "\0",
                "\t",
                "\x1b",
                "\x7f",
                "\x85",
                "\u2028",
                "\u2029",
                "\u202e",
                "\u200b",
            )
        ],
    ],
)
def test_diagnostic_template_rejections(template, definitions, reason, name):
    with pytest.raises(TemplateError) as error:
        validate_template(template, definitions)
    assert (error.value.reason, error.value.parameter) == (reason, name)


@pytest.mark.parametrize(
    ("template", "definitions", "params", "expected"),
    [
        ("hostname", [], {}, "hostname"),
        ("awk '{print $1}'", [], {}, "awk '{print $1}'"),
        ("echo '{{a-b}}'", [], {}, "echo '{{a-b}}'"),
        (
            "esxcli --nic-name={{vmnic}} /net/{{vmnic}}/stats",
            [{"name": "vmnic", "type": "vmnic"}],
            {"vmnic": "vmnic1"},
            "esxcli --nic-name=vmnic1 /net/vmnic1/stats",
        ),
        ("{{x}}", DEVICE, {"x": "uptime"}, "uptime"),
    ],
)
def test_diagnostic_template_rendering(template, definitions, params, expected):
    assert render_command(template, definitions, params) == expected


VALID_VALUES = {
    "vmnic": ("vmnic0", "vmnic999"),
    "vmk": ("vmk0", "vmk123"),
    "ipv4": ("0.0.0.0", "192.168.0.1", "255.255.255.255"),
    "device": ("naa.60a", "mpx.vmhba0:C0:T0:L0", "x41", "HOME", "Z" * 128),
}


@pytest.mark.parametrize("kind", PARAMETER_TYPES)
def test_diagnostic_parameter_types_have_shell_safe_values(kind):
    for example in VALID_VALUES[kind]:
        value = normalize_parameter(kind, example)
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9@%+=:,./_-]*", value)
        assert shlex.quote(value) == value


@pytest.mark.parametrize("kind", PARAMETER_TYPES)
def test_diagnostic_parameter_types_reject_unsafe_values(kind):
    example = VALID_VALUES[kind][0]
    invalid_values = [
        example[:-1] + character + example[-1:]
        for character in ("'", '"', " ", "$", ";", "\\", "`")
    ]
    invalid_values += ["-" + example, "+" + example, example + "\n", ""]
    for value in invalid_values:
        with pytest.raises(ValueError):
            normalize_parameter(kind, value)


@pytest.mark.parametrize(
    "value", ("-flag", "x;id", "x y", "x\n", "${HOME}", "", "Z" * 129)
)
def test_diagnostic_render_rejects_invalid_device(value):
    with pytest.raises(ParameterError) as error:
        render_command("echo {{x}}", DEVICE, {"x": value})
    assert error.value.errors == {"x": "invalid_value"}


def test_diagnostic_render_validates_saved_template_and_argument_names():
    with pytest.raises(TemplateError, match="undefined_parameter"):
        render_command("echo {{other}}", DEVICE, {"x": "nice"})
    with pytest.raises(ParameterError) as error:
        render_command("echo {{x}}", DEVICE, {"extra": "nice"})
    assert error.value.errors == {"x": "missing", "extra": "unknown"}
    for value in ("192.168.0.1\n", "127.1", "::1", "192.168.0.1%eth0"):
        with pytest.raises(ValueError):
            normalize_parameter("ipv4", value)


@pytest.mark.parametrize("shell", ["bash", "sh"])
@pytest.mark.parametrize("kind", PARAMETER_TYPES)
def test_diagnostic_parameters_survive_shell_quoting(shell, kind):
    executable = shutil.which(shell)
    if executable is None:
        pytest.skip(f"{shell} がありません")

    def run(command):
        return subprocess.run(
            [executable, "-c", command], check=True, capture_output=True, text=True
        ).stdout

    # POSIX.1-2017 までの sh では $'…' の先頭の $ が文字として残る。
    dollar_quote_prefix = run("printf '%s' $'marker'").removesuffix("marker")
    definitions = [{"name": "x", "type": kind}]
    for example in VALID_VALUES[kind]:
        value = normalize_parameter(kind, example)
        for template, expected in [
            ("""printf '%s' "{{x}}" """, value),
            ("""printf '%s' '{{x}}' """, value),
            ("""printf '%s' "$(printf '%s' '{{x}}')" """, value),
            ("""printf '%s' $'{{x}}' """, dollar_quote_prefix + value),
            ("""printf '%s' 'a {{x}} b' """, f"a {value} b"),
        ]:
            assert (
                run(render_command(template, definitions, {"x": example})) == expected
            )
