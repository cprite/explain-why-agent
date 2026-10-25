"""README.md and metadata.json for judges (Sprint 15, issue #33).

Checks that the submission documents match the repository: the 14 README sections in order, the one
quick-start block and what it may do, commands, flags, paths and variable names that exist, every
Results number found in the file it names, metadata.json's shape and paths, the Meterless test
command, and no secrets.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest

from app.config import REPO_ROOT

README = REPO_ROOT / "README.md"
METADATA = REPO_ROOT / "metadata.json"

SECTIONS = [
    "Summary",
    "Quick start (sample mode)",
    "Docker",
    "Full mode",
    "Usage",
    "How it works",
    "Results",
    "Sponsor technology",
    "Zetaris USL: reflection",
    "AI and model usage",
    "Data",
    "Limitations",
    "Pre-existing components",
    "Third-party code and licences",
]
SPONSOR_SUBSECTIONS = [
    "Zetaris",
    "Meterless",
    "Meterless Nightshift",
    "NVIDIA",
    "Cursor",
    "What was unique about our use of the sponsor technologies",
]
REPO_DIRS = ("app/", "data/", "data-prep/", "docs/", "eval/", "scripts/", "tests/", "web/", "input_examples/",
             "output_examples/", ".github/")
STDLIB_MODULES = {"venv", "pip"}
ROOT_FILES = ("run.py", "requirements.txt", "requirements-dev.txt", ".env.example", "metadata.json", "README.md",
              "LICENSE", "docker-compose.zetaris-sources.yml", "pytest.ini")


def _load_quickstart():
    spec = importlib.util.spec_from_file_location("readme_quickstart", REPO_ROOT / "scripts" / "readme_quickstart.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def readme() -> str:
    return README.read_text(encoding="utf-8")


def section(title: str, level: int = 2) -> str:
    """The text of one section, up to the next heading of the same or a higher level."""
    text = readme()
    marks = "#" * level
    start = re.search(rf"^{marks} {re.escape(title)}\s*$", text, re.MULTILINE)
    assert start, f"no '{marks} {title}' heading"
    rest = text[start.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def strip_fences(text: str) -> str:
    return re.sub(r"^```.*?^```", "", text, flags=re.MULTILINE | re.DOTALL)


def fenced_blocks(text: str) -> list[str]:
    return re.findall(r"^```[^\n]*\n(.*?)^```", text, flags=re.MULTILINE | re.DOTALL)


def commands() -> list[str]:
    """Every shell command in the README: fenced bash lines and inline `python …` spans."""
    lines = []
    for block in fenced_blocks(readme()):
        joined = block.replace("\\\n", " ")
        lines += [ln.strip() for ln in joined.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    lines += re.findall(r"`((?:[A-Z_]+=\S+ )*python3? [^`]+)`", strip_fences(readme()))
    return lines


def python_invocations() -> list[tuple[str, list[str]]]:
    """(target, flags) for each `python X.py …` / `python -m pkg …` command."""
    out = []
    for line in commands():
        for part in re.split(r"&&|\||;", line):
            m = re.search(r"\bpython3?\s+(-m\s+)?(\S+)(.*)", part)
            if not m or m.group(2).startswith("-") or (m.group(1) and m.group(2) in STDLIB_MODULES):
                continue
            target = m.group(2)
            if m.group(1):
                target = "-m " + target
            out.append((target, re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", m.group(3))))
    return out


def module_files(target: str) -> list[Path]:
    if target.startswith("-m "):
        mod = target[3:].replace(".", "/")
        candidates = [REPO_ROOT / f"{mod}.py", REPO_ROOT / mod / "__main__.py", REPO_ROOT / mod / "__init__.py"]
        files = [p for p in candidates if p.is_file()]
        if (REPO_ROOT / mod).is_dir():
            files += sorted((REPO_ROOT / mod).glob("*.py"))
        return files
    return [REPO_ROOT / target] if (REPO_ROOT / target).is_file() else []


# --- 1. sections ---------------------------------------------------------------------------------


def test_readme_has_the_fourteen_sections_in_order() -> None:
    headings = re.findall(r"^## (.+?)\s*$", strip_fences(readme()), re.MULTILINE)
    assert headings == SECTIONS


def test_sponsor_section_has_one_subsection_per_sponsor_in_order() -> None:
    headings = re.findall(r"^### (.+?)\s*$", section("Sponsor technology"), re.MULTILINE)
    assert headings == SPONSOR_SUBSECTIONS


def test_summary_names_the_track_and_what_the_agent_does() -> None:
    text = section("Summary")
    assert "Track 02" in text
    for phrase in ("why a business number changed", "four data sources", "disprove its own explanation",
                   "cannot be determined"):
        assert phrase in text


def test_zetaris_reflection_answers_the_three_questions() -> None:
    text = section("Zetaris USL: reflection")
    for question in ("How the USL saved time", "How it is useful beyond the hackathon", "How Zetaris could improve it"):
        assert f"**{question}" in text


def test_docker_section_says_sprint_16_and_metadata_has_no_docker_entrypoint() -> None:
    text = section("Docker")
    assert "Docker: added in Sprint 16" in text
    assert "docker run" not in text and "docker build" not in text
    assert json.loads(METADATA.read_text(encoding="utf-8"))["entrypoints"]["docker"] is None


# --- 2. quick start block ------------------------------------------------------------------------


def test_exactly_one_quickstart_block_inside_the_quick_start_section() -> None:
    qs = _load_quickstart()
    assert len(qs.extract_blocks(readme())) == 1
    assert len(qs.extract_blocks(section("Quick start (sample mode)"))) == 1


def test_quickstart_block_needs_no_credential_or_network_beyond_pip() -> None:
    block = _load_quickstart().extract_block(readme())
    assert "SAMPLE_MODE=true" in block
    assert re.search(r"^pip install -r requirements\.txt$", block, re.MULTILINE)
    assert not re.search(r"\b(curl|wget|ssh|git clone|docker)\b|https?://", block)
    names = set(_load_quickstart().env_example_names())
    assigned = set(re.findall(r"\b([A-Z][A-Z0-9_]*)=", block))
    assert assigned <= {"SAMPLE_MODE"}, f"the block sets more than SAMPLE_MODE: {assigned}"
    secrets = {n for n in names if re.search(r"TOKEN|KEY|PASSWORD|USERNAME|URL|ORG_ID", n)}
    assert not any(n in block for n in secrets)


def test_quickstart_block_runs_the_day1_question_and_lists_result_and_trace() -> None:
    block = _load_quickstart().extract_block(readme())
    run_line = next(ln for ln in block.splitlines() if "python run.py" in ln)
    assert "--run-id quickstart" in run_line
    assert "logs/result-quickstart.json" in block and "logs/trace-quickstart.jsonl" in block


def test_clean_env_drops_every_env_example_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    qs = _load_quickstart()
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "x")
    monkeypatch.setenv("ZETARIS_API_KEY", "x")
    monkeypatch.setenv("SAMPLE_MODE", "false")
    env = qs.clean_env()
    assert "METERLESS_RUNTIME_TOKEN" not in env and "ZETARIS_API_KEY" not in env
    assert env["SAMPLE_MODE"] == "true"
    assert "PATH" in env


def test_extract_block_rejects_zero_or_two_blocks() -> None:
    qs = _load_quickstart()
    one = "```bash readme-quickstart\necho hi\n```\n"
    assert qs.extract_block(one) == "echo hi\n"
    with pytest.raises(ValueError):
        qs.extract_block("no block")
    with pytest.raises(ValueError):
        qs.extract_block(one + one)


def test_ci_runs_the_quickstart_from_a_fresh_checkout_with_an_empty_env() -> None:
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci[ci.index("\n  readme-quickstart:"):]
    assert "path: readme-check" in job
    assert ": > .env" in job
    assert "python3 scripts/readme_quickstart.py --run" in job
    assert '- name: "Plan check O (task 23)' in job


# --- 3. commands, flags, paths, variables --------------------------------------------------------


def test_every_python_command_targets_an_existing_script_or_module_with_existing_flags() -> None:
    invocations = python_invocations()
    assert len(invocations) >= 10
    for target, flags in invocations:
        files = module_files(target)
        assert files, f"README runs `python {target}`, which does not exist"
        source = "\n".join(p.read_text(encoding="utf-8") for p in files)
        for flag in flags:
            assert f'"{flag}"' in source, f"`python {target}` has no flag {flag}"


def test_pytest_node_ids_in_the_readme_exist() -> None:
    nodes = re.findall(r"(tests/test_\w+\.py)(?:::(\w+))?", readme())
    assert nodes
    for path, func in nodes:
        file = REPO_ROOT / path
        assert file.is_file(), path
        if func:
            names = {n.name for n in ast.walk(ast.parse(file.read_text(encoding="utf-8")))
                     if isinstance(n, ast.FunctionDef)}
            assert func in names, f"{path}::{func} does not exist"


def test_repository_paths_in_backticks_exist() -> None:
    spans = re.findall(r"`([^`\s]+)`", readme())
    checked = 0
    for span in spans:
        path = span.rstrip(".,:")
        if any(ch in path for ch in "<>*{}…") or path.startswith(("logs/", "/", "http")):
            continue
        if path.startswith(REPO_DIRS) or path in ROOT_FILES:
            checked += 1
            assert (REPO_ROOT / path).exists(), f"README names `{path}`, which is not in the repository"
    assert checked >= 30


def test_markdown_links_to_repository_files_and_anchors_resolve() -> None:
    text = readme()
    anchors = set()
    for heading in re.findall(r"^#{2,3} (.+?)\s*$", strip_fences(text), re.MULTILINE):
        anchors.add(re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-"))
    links = re.findall(r"\]\(([^)\s]+)\)", text)
    assert links
    for link in links:
        if link.startswith(("http://", "https://")):
            continue
        if link.startswith("#"):
            assert link[1:] in anchors, f"anchor {link} has no heading"
        else:
            assert (REPO_ROOT / link.split("#")[0]).exists(), f"link {link} does not resolve"


def test_env_names_in_the_readme_are_in_env_example_or_the_code() -> None:
    documented = set(_load_quickstart().env_example_names())
    code = "\n".join(p.read_text(encoding="utf-8") for p in (REPO_ROOT / "app").rglob("*.py"))
    names = set(re.findall(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b", readme()))
    assert len(names) >= 40
    for name in names:
        assert name in documented or name in code, f"{name} is neither in .env.example nor in app/"


def test_full_mode_lists_every_env_example_variable() -> None:
    text = section("Full mode")
    missing = [n for n in _load_quickstart().env_example_names() if f"`{n}`" not in text]
    assert not missing, f"Full mode does not list {missing}"


def test_api_endpoints_in_usage_exist() -> None:
    main = (REPO_ROOT / "app" / "api" / "main.py").read_text(encoding="utf-8")
    routes = {(m, re.sub(r"\{\w+\}", "{}", p)) for m, p in re.findall(r'@app\.(get|post)\("([^"]+)"', main)}
    used = re.findall(r"`(GET|POST) (/[^`\s]*)`", section("Usage"))
    assert len(used) >= 5
    for method, path in used:
        assert (method.lower(), re.sub(r"\{\w+\}", "{}", path)) in routes, f"{method} {path} is not an API route"


def test_requirements_each_have_a_licence_row() -> None:
    text = section("Third-party code and licences")
    for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, version = line.strip().split("==")
        assert re.search(rf"^\| {re.escape(name)} \| {re.escape(version)} \| \S", text, re.MULTILINE), name
    assert "Adtributor" in text and "STL" in text


# --- 4. Results numbers ---------------------------------------------------------------------------


def results_rows() -> list[tuple[list[str], str]]:
    """(cells other than the source, source path) for every row of every table in Results."""
    rows = []
    header = None
    for line in section("Results").splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if set(line.replace("|", "").strip()) <= set("-: "):
            continue
        source_cell = cells[header.index("Source")]
        others = [c for i, c in enumerate(cells) if i != header.index("Source")]
        rows.append((others, source_cell))
    return rows


def test_results_tables_have_a_source_column() -> None:
    tables = re.findall(r"^\|([^\n]+)\|\n\|[-:| ]+\|$", section("Results"), re.MULTILINE)
    assert len(tables) >= 3
    for header in tables:
        assert "Source" in [c.strip() for c in header.split("|")]


def test_every_results_number_appears_in_its_committed_source_file() -> None:
    rows = results_rows()
    assert len(rows) >= 10
    checked = 0
    for cells, source in rows:
        numbers = [n for c in cells for n in re.findall(r"\d+(?:[./]\d+)*", c)]
        if not numbers:
            assert "not measured yet" in " ".join(cells) or source == "none committed", cells
            continue
        m = re.fullmatch(r"`([^`]+)`", source)
        assert m, f"row {cells} has numbers but no source file: {source!r}"
        path = REPO_ROOT / m.group(1)
        assert path.is_file(), f"source {m.group(1)} is not a committed file"
        text = path.read_text(encoding="utf-8")
        for number in numbers:
            assert number in text, f"{number} (row {cells[0]!r}) is not in {m.group(1)}"
            checked += 1
    assert checked >= 20


def test_results_prose_has_no_unsourced_numbers() -> None:
    prose = [ln for ln in section("Results").splitlines() if ln.strip() and not ln.startswith("|")]
    for line in prose:
        without_code = re.sub(r"`[^`]*`", "", line)
        assert not re.search(r"\d", without_code), f"number outside a sourced table: {line!r}"


def test_not_measured_rows_for_the_live_score_and_live_run_time() -> None:
    text = section("Results")
    assert re.search(r"^\| Evaluation score \(answer key, live[^|]*\| not measured yet \|", text, re.MULTILINE)
    assert re.search(r"^\| Run time, live[^|]*\| not measured yet \|", text, re.MULTILINE)


# --- 5. Meterless test command --------------------------------------------------------------------


def test_meterless_section_names_a_test_command_and_its_result() -> None:
    text = section("Meterless", level=3)
    assert "python scripts/check_markovian_run.py" in text
    assert "[PASS] 5/8 chunks, every chunk input within budget, stop_reason=completed" in text
    for path in ("app/engines/world_model/", "app/engines/markovian/", "tests/test_world_context.py",
                 "tests/test_markovian_orchestrator.py"):
        assert path in text
        assert (REPO_ROOT / path).exists()
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/check_markovian_run.py" in ci  # plan check J runs the same command in CI
    assert "test_plan_check_task9_critique_has_support_and_refutation_within_budget" in ci


# --- 6. metadata.json ----------------------------------------------------------------------------


def metadata() -> dict:
    return json.loads(METADATA.read_text(encoding="utf-8"))


def test_metadata_follows_the_shape() -> None:
    data = metadata()
    assert data["name"] == "explain-why-agent"
    assert data["track"].startswith("02")
    assert data["entrypoints"]["cli"] == 'python run.py "<question>"'
    assert data["entrypoints"]["api"] == "POST /run"
    assert "docker" in data["entrypoints"]
    assert data["sample_mode"] == {**data["sample_mode"], "env": "SAMPLE_MODE=true", "needs_network": False,
                                   "needs_credentials": False}
    sponsors = {s["sponsor"]: s for s in data["sponsors"]}
    assert list(sponsors) == ["Zetaris", "Meterless", "Meterless Nightshift", "NVIDIA", "Cursor"]
    assert sponsors["Zetaris"]["required"] and sponsors["Zetaris"]["role"] == "data layer"
    assert sponsors["Meterless"]["engines"] == ["World Model", "Markovian"] and sponsors["Meterless"]["required"]
    assert sponsors["Meterless Nightshift"]["role"] == "primary AI provider"
    assert sponsors["NVIDIA"]["via"] == "Meterless Nightshift"
    assert sponsors["Cursor"]["required"] is False
    assert data["examples"] == {"inputs": "input_examples/", "outputs": "output_examples/"}
    assert data["pre_existing"] == "docs/PRE-EXISTING.md"
    assert data["data_licence"] == "CC BY-NC-SA 4.0 (Olist)"
    assert data["synthetic_incidents"] is True


def metadata_paths() -> list[str]:
    data = metadata()
    paths = [data["pre_existing"], *data["examples"].values()]
    for sponsor in data["sponsors"]:
        for key in ("code", "tests", "evidence"):
            paths += sponsor.get(key, [])
    return paths


def test_every_metadata_path_exists() -> None:
    paths = metadata_paths()
    assert len(paths) >= 15
    for path in paths:
        assert (REPO_ROOT / path).exists(), f"metadata.json lists {path}, which is not in the repository"


def test_metadata_entrypoints_match_the_code() -> None:
    entry = metadata()["entrypoints"]
    assert entry["cli"].startswith("python run.py")
    assert entry["api_start"] == "python -m app.api" and (REPO_ROOT / "app" / "api" / "__main__.py").is_file()
    assert '@app.post("/run")' in (REPO_ROOT / "app" / "api" / "main.py").read_text(encoding="utf-8")


def test_nvidia_models_are_the_routed_models_in_the_recorded_cache() -> None:
    routed = set()
    for entry in (REPO_ROOT / "data" / "sample" / "llm_cache").glob("*.json"):
        data = json.loads(entry.read_text(encoding="utf-8"))
        if data.get("recorded_with") == "meterless":
            routed.add(data.get("model_routed"))
    models = next(s for s in metadata()["sponsors"] if s["sponsor"] == "NVIDIA")["models"]
    assert models and set(models) == routed
    for model in models:
        assert model in section("NVIDIA", level=3)


# --- 7. secrets ----------------------------------------------------------------------------------

IPV4 = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")


@pytest.mark.parametrize("path", [README, METADATA], ids=lambda p: p.name)
def test_no_secrets_hosts_or_personal_emails(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "nvapi-" not in text
    assert not re.search(r"(?<![\w-])sk-[A-Za-z0-9]", text)
    assert "@gmail" not in text.lower()
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), "an email address"
    assert not re.search(r"rt_[A-Za-z0-9]{12,}|rcpt_[a-z0-9]{6,}", text), "a token or receipt id"
    for m in IPV4.finditer(text):
        if all(0 <= int(p) <= 255 for p in m.groups()):
            assert m.group(0) in {"127.0.0.1", "0.0.0.0"}, f"IPv4 address {m.group(0)}"
    assert not re.search(r"\b[\w-]+\.(?:compute\.amazonaws\.com|ngrok\.\w+)\b", text), "a real hostname"


def test_secret_grep_catches_what_it_should() -> None:
    sample = "key nvapi-abc, sk-abc123, me@gmail.com, host 10.1.2.3, local 127.0.0.1"
    assert "nvapi-" in sample and re.search(r"(?<![\w-])sk-[A-Za-z0-9]", sample)
    found = [m.group(0) for m in IPV4.finditer(sample)]
    assert found == ["10.1.2.3", "127.0.0.1"]
