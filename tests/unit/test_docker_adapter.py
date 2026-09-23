"""§13 DockerAdapter against a FIXTURE runner (no real daemon: Docker is not installed on this host, decision D1).
The fixture imitates `docker ps/stats/inspect/logs` JSON output; it records every argv the adapter tries to run."""
from __future__ import annotations

import json

import pytest

from services.observability import docker as D
from services.observability.docker import DockerAdapter, DockerDenied

ALLOWED = frozenset({"alice-qdrant", "alice-prometheus", "alice-grafana"})

PS = [{"Names": "alice-qdrant", "ID": "a" * 64, "State": "running", "Status": "Up 2 hours"},
      {"Names": "alice-prometheus", "ID": "b" * 64, "State": "exited", "Status": "Exited (0)"},
      {"Names": "work-postgres", "ID": "c" * 64, "State": "running", "Status": "Up 3 days"}]
INSPECT = [{"Name": "/alice-qdrant", "RestartCount": 1,
            "State": {"Status": "running", "StartedAt": "2026-09-22T10:00:00Z", "OOMKilled": False, "ExitCode": 0},
            "Config": {"Env": ["QDRANT__SERVICE__API_KEY=supersecret-env-value"], "Cmd": ["./qdrant", "--secret"],
                       "Labels": {"com.work.owner": "confidential"}},
            "Mounts": [{"Source": "C:/Users/cuent/private"}], "HostConfig": {"Binds": ["/:/host"]}}]


class FixtureRunner:
    def __init__(self, logs: str = "2026-09-22T10:00:00Z INFO ready\n2026-09-22T10:01:00Z ERROR boom\n"):
        self.calls: list[list[str]] = []
        self.logs = logs

    def __call__(self, argv, timeout):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
        assert timeout <= D.TIMEOUT_S
        self.calls.append(argv)
        sub = argv[1]
        if sub == "version":
            return 0, "27.0.0", ""
        if sub == "ps":
            return 0, "\n".join(json.dumps(r) for r in PS), ""
        if sub == "stats":
            return 0, "\n".join(json.dumps({"Name": n, "ID": "x", "CPUPerc": "1.0%", "MemUsage": "10MiB / 1GiB", "MemPerc": "1.0%",
                                            "NetIO": "1kB / 2kB", "BlockIO": "0B / 0B", "PIDs": "5", "Container": "leak"})
                                for n in argv[5:]), ""
        if sub == "inspect":
            return 0, json.dumps(INSPECT), ""
        if sub == "logs":
            return 0, self.logs[: D.OUT_MAX + 1], ""
        return 1, "", "unexpected subcommand"


@pytest.fixture
def run():
    return FixtureRunner()


@pytest.fixture
def dk(run):
    return DockerAdapter(ALLOWED, runner=run, exe="docker-fixture")


def ref_calls(run):
    return [c for c in run.calls if c[1] in ("inspect", "logs")]


def test_list_only_allowlisted(dk):
    assert [c["name"] for c in dk.list_containers()] == ["alice-qdrant", "alice-prometheus"]


@pytest.mark.parametrize("ref", [
    "alice-qdrant; rm -rf /", "alice-qdrant && docker rm -f x", "$(whoami)", "`id`", "alice-qdrant|calc",
    "alice-qdrant\nrm", "-v", "--privileged", "-alice-qdrant", "--help", "../../etc", "", "a" * 200, "alice qdrant",
])
def test_malicious_refs_never_reach_the_runner(dk, run, ref):
    for op in ("container_status", "container_logs"):
        with pytest.raises(DockerDenied):
            dk.call(op, ref=ref)
    assert ref_calls(run) == []


def test_non_allowlisted_container_rejected_even_if_live(dk, run):
    with pytest.raises(DockerDenied, match="allowlist"):
        dk.call("container_logs", ref="work-postgres")
    assert ref_calls(run) == []


def test_allowlisted_but_absent_container_rejected(dk, run):
    with pytest.raises(DockerDenied, match="inventario"):
        dk.call("container_status", ref="alice-grafana")
    assert ref_calls(run) == []


