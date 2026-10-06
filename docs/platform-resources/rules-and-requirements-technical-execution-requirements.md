# Technical Execution Requirements

Folder: Rules and Requirements · updated 2026-09-30

# Technical Execution Guide

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**

This guide covers how to make your submission runnable, reproducible and judgeable. Judges have limited time per project. Anything they cannot start, call or read counts against you.

> **The official requirements are in section 6 of the Official Rules on the event page.** Where this guide and the Official Rules disagree, the Official Rules apply. Everything below is recommended practice, not a rule, unless the Rules say otherwise.

---

## 1. The Standard Every Submission Should Meet

| Area | Recommended standard |
|---|---|
| **Startup** | Runs from a clean checkout with a documented command, no manual fixing |
| **Interface** | Exposes a programmatic entry point, not only a user interface |
| **Reproducibility** | Docker or a documented environment setup that installs everything at build time |
| **Hardware** | Runs on a standard CPU machine; no GPU requirement |
| **Runtime** | A single run completes in minutes, not hours, with internal timeouts |
| **Secrets** | Loaded from environment variables only, never committed |
| **Data** | Small samples in the repository, scripts or APIs for anything larger |
| **Logs** | Printed to stdout and saved to `logs/`, showing how the agent worked |
| **Examples** | At least three sample inputs and their outputs |

---

## 2. Give Judges a Programmatic Entry Point

A user interface is fine and Product & UX is worth 10 points, but a judge should also be able to run your agent without clicking through a screen.

The simplest pattern that works:

```text
/project-root/run.py     # starts the app, or runs the agent on one input
```

If you expose an HTTP API, bind to all interfaces so it is reachable from outside a container:

```python
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
```

Avoid binding only to `127.0.0.1` inside Docker; the port mapping will not reach it.

A run endpoint that takes JSON and returns JSON makes your project easy to test:

```json
{
  "run_id": "demo-001",
  "input": {
    "query": "Reconcile supplier records across the three sources and flag conflicts."
  },
  "options": {
    "sample_mode": false
  }
}
```

And returns something a reader can inspect:

```json
{
  "run_id": "demo-001",
  "status": "success",
  "output": {
    "summary": "Generated result here",
    "recommendations": [],
    "artifacts": []
  },
  "agents": [
    { "name": "Planner", "role": "Breaks down the task and delegates work" },
    { "name": "Evaluator", "role": "Reviews outputs and requests refinement" }
  ],
  "trace_id": "trace-demo-001",
  "log_file": "logs/trace-demo-001.jsonl",
  "execution_time_seconds": 42.7
}
```

On failure, return a structured error rather than crashing silently:

```json
{
  "run_id": "demo-001",
  "status": "error",
  "error": {
    "type": "UpstreamTimeout",
    "message": "Source API did not respond after 3 retries; fell back to sample mode.",
    "recoverable": true
  },
  "trace_id": "trace-demo-001",
  "execution_time_seconds": 61.3
}
```

If your project includes a UI, run it on a separate port from the API so neither blocks the other.

---

## 3. Docker

Docker is the most reliable way to make sure your project runs the same way on a judge's machine as on yours.

Your image should:

- Build with a standard `docker build` command
- Install all dependencies at **build time**
- Start without manual shell steps
- Run on CPU only
- Take secrets as runtime environment variables, never at build time

### Reference Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/logs

EXPOSE 8000

CMD ["python", "run.py"]
```

### Running it

```bash
docker build -t oah-submission .

docker run --rm \
  -p 8000:8000 \
  --env-file .env \
  oah-submission
