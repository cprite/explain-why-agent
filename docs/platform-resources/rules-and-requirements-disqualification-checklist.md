# Disqualification Checklist

Folder: Rules and Requirements · updated 2026-09-30

# Pre-Submission Self-Check

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**

Run this before you submit. It won't tell you whether you'll win, but it catches the things that make a good project unscoreable.

> **Submissions close:** **20 October 2026, 23:45 UTC.** Hard deadline.
> **The principle:** a judge who has never seen your project should be able to run it, watch it work, and see how it got there.

> **The binding disqualification conditions are in the Official Rules on the event page.** This document is preparation guidance, not the rule list. Where the two differ, the Official Rules apply.

---

## 1. The Two Confirmed Disqualifiers

Only two conditions are confirmed from the published rules:

| Condition | Rule |
|---|---|
| **Late submission** | Submissions close 20 October, 23:45 UTC. This is hard. |
| **Duplicate accounts** | One account per participant. Duplicates disqualify the whole team. |

[TBC: the full disqualification conditions are in the Official Rules. Check them before relying on this document.]

---

## 2. The Things That Actually Cost You

These aren't published disqualifiers, but each one takes points off a project that deserved them. In rough order of damage:

| Problem | What it costs |
|---|---|
| A judge can't run it | Technical and Demo both collapse; you're judged on your video alone |
| No traces or logs | No evidence the agent did the work; Technical suffers |
| Hardcoded outputs | Reads as a mockup, and raises an integrity question |
| Secrets committed | Bad practice, a real security risk to you, and it looks careless |
| Partner tech mentioned but not used | Sponsor Tech scores near zero, and judges check |
| README overclaims | Costs credibility across every criterion |
| Only works on your laptop | Same as "can't run it" |
| Submitted at 23:44 | No margin when something goes wrong, and something will |

---

## 3. Repository Check

There's no mandated structure. This one is easy for a judge to navigate:

```text
/project-root
│── app/                # Core agent logic
│── data/               # Small samples or download scripts
│── scripts/            # Helper scripts
│── run.py              # Entry point
│── requirements.txt    # Dependencies
│── Dockerfile          # Strongly recommended
│── input_examples/     # At least 3 sample inputs
│── output_examples/    # At least 3 matching outputs
│── logs/               # Agent traces
│── .env.example        # Placeholders only
│── README.md           # Setup, run, architecture, limitations
```

- [ ] Repository is accessible to judges by the deadline
- [ ] An entry point exists and is documented
- [ ] `.env.example` exists, placeholders only
- [ ] README covers setup, run commands, agent roles, examples and limitations
- [ ] Sample inputs and matching outputs are included
- [ ] `logs/` exists or is created at runtime
- [ ] The repository is light; no large datasets committed
- [ ] Nothing required is buried in a nested folder

---

## 4. Can a Judge Run It?

The single most damaging failure. Test it the way they will.

### Self-test

```bash
# From a fresh clone, not your working copy
git clone <your-repo-url> final-check
cd final-check

cp .env.example .env     # fill in your keys

docker build -t oah-submission .
docker run --rm -p 8000:8000 --env-file .env oah-submission
```

Or without Docker, from a clean environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Pass criteria

- [ ] Build or install completes with no errors
- [ ] Nothing installs after the app starts
- [ ] It starts with no manual edits
- [ ] No GPU required
- [ ] A run finishes in minutes, not hours
- [ ] It runs from a fresh clone, on a machine that isn't yours

### What fails

- The build breaks on missing system packages
- Dependencies fail to install
- It downloads a large model or dataset at runtime
- Files have to be copied in by hand
- A judge has to run notebook cells first
- It only works on the author's laptop

---

## 5. Can a Judge Drive It?

A UI is welcome, and Product & UX is worth 10 points. But a judge should be able to run your agent without clicking through screens.

