"""Static checks on the deploy files: the image must never carry raw data, .env, or secrets."""
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ("ANTHROPIC_API_KEY", "DASHBOARD_PASSWORD", "SESSION_SECRET")


def _instructions(text: str) -> list[tuple[str, str]]:
    """Dockerfile logical lines as (INSTRUCTION, args), joining backslash continuations."""
    out, buf = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not buf and (not line or line.startswith("#")):
            continue
        if line.startswith("#"):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        word, _, rest = buf.partition(" ")
        out.append((word.upper(), rest.strip()))
        buf = ""
    return out


@pytest.fixture(scope="module")
def dockerfile() -> list[tuple[str, str]]:
    return _instructions((ROOT / "Dockerfile").read_text())


@pytest.fixture(scope="module")
def final_stage(dockerfile) -> list[tuple[str, str]]:
    froms = [i for i, (ins, _) in enumerate(dockerfile) if ins == "FROM"]
    assert len(froms) >= 2, "Dockerfile should be multi-stage"
    return dockerfile[froms[-1]:]


def test_final_stage_never_copies_raw_data_or_env(final_stage):
    copies = [args for ins, args in final_stage if ins in ("COPY", "ADD")]
    assert copies
    for args in copies:
        assert "data/raw" not in args
        assert ".env" not in args
        sources = [s for s in args.split()[:-1] if not s.startswith("--")]
        assert not {".", "./", "*"} & set(sources), f"copies whole build context: {args}"
    # The only thing taken from the builder is the preprocessed DB.
    from_builder = [a for a in copies if a.startswith("--from=")]
    assert from_builder and all(a.split()[1].endswith("data/boston.sqlite") for a in from_builder)


def test_builder_deletes_raw_data(dockerfile):
    runs = " ".join(args for ins, args in dockerfile if ins == "RUN")
    assert "rm -rf data/raw" in runs


ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"


def test_cmd_runs_entrypoint_without_access_log(final_stage):
    cmds = [args for ins, args in final_stage if ins == "CMD"]
    assert cmds and "entrypoint.sh" in cmds[-1]
    copies = " ".join(args for ins, args in final_stage if ins == "COPY")
    assert "docker/entrypoint.sh" in copies
    text = ENTRYPOINT.read_text()
    uvicorn = text[text.index("uvicorn app.main:app"):]
    for flag in ("--no-access-log", "--proxy-headers",
                 '--forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"', "${PORT:-8000}"):
        assert flag in uvicorn, flag
    assert "--access-log " not in text


def test_forwarded_ips_never_trust_every_peer():
    """X-Forwarded-For is trusted only from configured proxies, never from everyone."""
    code = [l for l in ENTRYPOINT.read_text().splitlines() if not l.lstrip().startswith("#")]
    joined = "\n".join(code)
    assert not re.search(r"forwarded-allow-ips=[\"']?\*", joined)
    assert not re.search(r"FORWARDED_ALLOW_IPS:-\*", joined)
    for name in ("Dockerfile", "render.yaml"):
        text = (ROOT / name).read_text()
        assert not re.search(r"forwarded-allow-ips=[\"']?\*", text), name
        assert not re.search(r"FORWARDED_ALLOW_IPS\s*[=:]\s*[\"']?\*", text), name
    # The blueprint leaves the proxy range to the owner instead of guessing it.
    m = re.search(r"-\s*key:\s*FORWARDED_ALLOW_IPS\s*\n((?:\s+\w+:.*\n?)*)", (ROOT / "render.yaml").read_text())
    assert m and re.search(r"sync:\s*false", m.group(1))


def test_final_stage_copies_only_startup_scripts(final_stage):
    copies = [args for ins, args in final_stage if ins == "COPY"]
    script_copies = [a for a in copies if "scripts" in a]
    assert script_copies == ["scripts/__init__.py scripts/seed_reports.py scripts/"]
    # seed_reports imports only the standard library and app/, which the final stage copies.
    src = (ROOT / "scripts" / "seed_reports.py").read_text()
    imported = set(re.findall(r"^(?:from|import)\s+([\w.]+)", src, re.M))
    assert not {m for m in imported if m.startswith("scripts")}
    assert "app/ app/" in copies