```

Any dependency manager is fine (`pip`, `poetry`, `uv`, `conda`) as long as nothing installs during a run. No `pip install`, `apt-get` or model download inside the request path.

---

## 4. CPU-Only

Assume a judge has an ordinary machine.

Do not require GPUs, CUDA, NVIDIA drivers, TPU runtimes or local model weights that need an accelerator. Hosted model APIs, lightweight local models, CPU-compatible vector stores and small classifiers are all fine. If your project can use a GPU, it should still run correctly without one.

---

## 5. Keep Runs Bounded

A run that takes an hour is hard to judge and hard to demo.

| Operation | Suggested timeout |
|---|---:|
| External API request | 10–30 seconds |
| Model API request | 30–90 seconds |
| One agent loop iteration | 1–3 minutes |
| A full run | Target 5–10 minutes |

Also:

- Cap agent loop iterations; unbounded debate is the most common cause of a hung run
- Do not download large datasets during a run
- Ship a `SAMPLE_MODE=true` path that works without any network access
- Return a controlled error or partial result instead of hanging

---

## 6. Secrets

All credentials come from environment variables.

Never put keys in source code, `README.md`, notebooks, config files committed to the repo, logs, or screenshots in your demo video.

Ship a `.env.example` with placeholders only:

```bash
# Model provider
OPENAI_API_KEY=your-api-key-here
OPENAI_BASE_URL=https://api.your-provider.example/v1

# Partner services
ZETARIS_API_KEY=your-key-here
NVIDIA_API_KEY=your-key-here
METERLESS_API_KEY=your-key-here

# Runtime behaviour
SAMPLE_MODE=false
LOG_LEVEL=INFO
PORT=8000
```

Read them at runtime:

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ.get("OPENAI_BASE_URL")
)
```

Add `.env` to `.gitignore`. If a real key ever reached a commit, rotate it rather than trying to scrub history.

---

## 7. Data

Keep the repository light. A judge cloning a multi-gigabyte repo is a judge who stops.

| Pattern | Use when | Requirements |
|---|---|---|
| **Static sample in repo** | Small curated data | Documented source and licence in the README |
| **Automated download script** | Larger open datasets | Fully automated, no login, no manual clicks |
| **Runtime public API** | Fresh or live data | Timeouts, retries, and a sample-mode fallback |

Avoid: large raw datasets, private or proprietary data, anything requiring manual download or approval, and real personal, clinical or financial records.

Document every source in your README: where it came from, the licence, what subset you used, and how to regenerate it.

---

## 8. Logs

Logs are how a judge verifies that your agent did what you say it did. This matters directly for the Technical and Demo scores.

Write to both **stdout** and a `logs/` directory.

### What logs should show

- Which agents ran, and what each was asked to do
- Handoffs and delegation decisions
- Critique or validation steps
- Refinement loops
- Retries, fallbacks and recovery
- The final synthesis
- Errors, with what happened next

### Recommended trace format

One JSONL file per run, `logs/trace-<run_id>.jsonl`, one JSON object per line:

```json
{
  "timestamp": "2026-10-17T18:42:11Z",
  "run_id": "demo-001",
  "agent_name": "Planner",
  "action": "delegate_task",
  "input_summary": "User asked for a reconciliation across three supplier sources.",
  "output_summary": "Created three sub-questions and assigned retrieval to Researcher.",
  "target_agent": "Researcher",
  "confidence": 0.91,
  "retry_count": 0,
  "status": "success"
}
```

### Readable stdout

```text
[INFO] run_id=demo-001 Starting run
[INFO] run_id=demo-001 Planner delegated retrieval to Researcher
[INFO] run_id=demo-001 Researcher returned 5 candidate records
[INFO] run_id=demo-001 Evaluator flagged a conflict between sources 2 and 3
[INFO] run_id=demo-001 Planner requested a second pass on source 3
[INFO] run_id=demo-001 Writer produced final reconciliation
[INFO] run_id=demo-001 Completed in 42.7 seconds
```

### Never log secrets

Mask them:

```text
OPENAI_API_KEY=sk-...redacted
```

---

## 9. Partner Technology

Sponsor Tech is worth 10 points, so document where each partner technology fits in your build rather than leaving a judge to guess.

