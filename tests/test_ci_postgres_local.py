"""CI の PostgreSQL の手順を手元で流すスクリプトのテスト。"""

from __future__ import annotations

import subprocess

import pytest

import scripts.ci_postgres_local as ci_postgres_local


def test_reads_postgres_steps_from_the_real_workflow():
    """ci.yml の PostgreSQL の手順を取り出し、ポートの式を手元のポートに置き換える。"""
    workflow = ci_postgres_local.load_workflow()
    steps = ci_postgres_local.postgres_steps(workflow, 55432)

    assert steps
    for step in steps:
        assert step.run.startswith("uv run")
        assert "${{" not in step.run
        assert all("${{" not in value for value in step.env.values())
        assert any("127.0.0.1:55432" in value for value in step.env.values())
    # 認証の手順は別の環境変数で URL を受け取るので、それも取り出す。
    assert {key for step in steps for key in step.env} >= {"VEA_TEST_POSTGRES_URL", "VEA_TEST_AUTH_POSTGRES_URL"}

    service = ci_postgres_local.postgres_service(workflow)
    assert service.image.startswith("postgres:")
    assert (service.user, service.password, service.database) == ("vea_ci", "vea_ci", "vea_ci")


def test_published_ports_reads_docker_port_output():
    assert ci_postgres_local.published_ports("0.0.0.0:55432\n[::]:55432\n") == {55432}
    assert ci_postgres_local.published_ports("") == set()


def test_rejects_a_running_container_published_on_another_port(monkeypatch):
    """既定のポートで残したコンテナを、別のポートの指定で使わない。"""
    calls = []

    def fake_docker(*args, check=True):
        calls.append(args)
        outputs = {"ps": f"{ci_postgres_local.CONTAINER}\n", "port": "0.0.0.0:55432\n[::]:55432\n"}
        return subprocess.CompletedProcess(args, 0, stdout=outputs.get(args[0], ""), stderr="")

    monkeypatch.setattr(ci_postgres_local, "_docker", fake_docker)
    service = ci_postgres_local.PostgresService("postgres:16-alpine", "u", "p", "d")

    with pytest.raises(RuntimeError, match="6000"):
        ci_postgres_local.ensure_container(service, 6000)
    assert [call[0] for call in calls] == ["ps", "port"]

    calls.clear()
    ci_postgres_local.ensure_container(service, 55432)
    assert [call[0] for call in calls] == ["ps", "port", "exec"]


def test_skips_steps_that_do_not_use_the_postgres_service():
    workflow = {
        "jobs": {
            "python": {"steps": [{"run": "uv run pytest", "env": {"X": "1"}}]},
            "db": {
                "services": {"postgres": {"image": "postgres:16", "env": {
                    "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p", "POSTGRES_DB": "d",
                }}},
                "steps": [
                    {"uses": "actions/checkout@v4"},
                    {"run": "uv sync --locked"},
                    {
                        "name": "Postgres tests",
                        "run": "uv run pytest -k postgres\n",
                        "env": {"URL": "postgresql://u:p@127.0.0.1:${{ job.services.postgres.ports['5432'] }}/d"},
                    },
                ],
            },
        }
    }

    steps = ci_postgres_local.postgres_steps(workflow, 6000)

    assert steps == [
        ci_postgres_local.PostgresStep(
            job="db",
            name="Postgres tests",
            run="uv run pytest -k postgres",
            env={"URL": "postgresql://u:p@127.0.0.1:6000/d"},
        )
    ]