@pytest.mark.parametrize("op", ["exec", "run", "rm", "stop", "restart", "kill", "prune", "cp", "pull", "_run", "__init__", "status"])
def test_mutating_or_unknown_ops_do_not_exist(dk, run, op):
    with pytest.raises(DockerDenied, match="no permitida"):
        dk.call(op, ref="alice-qdrant")
    assert run.calls == []


def test_argv_is_fixed_and_ref_after_double_dash(dk, run):
    dk.call("container_logs", ref="alice-qdrant")
    argv = run.calls[-1]
    assert argv[:2] == ["docker-fixture", "logs"] and argv[-2:] == ["--", "alice-qdrant"]
    assert "--follow" not in argv and "-f" not in argv


@pytest.mark.parametrize("tail,since,exp_tail,exp_since", [
    (10 ** 9, 10 ** 9, D.LOG_MAX, D.SINCE_MAX_S), (-5, -5, 1, 1), (0, 0, 1, 1), (200, 3600, 200, 3600)])
def test_log_bounds_clamped(dk, run, tail, since, exp_tail, exp_since):
    out = dk.call("container_logs", ref="alice-qdrant", tail=tail, since_s=since)
    assert (out["tail"], out["since_s"]) == (exp_tail, exp_since)
    argv = run.calls[-1]
    assert argv[argv.index("--tail") + 1] == str(exp_tail) and argv[argv.index("--since") + 1] == f"{exp_since}s"
    assert D.LOG_MAX == 1000 and D.SINCE_MAX_S == 24 * 3600


def test_non_numeric_bounds_rejected(dk):
    with pytest.raises((ValueError, DockerDenied)):
        dk.call("container_logs", ref="alice-qdrant", tail="10; rm -rf /")


def test_huge_output_truncated_with_notice(run):
    run.logs = ("x" * 99 + "\n") * 10_000  # ~1 MB
    out = DockerAdapter(ALLOWED, runner=run, exe="docker-fixture").call("container_logs", ref="alice-qdrant")
    assert out["truncated"] is True
    assert len("\n".join(out["lines"])) <= D.OUT_MAX == 256 * 1024


def test_secret_shaped_log_lines_redacted(run):
    run.logs = ("password=hunter2\nAuthorization: Bearer abcdef1234567890\nkey sk-or-v1-ABCDEFGHIJKLMNOPQRSTUV loaded\n"
                "QDRANT__SERVICE__API_KEY: qdrant-secret-xyz\n")
    out = DockerAdapter(ALLOWED, runner=run, exe="docker-fixture").call("container_logs", ref="alice-qdrant")
    text = "\n".join(out["lines"])
    for s in ("hunter2", "abcdef1234567890", "sk-or-v1-ABCDEFGHIJKLMNOPQRSTUV", "qdrant-secret-xyz"):
        assert s not in text


def test_status_is_projection_not_full_inspect(dk):
    st = dk.call("container_status", ref="alice-qdrant")
    assert set(st) == {"name", "state", "started_at", "restart_count", "oom_killed", "exit_code", "health"}
    dump = json.dumps(st)
    for leak in ("supersecret", "--secret", "confidential", "private", "/host", "Env", "Mounts"):
        assert leak not in dump
    assert "no instrumentada" in st["health"]  # no HEALTHCHECK -> never reported as "healthy"


def test_stats_projection_and_only_running_allowlisted(dk, run):
    stats = dk.call("container_stats")
    assert [s["Name"] for s in stats] == ["alice-qdrant"]
    assert "Container" not in stats[0] and "ID" not in stats[0]
    assert "work-postgres" not in run.calls[-1]


def test_no_docker_installed_is_unavailable_not_invented(run, monkeypatch):
    monkeypatch.setattr(D.shutil, "which", lambda _: None)
    d = DockerAdapter(ALLOWED, runner=run)
    assert d.status()["state"] == "unavailable"
    with pytest.raises(DockerDenied):
        d.call("list_containers")
    assert run.calls == []


def test_default_runner_never_uses_shell():
    import inspect
    src = inspect.getsource(D._default_runner)
    assert "shell=False" in src and "cmd" not in src