### Self-test

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d @input_examples/example_1.json
```

### Pass criteria

- [ ] There's a programmatic way in, not just a UI
- [ ] It takes structured input and returns structured output
- [ ] It needs no interactive input
- [ ] The UI, if present, doesn't block the programmatic path
- [ ] Failures return a useful message, not a stack trace or a hang

[TBC: whether a specific interface, port or endpoint is required. See section 6 of the Official Rules.]

---

## 6. No Hidden Manual Steps

**Allowed:** setting environment variables, running documented install or build commands, running the documented entry point, automated data downloads, a `SAMPLE_MODE=true` fallback.

**Not:** downloading files by hand from a browser, editing source code, creating folders the app should create, pasting keys into files, running notebooks to prepare data, manual database setup.

- [ ] The README has every command needed
- [ ] Data setup is automated
- [ ] No credentials are needed beyond environment variables
- [ ] It runs from a clean checkout
- [ ] External failures are handled with timeouts, retries or sample mode

The test: give the README to someone on your team who hasn't touched the repo and watch them follow it without asking you anything.

---

## 7. Sample Mode

More important here than at events with a mandated provider, because **judges may not have credentials for whichever model provider you chose.**

- [ ] `SAMPLE_MODE=true` runs the whole thing with no live credentials
- [ ] It's documented in the README
- [ ] It still runs real agent logic on cached data, rather than replaying a saved output
- [ ] You've tested it from a fresh clone with an empty `.env`

That last test is the one nobody does, and it's the one that decides whether a judge without your keys sees a working agent or an error.

---

## 8. No Hardcoded Outputs

Your system must do real work on the input it's given.

### Self-test

Run it on all three of your examples and confirm the outputs differ meaningfully and trace back to their inputs.

### Pass criteria

- [ ] Output changes appropriately across different inputs
- [ ] Output isn't read from `output_examples/`
- [ ] Agent decisions are visible in the logs
- [ ] There's no demo-only branch
- [ ] No code maps a known input to a prewritten output
- [ ] Sample mode still runs real logic

### What fails

- `if input == "example_1": return saved_output_1`
- Every input returns the same response
- Logs are static text unrelated to the run
- A model client exists but is never called
- The README says the demo uses mocked outputs

Judges test with their own inputs. A project that only works on the three you shipped is a project that doesn't work.

---

## 9. Traces

This is how a judge verifies your agent did the work rather than took one long prompt. It feeds the Technical score directly.

### What the logs should show

- At least two named agents doing distinct things
- Handoffs between them
- Critique, validation, retry, escalation or branching
- Status of each step
- Logs tied to the input actually being processed

### Weak

```text
Agent A -> Agent B -> Agent C -> final answer
```

### Strong

```text
PlannerAgent -> ResearchAgent: requests evidence
ResearchAgent -> PlannerAgent: returns findings with uncertainty
PlannerAgent -> EvaluatorAgent: asks for critique
EvaluatorAgent -> PlannerAgent: flags a missing source
PlannerAgent -> ResearchAgent: requests a retry with a narrower query
ResearchAgent -> EvaluatorAgent: provides revised evidence
EvaluatorAgent -> WriterAgent: approves synthesis
WriterAgent -> final response
```

### Format

Print to stdout and save to `logs/`. JSONL works well:

```json
{"timestamp":"2026-10-18T20:14:03Z","agent_name":"PlannerAgent","action":"delegate","input_summary":"User requested a supplier reconciliation","output_summary":"Delegated source retrieval to ReconcilerAgent","target_agent":"ReconcilerAgent","confidence":0.86,"retry_count":0,"status":"success"}
{"timestamp":"2026-10-18T20:14:19Z","agent_name":"ConflictCritic","action":"critique","input_summary":"Merged record set","output_summary":"Rejected the resolution for Supplier C as unsupported","target_agent":"ReconcilerAgent","confidence":0.79,"retry_count":0,"status":"needs_revision"}
```

### Pass criteria

- [ ] Logs are generated during the run
- [ ] Written to stdout and `logs/`
- [ ] At least two named agents appear
- [ ] Agent-to-agent interaction is visible
- [ ] It's more than a single pass
- [ ] At least one feedback, critique, retry or branch event appears
- [ ] The logs match the input being processed

**Never hand-write a trace.** A trace that doesn't match the code is an integrity problem, not a shortcut.

---

## 10. Partner Technology

Sponsor Tech is worth **10 points**. It's the easiest ten points to lose by omission and the easiest to lose by faking.

- [ ] You've documented which of Zetaris, NVIDIA, Cursor and Meterless you used
- [ ] You've documented where each one sits in the build
- [ ] Each is load-bearing, not decorative
- [ ] Each call has a timeout and a fallback, so an outage during judging degrades rather than kills
- [ ] Partner credentials come from environment variables

A partner named in the README but absent from the code scores worse than not mentioning it, because it reads as padding.

---

## 11. Secrets

### Never commit

API keys of any kind, cloud credentials, database passwords, SSH private keys, OAuth tokens, personal access tokens, dataset credentials, or a real `.env`.

### Required

```bash
# .env.example — placeholders only
OPENAI_API_KEY=your-api-key-here
OPENAI_BASE_URL=https://api.your-provider.example/v1
MODEL_NAME=your-model
SAMPLE_MODE=false
```

```gitignore
.env
.env.*
!.env.example
*.pem
*.key
secrets/
credentials/
```

### Self-test

```bash
grep -RIn --exclude-dir=.git \
  -E "(sk-|api[_-]?key|secret|token|password|BEGIN RSA PRIVATE KEY|BEGIN OPENSSH PRIVATE KEY)" .