def test_datacommons_key_is_a_build_secret_only(dockerfile):
    for ins, args in dockerfile:
        if ins in ("ENV", "ARG"):
            assert "DATACOMMONS" not in args.upper(), f"{ins} sets the Data Commons key"
    froms = [i for i, (ins, _) in enumerate(dockerfile) if ins == "FROM"]
    builder, final = dockerfile[froms[0]:froms[-1]], dockerfile[froms[-1]:]
    data_run = next(a for ins, a in builder if ins == "RUN" and "build_data.sh" in a)
    assert data_run.startswith("--mount=type=secret,id=datacommons_api_key")
    assert "/run/secrets/datacommons_api_key" in data_run
    assert not any("datacommons" in a.lower() for _, a in final)
    lines = {l.strip() for l in (ROOT / ".dockerignore").read_text().splitlines()}
    assert "datacommons_api_key" in lines
    example = (ROOT / ".env.example").read_text()
    assert re.search(r"^# DATACOMMONS_API_KEY=$", example, re.M)


def test_gitignore_covers_every_sqlite_file():
    lines = {l.strip() for l in (ROOT / ".gitignore").read_text().splitlines()}
    assert "data/*.sqlite*" in lines
    assert "data/raw/" in lines and ".env" in lines


def test_final_stage_runtime_env(final_stage):
    env = " ".join(args for ins, args in final_stage if ins == "ENV")
    for item in ("APP_DB_PATH=/data/app.sqlite", "FORCE_SECURE_COOKIES=true",
                 "PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1"):
        assert item in env, item
    runs = " ".join(args for ins, args in final_stage if ins == "RUN")
    assert "requirements-dev" not in runs
    assert any(ins == "HEALTHCHECK" and "/health" in args for ins, args in final_stage)
    assert any(ins == "EXPOSE" and args == "8000" for ins, args in final_stage)


def test_no_secrets_baked_into_env_or_args(dockerfile):
    for ins, args in dockerfile:
        if ins in ("ENV", "ARG"):
            for name in SECRETS:
                assert name not in args, f"{ins} sets {name}"


def test_final_stage_runs_as_non_root(final_stage):
    users = [args for ins, args in final_stage if ins == "USER"]
    assert users and users[-1] not in ("root", "0")


def test_dockerignore_excludes_sensitive_paths():
    lines = {l.strip() for l in (ROOT / ".dockerignore").read_text().splitlines()}
    for entry in (".env", ".env.*", "data/raw", ".venv", "data/*.sqlite*"):
        assert entry in lines, f".dockerignore missing {entry}"


def test_render_secrets_not_in_blueprint():
    text = (ROOT / "render.yaml").read_text()
    for name in SECRETS:
        m = re.search(rf"-\s*key:\s*{name}\s*\n((?:\s+\w+:.*\n?)*)", text)
        assert m, f"render.yaml missing {name}"
        body = m.group(1)
        assert re.search(r"sync:\s*false|generateValue:\s*true", body), name
        assert "value:" not in body.replace("generateValue:", ""), f"{name} has a literal value"


def test_build_data_script_is_executable():
    script = ROOT / "scripts" / "build_data.sh"
    assert script.exists()
    assert os.access(script, os.X_OK)
    text = script.read_text()
    assert "set -euo pipefail" in text
    assert "--python" in text


def test_build_data_script_runs_fetch_then_preprocess():
    text = (ROOT / "scripts" / "build_data.sh").read_text()
    fetch = text.index("-m scripts.fetch_boston")
    assert fetch < text.index("-m scripts.preprocess_boston")
    # No dataset names after fetch_boston: all datasets are fetched.
    assert text[fetch:].splitlines()[0].strip() == "-m scripts.fetch_boston"


def test_entrypoint_is_executable_and_execs():
    assert os.access(ENTRYPOINT, os.X_OK)
    text = ENTRYPOINT.read_text()
    assert "set -eu" in text
    assert re.search(r"^exec ", text, re.M)
    assert 'scripts.seed_reports --db "$DB"' in text
    assert "SELECT COUNT(*) FROM simulated_reports" in text


def test_entrypoint_seed_guard_works_with_port_unset(tmp_path):
    """The entrypoint's shell syntax is valid and PORT/SEED_SIMULATED may be unset."""
    import subprocess

    res = subprocess.run(["sh", "-n", str(ENTRYPOINT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    # Passing a command replaces uvicorn, so this exercises the guard without starting a server.
    env = {"PATH": os.environ["PATH"], "APP_DB_PATH": str(tmp_path / "app.sqlite")}
    res = subprocess.run(["sh", str(ENTRYPOINT), "echo", "ran"], capture_output=True, text=True,
                         env=env, timeout=30)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "ran"
    assert not (tmp_path / "app.sqlite").exists()
