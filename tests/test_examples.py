"""The three examples and the Docker configuration (Sprint 16, build-plan tasks 21+22).

The outputs in output_examples/ must be what `scripts/make_examples.py` produces from the cache on
the branch: the regeneration test reruns it into a temp folder and compares, ignoring only run
timestamps and durations. The Docker image itself is built and run in CI (.github/workflows/
docker-check.yml); here only its configuration is checked.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from app.api.main import RunRequest
from app.config import REPO_ROOT
from app.schemas import Result

INPUTS = REPO_ROOT / "input_examples"
OUTPUTS = REPO_ROOT / "output_examples"
NUMBERS = (1, 2, 3)
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docker-check.yml"


def _load_make_examples():
    spec = importlib.util.spec_from_file_location("make_examples", REPO_ROOT / "scripts" / "make_examples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MAKE = _load_make_examples()


def answer_key() -> dict[str, dict]:
    return {item["id"]: item for item in json.loads((REPO_ROOT / "eval" / "answer_key.json").read_text("utf-8"))}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --- the committed triples ---------------------------------------------------------------------------


def test_three_examples_each_with_input_output_trace_and_meta() -> None:
    assert [n for n, _, _ in MAKE.EXAMPLES] == list(NUMBERS)
    for n in NUMBERS:
        for path in (INPUTS / f"example_{n}.json", OUTPUTS / f"example_{n}.json",
                     OUTPUTS / f"example_{n}.trace.jsonl", OUTPUTS / f"example_{n}.meta.json"):
            assert path.is_file(), path


def test_inputs_are_valid_run_bodies_with_the_answer_key_questions_verbatim() -> None:
    key = answer_key()
    for n, incident, _ in MAKE.EXAMPLES:
        body = read_json(INPUTS / f"example_{n}.json")
        request = RunRequest.model_validate(body)  # the API's own model: unknown fields would be 422
        assert request.options.sample_mode is True
        assert request.input is not None and request.input.query == key[incident]["question"]
        assert "run_id" not in body  # a fixed run id would get 409 run_id_taken on the second POST


def test_examples_are_the_day1_review_dip_and_an_undeterminable_question() -> None:
    incidents = [incident for _, incident, _ in MAKE.EXAMPLES]
    assert incidents[:2] == ["incident-01", "incident-06"]
    assert incidents[2] in ("incident-09", "incident-10")
    assert answer_key()[incidents[2]]["cause_types"] == ["none"]


@pytest.mark.parametrize("n", NUMBERS)
def test_output_is_a_schema_valid_sample_mode_success(n: int) -> None:
    result = Result.model_validate_json((OUTPUTS / f"example_{n}.json").read_text(encoding="utf-8"))
    assert result.status == "success" and result.sample_mode is True and result.error is None
    assert result.run_id == f"example_{n}"
    assert result.question == read_json(INPUTS / f"example_{n}.json")["input"]["query"]


def test_example_1_and_2_answers() -> None:
    one = Result.model_validate_json((OUTPUTS / "example_1.json").read_text(encoding="utf-8"))
    assert one.determinable and one.causes and one.causes[0].type == "volume"
    two = Result.model_validate_json((OUTPUTS / "example_2.json").read_text(encoding="utf-8"))
    assert two.determinable and two.causes[0].type == "product_quality"
    assert "logistics_delay" in [item.type for item in two.ruled_out]
    verdicts = {(line.get("hypothesis_family"), json.loads(line["output_summary"])["verdict"])
                for line in trace(OUTPUTS / "example_2.trace.jsonl")
                if line.get("agent") == "Critic" and line.get("action") == "critique"}
    assert any(verdict == "refuted" for _, verdict in verdicts), verdicts


def test_example_3_cannot_be_determined_and_asserts_no_cause() -> None:
    result = Result.model_validate_json((OUTPUTS / "example_3.json").read_text(encoding="utf-8"))
    assert result.determinable is False
    assert result.causes == []
    assert result.limitations
    assert result.summary.startswith("Cannot be determined")


@pytest.mark.parametrize("n", NUMBERS)
def test_trace_names_the_model_of_every_request(n: int) -> None:
    lines = trace(OUTPUTS / f"example_{n}.trace.jsonl")
    assert {line["run_id"] for line in lines} == {f"example_{n}"}
    calls = [line for line in lines if line.get("action") == "model_call"]
    assert calls, "no model request in the trace"
    for call in calls:
        assert call.get("model_requested") and call.get("model_routed"), call
        assert call.get("recorded_with") in ("stub", "meterless"), call


@pytest.mark.parametrize("n", NUMBERS)
def test_meta_reports_stub_and_meterless_entry_counts_from_the_trace(n: int) -> None:
    info = read_json(OUTPUTS / f"example_{n}.meta.json")
    calls = [line for line in trace(OUTPUTS / f"example_{n}.trace.jsonl") if line.get("action") == "model_call"]
    entries = {call["cache_key"]: call["recorded_with"] for call in calls}
    assert info["cache_entries"] == {"stub": list(entries.values()).count("stub"),
                                     "meterless": list(entries.values()).count("meterless"), "other": 0}
    assert sum(info["cache_entries"].values()) >= 1
    assert info["model_calls"] == len(calls)
    assert info["loop"] == "markovian" and info["sample_mode"] is True
    assert info["input"] == f"input_examples/example_{n}.json"
    if info["cache_entries"]["stub"]:
        assert "not a model's answer" in info["note"] or "Mixed" in info["note"]


# --- regeneration ------------------------------------------------------------------------------------


def _normalised(path: Path, log_dir: Path | None = None) -> str:
    text = path.read_text(encoding="utf-8")
    if log_dir is not None:  # the result names its log files; the temp run used another LOG_DIR
        text = text.replace(str(log_dir), "logs")
    return MAKE.normalised_text(text, jsonl=path.suffix == ".jsonl")


# Shell values that would change the outputs if make_examples.py let them through.
HOSTILE_ENV = {
    "QUERY_CACHE_DIR": "/nonexistent/query_cache",
    "loop": "simple",
    "SAMPLE_MODE": "false",
    "MARKOVIAN_MAX_CHUNKS": "1",
}


def test_make_examples_regenerates_the_committed_outputs(tmp_path: Path) -> None:
    out, inputs, logs = tmp_path / "out", tmp_path / "in", tmp_path / "logs"
    proc = subprocess.run(
        [sys.executable, "scripts/make_examples.py", "--out-dir", str(out), "--input-dir", str(inputs),
         "--log-dir", str(logs)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=600, check=False,
        env={**os.environ, **HOSTILE_ENV},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for n in NUMBERS:
        assert _normalised(inputs / f"example_{n}.json") == _normalised(INPUTS / f"example_{n}.json")
        for name in (f"example_{n}.json", f"example_{n}.trace.jsonl", f"example_{n}.meta.json"):
            assert _normalised(out / name, logs) == _normalised(OUTPUTS / name), f"{name} differs: rerun make_examples.py"


def test_clean_environment_drops_every_settings_field_and_markovian_variable(monkeypatch) -> None:
    # A copy, so the test process's own environment is left as it was.
    env = {**os.environ, **HOSTILE_ENV, "query_cache_dir": "/x", "METERLESS_BASE_URL": "http://x",
           "UNRELATED_VARIABLE": "kept"}
    monkeypatch.setattr(os, "environ", env)
    MAKE.clean_environment()
    assert not {"QUERY_CACHE_DIR", "loop", "query_cache_dir", "SAMPLE_MODE", "MARKOVIAN_MAX_CHUNKS",
                "METERLESS_BASE_URL"} & set(os.environ)
    assert os.environ["UNRELATED_VARIABLE"] == "kept"


def test_write_if_changed_keeps_a_file_that_differs_only_in_timings(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text('{"run_id": "x", "execution_time_seconds": 1.5, "causes": []}\n', encoding="utf-8")
    assert MAKE.write_if_changed(path, '{"run_id": "x", "execution_time_seconds": 0.2, "causes": []}\n') == "unchanged"
    assert "1.5" in path.read_text(encoding="utf-8")
    assert MAKE.write_if_changed(path, '{"run_id": "x", "execution_time_seconds": 0.2, "causes": [1]}\n') == "written"
    lines = tmp_path / "t.jsonl"
    lines.write_text('{"timestamp": "a", "duration_s": 0.1, "agent": "x"}\n', encoding="utf-8")
    assert MAKE.write_if_changed(lines, '{"timestamp": "b", "duration_s": 0.3, "agent": "x"}\n', jsonl=True) == "unchanged"
    assert MAKE.write_if_changed(lines, '{"timestamp": "b", "duration_s": 0.3, "agent": "y"}\n', jsonl=True) == "written"


# --- no secrets ----------------------------------------------------------------------------------------

SCANNED = [REPO_ROOT / "Dockerfile", REPO_ROOT / ".dockerignore", REPO_ROOT / ".env.example",
           *sorted(INPUTS.glob("*")), *sorted(OUTPUTS.glob("*"))]
SECRET_PATTERNS = {
    "NVIDIA key": re.compile(r"nvapi-"),
    "OpenAI-style key": re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}"),
    "e-mail address": re.compile(r"@gmail", re.IGNORECASE),
    "bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._-]{12,}"),
}
IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
ALLOWED_IPS = {"127.0.0.1", "0.0.0.0"}


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_secret_token_ip_or_account_in_docker_and_example_files(path: Path) -> None:
    if path.is_dir():
        return
    text = path.read_text(encoding="utf-8")
    for name, pattern in SECRET_PATTERNS.items():
        assert not pattern.search(text), f"{name} in {path.name}"
    assert set(IPV4.findall(text)) <= ALLOWED_IPS, f"IPv4 address in {path.name}: {set(IPV4.findall(text))}"


def test_secret_scan_patterns_catch_what_they_should() -> None:
    assert SECRET_PATTERNS["NVIDIA key"].search("NVIDIA_API_KEY=nvapi-abc")
    assert SECRET_PATTERNS["OpenAI-style key"].search("key sk-abcdefgh1234")
    assert not SECRET_PATTERNS["OpenAI-style key"].search("a task-level risk-free check")
    assert IPV4.findall("host 10.1.2.3 and 127.0.0.1") == ["10.1.2.3", "127.0.0.1"]
    assert IPV4.findall("version 1.2.3.4.5 or 0.0638") == []


# --- Docker configuration --------------------------------------------------------------------------------


def dockerfile() -> str:
    return (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")


def instructions() -> list[tuple[str, str]]:
    """(INSTRUCTION, arguments) per Dockerfile instruction, continuation lines joined."""
    text = re.sub(r"\\\n", " ", "\n".join(ln for ln in dockerfile().splitlines() if not ln.lstrip().startswith("#")))
    out = []
    for line in text.splitlines():
        if line.strip():
            word, _, rest = line.strip().partition(" ")
            out.append((word.upper(), rest.strip()))
    return out


def ci_python_version() -> str:
    ci = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    for step in ci["jobs"]["test"]["steps"]:
        if step.get("uses", "").startswith("actions/setup-python"):
            return str(step["with"]["python-version"])
    raise AssertionError("no setup-python step in ci.yml")


def test_dockerfile_base_is_the_ci_python_slim_image() -> None:
    froms = [rest for word, rest in instructions() if word == "FROM"]
    assert froms == [f"python:{ci_python_version()}-slim"]


def test_dependencies_are_installed_at_build_time_from_requirements() -> None:
    steps = instructions()
    runs = [rest for word, rest in steps if word == "RUN"]
    assert any(re.search(r"\bpip install -r requirements\.txt\b", run) for run in runs)
    copy_reqs = steps.index(("COPY", "requirements.txt ."))
    pip = next(i for i, (word, rest) in enumerate(steps) if word == "RUN" and "pip install" in rest)
    assert copy_reqs < pip


def test_start_command_is_the_api_and_installs_nothing() -> None:
    steps = instructions()
    cmds = [rest for word, rest in steps if word in ("CMD", "ENTRYPOINT")]
    assert cmds == ['["python", "-m", "app.api"]']
    for word, rest in steps:
        if word in ("CMD", "ENTRYPOINT", "HEALTHCHECK"):
            assert not re.search(r"\b(pip|apt-get|curl|wget|git)\b", rest), rest


def test_no_build_arg_or_env_holds_a_secret() -> None:
    steps = instructions()
    assert not [rest for word, rest in steps if word == "ARG"]
    env_names = [name for word, rest in steps if word == "ENV" for name in re.findall(r"([A-Z_][A-Z0-9_]*)=", rest)]
    assert env_names and not [n for n in env_names if re.search(r"KEY|TOKEN|PASSWORD|SECRET|ZETARIS|METERLESS", n)]


def test_duckdb_work_dir_is_on_disk_under_the_app_not_tmp() -> None:
    steps = instructions()
    assert ("WORKDIR", "/app") in steps
    assert any(word == "RUN" and "mkdir -p logs .cache/duckdb" in rest for word, rest in steps)
    assert not [rest for _, rest in steps if "/tmp" in rest or "DUCKDB_" in rest]  # the app defaults apply
    from app.config import Settings

    defaults = Settings.model_construct()
    assert not defaults.duckdb_work_dir.startswith("/")  # relative: resolved under the repository, /app here
    assert defaults.duckdb_threads >= 1 and defaults.duckdb_memory_limit


def dockerignore() -> list[str]:
    lines = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _ignored(path: str) -> bool:
    """Docker-style: the last matching pattern wins; `!` re-includes; a directory pattern covers its files."""
    ignored = False
    for pattern in dockerignore():
        negate = pattern.startswith("!")
        pat = pattern.lstrip("!").lstrip("/").rstrip("/")
        parts = path.split("/")
        prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
        if any(fnmatch.fnmatchcase(p, pat) or fnmatch.fnmatchcase(p, pat.removeprefix("**/")) for p in prefixes):
            ignored = not negate
    return ignored


def test_dockerignore_keeps_secrets_and_run_output_out_and_the_sample_data_in() -> None:
    entries = dockerignore()
    for required in (".git", ".venv", ".env", ".cache/", "logs/*", "!logs/.gitkeep", "__pycache__"):
        assert required in entries
    for path in (".env", ".git/config", ".venv/bin/python", "logs/result-x.json", ".cache/duckdb/x.duckdb",
                 "app/__pycache__/x.pyc"):
        assert _ignored(path), path
    for path in ("logs/.gitkeep", "data/sample/orders/orders.csv", "data/sample/llm_cache/x.json",
                 "eval/answer_key.json", "input_examples/example_1.json", "app/api/main.py", "requirements.txt",
                 ".env.example"):
        assert not _ignored(path), path


def test_env_example_has_the_docker_host_variants_commented() -> None:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^# METERLESS_BASE_URL=http://host\.docker\.internal:8088/v1$", text, re.MULTILINE)
    assert re.search(r"^# ZETARIS_URL=http://host\.docker\.internal:8888/api/v1\.0$", text, re.MULTILINE)
    assert re.search(r"^METERLESS_BASE_URL=http://127\.0\.0\.1:8088/v1$", text, re.MULTILINE)  # active value unchanged
    assert "recorded reply" in text and "highlighted" in text  # the SAMPLE_MODE wording


def test_docker_check_workflow_builds_runs_and_posts_all_three_examples() -> None:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = wf["jobs"]["docker-check"]
    assert job["timeout-minutes"] <= 15
    script = "\n".join(step.get("run", "") for step in job["steps"])
    assert "docker build -t explain-why-agent ." in script
    assert re.search(r"docker run -d --name ewa -p 8000:8000 -e SAMPLE_MODE=true explain-why-agent", script)
    assert "--env-file" not in script
    assert "seq 1 60" in script and "/health" in script  # capped wait, at most 60 tries of 1 s
    assert "for n in 1 2 3" in script and "-d @input_examples/example_$n.json" in script
    assert "model_validate_json" in script and "docker logs" in script and "docker stop" in script
    assert all("--max-time" in line for line in script.splitlines() if line.strip().startswith(("curl", "code=$(curl")))
    assert job["steps"][-1]["if"] == "always()"
