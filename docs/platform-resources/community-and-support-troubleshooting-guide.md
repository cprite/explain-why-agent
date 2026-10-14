# Troubleshooting Guide

Folder: Community and Support · updated 2026-10-13

# Troubleshooting Guide

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**

This guide covers the problems that eat build time: Docker, dependencies, provider auth, rate limits, sponsor technology setup, data downloads, runaway agent loops and logs. Work through it before asking for help.

Support during the event lives on HackOS: the #help desk channel, each sponsor's Help channel, the sponsor folders in Resources, and mentor office hours.

---

## 1. Fast Triage

| Symptom | Likely cause | Go to |
|---|---|---|
| `docker build` fails | Dockerfile, dependency, OS package, Python version | [2. Docker](#2-docker) |
| Container runs but nothing responds | Wrong port, bound to `localhost`, server not started | [2.4](#24-container-runs-but-the-port-does-not-respond) |
| `ModuleNotFoundError` | Missing or conflicting dependency | [3. Python and dependencies](#3-python-and-dependencies) |
| `401` or `403` from your model provider | Missing or wrong key, wrong base URL | [4. Provider auth](#4-provider-authentication) |
| `429` or rate limit error | Too many calls, too much concurrency | [5. Rate limits and cost](#5-rate-limits-and-cost) |
| `model_not_found` | Wrong model name for your provider | [6. Model errors](#6-model-errors) |
| Zetaris, Meterless, NVIDIA or Cursor problem | Setup step missed, wrong settings | [7. Sponsor technology](#7-sponsor-technology) |
| Data fails to download | Broken URL, auth required, timeout | [8. Data](#8-data) |
| Run never finishes | Unbounded loops, heavy calls, no timeouts | [9. Runs that never end](#9-runs-that-never-end) |
| Logs don't show the agent working | No trace logging, or a linear pipeline | [10. Logs](#10-logs-and-traces) |
| Works locally, fails in Docker | Environment mismatch, hidden local files | [11. Works locally, fails in Docker](#11-works-locally-fails-in-docker) |

---

## 2. Docker

Docker is the most reliable way to make sure a judge gets the same result you do.

### 2.1 What good looks like

```bash
docker build -t oah-submission .

docker run --rm -p 8000:8000 --env-file .env oah-submission
```

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d @input_examples/example_1.json
```

Dependencies install at build time, it runs without a local GPU, and a run finishes in minutes.

### 2.2 Build fails

Common errors:

```text
ERROR: Could not find a version that satisfies the requirement ...
Building wheel for package failed
No matching distribution found
COPY failed: file not found in build context
```

Checklist:

1. Start from a supported base image: `FROM python:3.11-slim`
2. Confirm `requirements.txt` is in the repository root
3. Copy dependencies before app code, so the layer caches:

```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

4. Check `.dockerignore` isn't excluding something you need
5. Install native build tools only if a package needs them:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*
```

6. Rebuild clean: `docker build --no-cache -t oah-submission .`

### 2.3 A Dockerfile that works

```dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/logs

EXPOSE 8000

CMD ["python", "run.py"]
```

If you ship a UI on a second port, expose that too.

### 2.4 Container runs but the port does not respond

```bash
curl http://localhost:8000/health
# curl: (7) Failed to connect to localhost port 8000
```

| Cause | Fix |
|---|---|
| App binds to `127.0.0.1` inside Docker | Bind to `0.0.0.0` |
| Wrong port | Match the port you mapped |
| `run.py` exits immediately | Start a persistent server |
| Missing port mapping | Add `-p 8000:8000` |

```python
# run.py
import os
import uvicorn
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/run")
def run(payload: dict):
    return {"result": "received", "input": payload}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
```

### 2.5 Image is huge or slow to build

Use `python:3.11-slim`, don't copy large datasets in, and use a `.dockerignore`:

```gitignore
.git
__pycache__/
*.pyc
.env
.venv/
venv/
.ipynb_checkpoints/
.cache/
dist/
build/
*.mp4
*.mov
*.zip
data/raw_large/
logs/*.log
```

Don't ignore things judges need: `input_examples/`, `output_examples/`, `README.md`, `.env.example`.

---

## 3. Python and Dependencies

### 3.1 Version

Python 3.11 unless your framework needs otherwise. If your machine runs something else, test in Docker.

### 3.2 `ModuleNotFoundError`

Add it to `requirements.txt`, reinstall, rebuild with `--no-cache`. The usual cause is a package you installed locally weeks ago and never declared.

### 3.3 Dependency conflicts

```text
ResolutionImpossible
```

Start clean and add packages one at a time:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install fastapi uvicorn openai python-dotenv requests
pip install langgraph           # then your agent framework
pip freeze > requirements.txt   # only once it works
```

Every extra dependency is another way the build can fail. Keep the list short.

If `pip install` fails with `externally-managed-environment`, your system Python blocks global installs. Use a virtual environment as above.

### 3.4 Baseline requirements

Direct provider API:

```text
fastapi==0.115.0
uvicorn==0.30.6
openai>=1.40.0
python-dotenv==1.0.1
pydantic>=2.7.0
requests>=2.32.0
```

LangGraph or LangChain:

```text
fastapi==0.115.0
uvicorn==0.30.6
openai>=1.40.0
python-dotenv==1.0.1
requests>=2.32.0
langchain
langchain-openai
langgraph
```

Retrieval-heavy:

```text
numpy
pandas
faiss-cpu
tiktoken
```

Avoid libraries that need a local GPU. Assume a judge has an ordinary machine.

### 3.5 Never install at runtime

```python
os.system("pip install some-package")   # don't
```

Everything installs at build or setup time.

---

## 4. Provider Authentication

Model choice is open, so the exact errors depend on your provider. The causes rarely do.

### 4.1 Environment variables, always

```bash
export MODEL_API_KEY="your-key"
export MODEL_BASE_URL="https://api.your-provider.example/v1"
export MODEL_NAME="your-model"
```

`.env.example` gets placeholders only. `.env` goes in `.gitignore`.

### 4.2 A connection test script

Put this in `scripts/check_provider.py` and run it before you debug anything else:

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["MODEL_API_KEY"],
    base_url=os.environ.get("MODEL_BASE_URL"),
)

response = client.chat.completions.create(
    model=os.environ["MODEL_NAME"],
    messages=[{"role": "user", "content": "Reply with: connection OK"}],
    temperature=0,
)

print(response.choices[0].message.content)
```

### 4.3 `401 Unauthorized`

- Key missing from the environment
- Extra spaces or quotes around the key
- Wrong key copied
- Key rotated or revoked
- The key doesn't match the provider in `MODEL_BASE_URL`
- Code not actually reading the environment variable

Check what your process sees:

```bash
echo "$MODEL_BASE_URL"
echo "${MODEL_API_KEY:0:8}..."
```

Never paste a full key anywhere, including a support request.

### 4.4 `403 Forbidden`

Usually the key is valid but not entitled to that model, or the account needs billing or credit enabled. Try your provider's cheapest model first. If that works, it's an entitlement problem, not a key problem.

### 4.5 Base URL mistakes

A trailing slash, a missing `/v1`, or a typo in the host produces confusing errors. Compare yours against your provider's documentation character by character.

### 4.6 It works locally but not in Docker

The container doesn't inherit your shell. Pass the variables in:

```bash
docker run --rm -p 8000:8000 --env-file .env oah-submission
```

---

## 5. Rate Limits and Cost

You pick your provider, so you carry its limits and its bill, except where sponsor credits or free access cover it.

### 5.1 `429` and rate limit errors

Before escalating anything:

**Reduce concurrency.** Parallel agent calls are the usual culprit.

```python
MAX_PARALLEL_AGENT_CALLS = 2
```

**Cap output length.**

```python
response = client.chat.completions.create(
    model=os.getenv("MODEL_NAME"),
    messages=messages,
    max_tokens=800,
    temperature=0.2,
)
```

**Shorten prompts.** Don't send whole datasets. Summarise, retrieve the relevant chunks, or embed.

**Cache repeated calls.** Planners often ask the same question twice.

**Add backoff and cap retries.**

```python
import time
import random

def call_with_retries(fn, max_retries=3):
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = min(30, (2 ** attempt) + random.random())
            print(f"[retry] {type(e).__name__}. Waiting {wait:.1f}s")
            time.sleep(wait)
```

Never retry indefinitely. An unbounded retry loop can burn a day's budget or credit while you sleep.

### 5.2 Watching usage

Agent loops multiply token use fast. A planner ↔ executor ↔ evaluator loop over three rounds is nine calls per run, and you will run it hundreds of times in six days.

- Check your credit or rate limits with your provider on day one
- Use a smaller model for routine steps, a larger one for the hard reasoning step
- Develop against sample mode so you're not spending on testing plumbing
- Cap `MAX_AGENT_ROUNDS`
- Keep your product's model key out of Cursor, so coding never uses it

---

## 6. Model Errors

### 6.1 `model_not_found`

The model name doesn't exist on that provider, or your account lacks access. Model names differ between providers and change often. Copy the exact model ID from your provider rather than from a tutorial.

Read it from configuration, never hardcode:

```python
model = os.getenv("MODEL_NAME")
```

### 6.2 Message format errors

```python
messages=[
    {"role": "system", "content": "You are a planning agent."},
    {"role": "user", "content": "Create a plan."},
]
```

Not `messages="Create a plan"`, and not `[{"user": "..."}]`.

### 6.3 Embeddings

```python
embedding = client.embeddings.create(
    model=os.getenv("EMBEDDING_MODEL"),
    input="Text to embed",
)
vector = embedding.data[0].embedding
```

Failures usually mean: input too long, input empty, you passed a DataFrame or dict instead of strings, or you're embedding thousands of chunks in one run.

```python
texts = [str(x)[:4000] for x in texts if str(x).strip()]
```

Pre-compute embeddings where you can, rather than doing it inside a judged run.

---

## 7. Sponsor Technology

Setup steps and documentation for each sponsor are in its folder in Resources on HackOS. Check there first, then ask in that sponsor's Help channel.

### 7.1 Zetaris

| Symptom | Likely cause | Fix |
|---|---|---|
| You don't have the platform bundle or registry credentials | They haven't reached you yet | Ask in Help Zetaris, well before the event |
| `./preflight.sh` reports failures | Docker isn't running, has too little memory or disk, or the registry sign-in is missing | Give Docker 8 GB and 4 CPUs, free 15 GB of disk, rerun the registry sign-in, then rerun preflight |
| `docker compose pull` fails with "denied" or "unauthorized" | The registry didn't accept your sign-in | Rerun `docker login` with the registry credentials you were given |
| `./verify.sh` fails right after starting | First-time setup is still running | Wait until bootstrap shows `Exited (0)`, wait a minute, run it again |
| Very slow first start on a Mac | Apple Silicon runs the images under emulation | Turn on **Use Rosetta** in Docker Desktop and allow extra time |
| Sign-in fails | Wrong email or password; editing `.env` after the first start doesn't reset an existing account | Use the details you set before the first start |
| REST requests return `401` | Zetaris API key missing, wrong or expired | Create a new key in the Zetaris web interface and update `.env` |
| REST requests return `400` | Wrong `X-Org-ID`, or `X-Request-ID` isn't a UUID | Use organisation ID `1` on a local install and a fresh UUID for every request |
| "Object already exists" | You already ran that create statement | Check the existing object matches, then move on |
| A table is created but returns no rows | Zetaris can't reach the source, or the path is wrong | Check the source address, and that Zetaris itself can reach it |
| A file on your laptop won't query | Zetaris can't read files on your laptop | Put the file in storage Zetaris can reach, such as an S3 bucket, then register it |
| Your Dockerised agent can't reach Zetaris on `localhost` | Inside a container, `localhost` means the container | Use `http://host.docker.internal:8888/api/v1.0` on Mac and Windows, or run with `--network host` on Linux |

Quick REST check:

```python
import os, uuid, requests

r = requests.post(
    os.environ["ZETARIS_REST_URL"].rstrip("/") + "/sql-editor/sqls/run",
    headers={
        "Authorization": "Bearer " + os.environ["ZETARIS_API_KEY"],
        "X-Org-ID": os.environ["ZETARIS_ORG_ID"],
        "X-Request-ID": str(uuid.uuid4()),
    },
    json={"queryId": str(uuid.uuid4()), "sql": "SELECT 1", "source": "SqlEditor", "limit": 1},
    timeout=60,
)
print(r.status_code, r.text[:200])
```

### 7.2 Meterless

| Symptom | Likely cause | Fix |
|---|---|---|
| Calls fail even though each setting looks right | Settings mixed from two routes, such as a Meterless key with another provider's address | Take the address, key and model ID all from your Meterless account |
| `401` | The key doesn't match the address | Copy the key again from Meterless |
| `404` or "model not found" | The model ID doesn't match the Meterless model list | Copy the exact model ID shown in Meterless |
| Credit or rate-limit error | Your Meterless credit has run out | Check your credit, and ask in Help Meterless |
| Meterless credit drops while you're coding | Your Meterless key is in Cursor's settings | Remove it from Cursor; code with Cursor's own models |

### 7.3 NVIDIA

| Symptom | Likely cause | Fix |
|---|---|---|
| `401` | Key doesn't match the route, or was mistyped | Create or copy your key again on build.nvidia.com; keys start with `nvapi-` |
| `404` or "model not found" | Wrong model ID | Copy the exact model ID from the model page on build.nvidia.com |
| Calls fail with a Meterless key | Settings mixed from two routes | Use NVIDIA's address, key and model ID together |
| Rate-limit errors | Free-tier limits reached | Wait and retry, check your limits, or switch routes |

NVIDIA's API address is `https://integrate.api.nvidia.com/v1`. Create keys only on build.nvidia.com itself: look-alike sites are not run by NVIDIA.

### 7.4 Cursor

| Symptom | Likely cause | Fix |
|---|---|---|
| Composer or Grok missing from the model menu, or requests stop | Your Cursor credit isn't active or has run out | Check your plan and usage in Cursor's settings, then ask in Help Cursor |
| Charges on your product's provider while coding | Your provider key is in Cursor's settings | Remove it; code with Cursor's own models |
| An MCP server doesn't appear in Cursor | A JSON typo or wrong token in `.cursor/mcp.json` | Open the Output panel, choose MCP Logs, fix the error and restart Cursor |
| The Agent can't edit files or run commands | Workspace or permission issue | Reopen the project folder in Cursor and approve the tool call when asked |

### 7.5 General advice

Put every sponsor call behind an adapter with a timeout and a fallback. If a service is down during judging, a project that degrades gracefully still scores; one that crashes does not.

---

## 8. Data

### 8.1 Download script pattern

```python
import requests
from pathlib import Path

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

URL = "https://example.com/sample.csv"
OUT = DATA_DIR / "sample.csv"

def download():
    if OUT.exists():
        print(f"Data already exists: {OUT}")
        return
    response = requests.get(URL, timeout=30)
    response.raise_for_status()
    OUT.write_bytes(response.content)
    print(f"Saved to {OUT}")

if __name__ == "__main__":
    download()
```

### 8.2 Timeouts on everything

```python
requests.get(url)                      # will hang forever one day
requests.get(url, timeout=(5, 30))     # better
```

### 8.3 Sample mode

Every project that touches external data should have one:

```python
import os
import pandas as pd

def load_data():
    if os.getenv("SAMPLE_MODE", "false").lower() == "true":
        return pd.read_csv("data/sample.csv")
    try:
        return fetch_live_data()
    except Exception as e:
        print(f"[data] Live fetch failed: {e}; using sample")
        return pd.read_csv("data/sample.csv")
```

This is what lets a judge without your credentials see the system work.

### 8.4 Data sources that cause trouble

| Source type | Problem | Fix |
|---|---|---|
| Large public APIs | Timeouts, huge responses | Narrow the date range and query, cache a sample |
| Paginated APIs | Pagination not handled, silent truncation | Handle pages, cap the total |
| Auth-gated datasets | Won't download in a clean environment | Ship a small permitted sample instead |
| Access-controlled datasets | Judges can't get them | Use synthetic or open data, and say so |

---

## 9. Runs That Never End

### 9.1 Usual causes

| Cause | Fix |
|---|---|
| Downloading a large dataset mid-run | Cached sample or a narrow query |
| Too many model calls | Fewer agent rounds, fewer retries |
| Enormous prompts | Retrieve the relevant chunks only |
| Unbounded agent debate | Cap the rounds |
| No request timeouts | Add them everywhere |
| Heavy local models | Use hosted models instead |

### 9.2 A global deadline

```python
import time

class Deadline:
    def __init__(self, seconds):
        self.start = time.time()
        self.seconds = seconds

    def remaining(self):
        return self.seconds - (time.time() - self.start)

    def check(self):
        if self.remaining() <= 0:
            raise TimeoutError("Execution deadline reached")

deadline = Deadline(10 * 60)
```

Check it inside every loop.

### 9.3 Cap the rounds

```python
# don't
while not evaluator_satisfied:
    run_agents()

# do
MAX_AGENT_ROUNDS = 3
for round_id in range(MAX_AGENT_ROUNDS):
    result = run_agent_round(round_id)
    if result["accepted"]:
        break
```

### 9.4 How many calls is reasonable

A good run rarely needs dozens. Aim for 1–3 planner calls, 1–5 executor or tool calls, 1–3 critic calls and one synthesis call. Fifty calls per run means timeouts, rate limits and a bill.

### 9.5 Degrade, don't crash

```python
try:
    live_data = fetch_live_data()
except Exception as e:
    trace("DataAgent", "fallback", f"Live fetch failed: {e}")
    live_data = load_sample_data()

final = synthesize_result(live_data)
```

Graceful failure scores. A stack trace does not.

---

## 10. Logs and Traces

### 10.1 Where

Write to `logs/` and print the important events to stdout.

### 10.2 A trace helper

```python
import json
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
TRACE_FILE = LOG_DIR / "agent_trace.jsonl"

def trace(agent_name, action, input_summary, output_summary="", target_agent=None,
          confidence=None, retry_count=0, status="success"):
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_name": agent_name,
        "action": action,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "target_agent": target_agent,
        "confidence": confidence,
        "retry_count": retry_count,
        "status": status,
    }
    line = json.dumps(event, ensure_ascii=False)
    print(line)
    with TRACE_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
```

Add it on day one. Retrofitting traces at 11pm on day six is how teams lose Technical points. Log your Zetaris and Meterless calls too, so judges can see the sponsor technology at work.

### 10.3 Weak versus strong

Weak:

```text
Agent A completed.
Agent B completed.
Agent C completed.
```

Strong:

```text
Planner delegated to ResearchAgent.
ResearchAgent queried Zetaris and returned incomplete evidence.
Evaluator challenged ResearchAgent.
ResearchAgent retried with a narrower query.
Planner revised the plan on the Evaluator's critique.
```

Never hand-write a trace. A trace that doesn't match the code is a disqualification risk, not a shortcut.

---

## 11. Works Locally, Fails in Docker

The classic final-day failure.

| Local works because | Docker fails because |
|---|---|
| You have unlisted packages installed | `requirements.txt` is incomplete |
| You have a local `.env` | Variables aren't passed to the container |
| You use absolute paths | The path doesn't exist in the container |
| You rely on cached data | The cache wasn't copied in |
| You started from a notebook | `run.py` is incomplete |
| Zetaris runs on your machine | `localhost` means the container; use `host.docker.internal` |

Test the real path:

```bash
docker build --no-cache -t oah-submission .
docker run --rm -p 8000:8000 --env-file .env -e SAMPLE_MODE=true oah-submission
```

And use relative paths:

```python
from pathlib import Path
ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "sample.csv"
```

---

## 12. Secrets

### 12.1 Check before you push

```bash
git status
git diff --cached

grep -R "sk-" . --exclude-dir=.git || true
grep -R "nvapi-" . --exclude-dir=.git || true
grep -R "API_KEY=" . --exclude-dir=.git --exclude=.env.example || true
```

### 12.2 If you commit a key

1. **Rotate it immediately.** This is the step that matters.
2. Remove it from the repository history.
3. Assume the old key is compromised.

Deleting the commit is not enough on its own, and your repository will be public.

### 12.3 `.env.example`

```env
# Model provider
MODEL_API_KEY=your-api-key-here
MODEL_BASE_URL=https://api.your-provider.example/v1
MODEL_NAME=your-default-model
EMBEDDING_MODEL=your-embedding-model

# Zetaris
ZETARIS_REST_URL=http://localhost:8888/api/v1.0
ZETARIS_ORG_ID=1
ZETARIS_API_KEY=your-key-here

# Meterless
METERLESS_API_KEY=your-key-here

# NVIDIA (if used directly)
NVIDIA_API_KEY=your-key-here

# Runtime
SAMPLE_MODE=true
MAX_AGENT_ROUNDS=3
MAX_RETRIES=3
REQUEST_TIMEOUT_SECONDS=30
```

---

## 13. Framework-Specific Notes

### LangChain / LangGraph

Point the client at your provider explicitly:

```python
import os
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model=os.getenv("MODEL_NAME"),
    api_key=os.environ["MODEL_API_KEY"],
    base_url=os.getenv("MODEL_BASE_URL"),
)
```

### CrewAI

CrewAI reads OpenAI-style variable names. Map yours before the crew starts:

```bash
export OPENAI_API_KEY="$MODEL_API_KEY"
export OPENAI_BASE_URL="$MODEL_BASE_URL"
export OPENAI_MODEL_NAME="$MODEL_NAME"
```

### AutoGen

```python
llm_config = {
    "config_list": [{
        "model": os.getenv("MODEL_NAME"),
        "api_key": os.environ["MODEL_API_KEY"],
        "base_url": os.getenv("MODEL_BASE_URL"),
    }],
    "temperature": 0.2,
}
```

### Direct SDK

```python
client = OpenAI(
    api_key=os.environ["MODEL_API_KEY"],
    base_url=os.getenv("MODEL_BASE_URL"),
)
```

The recurring bug across all of these: a default endpoint quietly used because `base_url` wasn't passed through.

---

## 14. Keeping Agents Cheap and Fast

### Hard limits

```env
MAX_AGENT_ROUNDS=3
MAX_RETRIES=3
MAX_TOOL_CALLS=10
MAX_INPUT_CHARS=12000
MAX_CONTEXT_CHUNKS=5
MAX_OUTPUT_TOKENS=1000
```

### Truncate safely

```python
def limit_text(text: str, max_chars: int = 12000) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[TRUNCATED]"
```

### Retrieve, don't dump

Send the top relevant chunks or query results, not the whole dataset. Let Zetaris filter with SQL before data reaches the model.

### Deterministic for demos

`temperature=0.2` and a capped `max_tokens` make your demo reproducible.

---

## 15. Error Cheat Sheet

| Error | Meaning | Fix |
|---|---|---|
| `401 Unauthorized` | Missing or invalid key | Check the environment variable reaches the process, and matches the route |
| `403 Forbidden` | No access to that model, or a billing or credit issue | Try a smaller model; check your account |
| `429` | Rate limited | Lower concurrency, add backoff |
| `model_not_found` | Wrong model ID | Copy the exact ID from your provider |
| `Connection refused` | Not running, or wrong port | Bind to `0.0.0.0`; check the port |
| `ModuleNotFoundError` | Missing dependency | Add to `requirements.txt` |
| `No such file or directory` | Wrong path in Docker | Use relative paths |
| `JSONDecodeError` | Malformed JSON | `python -m json.tool file.json` |
| `ReadTimeout` | External call timed out | Add a timeout and a fallback |
| `Killed` | Out of memory | Smaller data, smaller model, more Docker memory |
| `Permission denied: entrypoint.sh` | Not executable | `chmod +x entrypoint.sh` |
| `externally-managed-environment` | System Python blocks installs | Use a virtual environment |

---

## 16. Pre-Submission Check

### Repository

- [ ] Repository is public
- [ ] Entry point exists and is documented
- [ ] A programmatic interface works, not only a UI
- [ ] README covers setup, usage and dependencies, locally and in Docker
- [ ] `.env.example` present, no real keys
- [ ] At least 3 input examples and 3 matching outputs
- [ ] `logs/` exists or is created automatically
- [ ] No keys committed

### Docker

- [ ] `docker build` succeeds from clean
- [ ] `docker run` starts and responds
- [ ] Binds to `0.0.0.0`
- [ ] Dependencies install at build time
- [ ] No runtime `pip install`

### Provider and sponsor technology

- [ ] Credentials read from environment variables
- [ ] The provider connection test passes
- [ ] Zetaris and Meterless connect, or fail gracefully
- [ ] `SAMPLE_MODE=true` works with no credentials at all

### Runtime

- [ ] A run finishes in minutes
- [ ] External calls have timeouts
- [ ] Agent loops have a round cap
- [ ] Retries are capped with backoff
- [ ] Logs show real agent interaction

---

## 17. Asking for Help

```text
Issue summary:
[One sentence]

Expected:
[What should happen]

Actual:
[What happens]

Command:
[paste]

Error:
[paste, secrets removed]

Environment:
- OS:
- Python version:
- Docker version:
- Framework:
- Provider and model:
- Local or Docker:

Already tried:
- [1]
- [2]

Logs:
[relevant excerpt]

I confirm no API keys are in this message.
```

| Issue | Where |
|---|---|
| General technical questions | #help desk channel on HackOS |
| Zetaris setup, access, errors | Zetaris folder in Resources, then Help Zetaris |
| Meterless setup, access, errors | Meterless folder in Resources, then Help Meterless |
| Cursor setup and credit | Space XAI and Cursor folder in Resources, then Help Cursor |
| NVIDIA setup and errors | NVIDIA folder in Resources, then Help NVIDIA |
| Agent design, framework, debugging | Mentor office hours |
| Track scope | Challenge pages on HackOS |
| Rules and submission requirements | Official Rules, or hackathons@genai.works |
| Your own model provider account | Your provider's support |

Mentors can help you get unstuck. They can't debug your provider account for you.

---

## 18. The Golden Path

Run this before you submit. If it all works from a clean state, you're in good shape.

```bash
# 1. Clean environment
rm -rf .venv
python -m venv .venv
source .venv/bin/activate

# 2. Dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3. Configuration
cp .env.example .env     # fill in your keys
export SAMPLE_MODE="true"

# 4. Provider connection
python scripts/check_provider.py

# 5. Run
python run.py
```

In another terminal:

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d @input_examples/example_1.json
```

Then Docker:

```bash
docker build --no-cache -t oah-submission .
docker run --rm -p 8000:8000 --env-file .env -e SAMPLE_MODE=true oah-submission
```

And call it again. Then, crucially, **try it with sample mode and no credentials at all**, because that's how a judge may see it.

---

## 19. Final Reminder

Most lost points are preventable:

- Broken Docker build
- Nothing a judge can run programmatically
- Zetaris or Meterless not working, with no fallback
- No logs showing how the agent worked
- Hardcoded outputs
- Keys committed to the repository
- Runs that hang on an external call
- A project that only works on the author's laptop

Build defensively. Timeouts, fallbacks, sample mode, capped loops and honest logs. The goal is not an impressive demo. It is a system that runs the same way for someone who has never seen it.