git ls-files | grep -E "(\.env$|\.pem$|\.key$|credentials|secrets)"
```

### If you find one

**Rotate the key with your provider first.** Not after cleaning the repo. First. Removing it from the latest commit doesn't remove it from history, and a key that was ever public should be treated as compromised.

### Pass criteria

- [ ] No real keys in source, notebooks, README, screenshots or logs
- [ ] No real `.env` committed
- [ ] `.env.example` has placeholders only
- [ ] Git history exposes no active secrets
- [ ] Your demo video shows no keys on screen

That last one catches people. Check your video frame by frame around any terminal.

---

## 12. Demo Video

Demo is worth **15 points**.

- [ ] 2 to 3 minutes
- [ ] Shows the system actually running
- [ ] Shows the agents and how they interact
- [ ] Shows the final output and why it's useful
- [ ] The link works for someone who isn't logged in as you
- [ ] No credentials visible anywhere

Test the link in a private browser window. A dead or permission-locked link costs you the whole 15 points.

---

## 13. Honesty Check

Read your README as if you were a judge who will check every claim, because they are.

- [ ] Every capability claimed is one the code has
- [ ] Data sources are described accurately, including whether they're live or cached
- [ ] The agent description matches what the traces show
- [ ] Limitations are stated honestly
- [ ] Nothing is described as production-ready that isn't

An accurate limitations section reads as confidence. An overclaim that a judge catches costs more than the gap it was hiding.

---

## 14. Full Validation Flow

Run this in one sitting before submitting.

```bash
# 1. Fresh clone, not your working copy
git clone <your-repo-url> final-check
cd final-check

# 2. Required files present?
ls run.py README.md .env.example input_examples/ output_examples/

# 3. Build
docker build -t oah-submission .

# 4. Run with your credentials
cp .env.example .env    # fill in
docker run --rm -p 8000:8000 --env-file .env oah-submission

# 5. Call it, in another terminal
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d @input_examples/example_1.json

# 6. And the other two
curl -X POST http://localhost:8000/run -H "Content-Type: application/json" -d @input_examples/example_2.json
curl -X POST http://localhost:8000/run -H "Content-Type: application/json" -d @input_examples/example_3.json

# 7. Check the traces
ls logs/
cat logs/* | head -50

# 8. Scan for secrets
grep -RIn --exclude-dir=.git -E "(sk-|api[_-]?key|secret|token|password)" .

# 9. THE ONE PEOPLE SKIP: no credentials at all
rm .env
docker run --rm -p 8000:8000 -e SAMPLE_MODE=true oah-submission
curl -X POST http://localhost:8000/run -H "Content-Type: application/json" -d @input_examples/example_1.json
```

Step 9 is how a judge without your keys will experience your project. If it fails there, fix it before you submit.

---

## 15. Submit / Don't Submit

Submit only when all of these are true:

- [ ] It builds and runs from a clean clone
- [ ] A judge can drive it without your UI
- [ ] No hidden manual setup
- [ ] Outputs are generated, not stored
- [ ] Traces show real agent interaction
- [ ] Sample mode works with no credentials
- [ ] No secrets anywhere, including the video
- [ ] Partner technology use is documented and real
- [ ] The README is accurate and honest
- [ ] Demo video is 2–3 minutes and the link works
- [ ] Examples and traces match your track
- [ ] You're submitting with hours to spare, not minutes

---

## 16. If Something Fails

1. **Fix it now**, not after one more feature
2. Re-run the full validation flow from a clean clone
3. Update the README if the commands changed
4. Regenerate the logs with the fixed version
5. Confirm no secrets got introduced in the fix
6. Submit

**If you're blocked:** mentor office hours for build problems, your track room for scope questions, the partner resource area for partner issues, your provider's support for auth and rate limits, and the Official Rules for what's required.

**Don't leave this to 20 October.** Run the full flow on day four, when you still have two days to fix what it finds. Almost everything on this list is preventable with 48 hours' notice and unfixable with two.