| Layer | Partner | Setup |
|---|---|---|
| **Data** | Zetaris | [TBC: see the partner resource area on HackOS] |
| **Models** | NVIDIA | [TBC: see the partner resource area on HackOS] |
| **Cognition** | Meterless | [TBC: see the partner resource area on HackOS] |
| **Coding** | Cursor | [TBC: see the partner resource area on HackOS] |

Keep the integration behind an adapter so a service outage does not take your whole project down during judging, and so a judge without your credentials can still run sample mode.

---

## 10. Suggested Repository Structure

```text
/project-root
│── app/                 # Core agent logic
│── data/                # Small static data or download scripts
│── scripts/             # Helper scripts
│── run.py               # Entry point
│── requirements.txt     # Dependencies
│── Dockerfile           # Reproducible build
│── input_examples/      # At least 3 sample inputs
│── output_examples/     # Matching outputs
│── logs/                # Agent traces
│── .env.example         # No real keys
│── README.md            # Setup, usage, architecture, limitations
```

---

## 11. Test It Like a Judge Would

Before you submit, do this on a clean machine or a fresh clone:

```bash
git clone <your-repo-url>
cd <your-repo>

cp .env.example .env     # fill in your keys

docker build -t oah-submission .
docker run --rm -p 8000:8000 --env-file .env oah-submission
```

Then call it:

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d @input_examples/example_1.json
```

And read the logs:

```bash
docker logs <container_id>
cat logs/trace-*.jsonl
```

If any step needs a fix you make by hand, your README is incomplete.

---

## 12. Common Failures

| Failure | What it looks like | Fix |
|---|---|---|
| **UI only** | A dashboard runs, but nothing can be called programmatically | Add an entry point that takes input and returns output |
| **Runtime installs** | `os.system("pip install ...")` inside a request | Install at build time |
| **Hardcoded secrets** | A real key in the source | Environment variables and `.env.example` |
| **No trace** | Logs say "Final answer generated." | Log each agent, handoff, critique and retry |
| **Unbounded run** | Downloads 4GB during a run and hangs | Small samples, timeouts, sample mode |
| **Localhost binding** | API unreachable from outside the container | Bind to `0.0.0.0` |
| **Works on my machine** | Undocumented setup steps | Test from a fresh clone |
| **Silent crash** | Process dies with no output | Return a structured error |

---

## 13. Readiness Checklist

### Running

- [ ] A documented command starts the project from a clean clone
- [ ] There is a programmatic entry point, not only a UI
- [ ] Input and output are structured and machine-readable
- [ ] Nothing requires interactive input

### Build

- [ ] Docker build succeeds, or setup is fully documented
- [ ] Dependencies install at build time
- [ ] Runs on CPU only
- [ ] No runtime installs or model downloads

### Secrets

- [ ] No keys in code, logs, examples or the demo video
- [ ] `.env.example` present with placeholders
- [ ] `.env` is gitignored

### Data

- [ ] Repository is small
- [ ] Sources and licences documented
- [ ] No manual data setup
- [ ] Sample mode works with no network

### Runtime

- [ ] A run finishes in minutes
- [ ] External calls have timeouts
- [ ] Agent loops are bounded
- [ ] Failures return a controlled response

### Logs

- [ ] Written to stdout and `logs/`
- [ ] Show agent handoffs, critique, retries and recovery
- [ ] Contain no secrets

### Evidence

- [ ] At least three sample inputs and outputs
- [ ] README covers setup, architecture and limitations
- [ ] Partner technology use documented
- [ ] Demo recorded and accessible

---

## 14. The Standard in One Line Each

**Runnable** — starts cleanly from a documented command.
**Reachable** — can be driven programmatically, not only through a screen.
**Reproducible** — no manual setup, no hidden dependencies.
**CPU-compatible** — no GPU requirement.
**Bounded** — finishes in minutes, with timeouts and caps.
**Secure** — secrets only through environment variables.
**Data-conscious** — light repository, documented sources.
**Observable** — logs to stdout and `logs/`.
**Agentic** — the traces show the agent doing real work.
