# Help Desk Instructions

Folder: Community and Support · updated 2026-09-30

# Help Desk Guide

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**

This guide explains how to ask for help so you get unblocked fast. Read it before posting.

The principle: **a clear question gets a fast answer. "It doesn't work" gets a follow-up question and an hour lost.**

---

## 1. Where Help Lives

Everything during the event happens on HackOS.

| You need help with | Go to |
|---|---|
| Track scope, what counts, use case questions | **Your track room** |
| Partner setup, access, errors | **The partner's resource area**, then your track room |
| Agent design, framework bugs, debugging | **Mentor office hours** |
| Submission requirements | **Official Rules** on the event page |
| Finding teammates | **Team-finding** |
| Platform access, schedule, admin | **Announcements**, or a moderator |
| Your model provider's errors | **Your provider's own support** |

Discord is the community space for after the hackathon, not event support.

**One thing mentors don't do:** build your project. They can unblock you, review your direction and explain a concept. The architecture, the code and the submission stay yours.

---

## 2. Golden Rules

**Do:**

- Post in the right room
- Lead with the issue in one sentence
- Include the exact error, not a paraphrase
- Include your environment: OS, Python version, framework, local or Docker
- Share the relevant file paths and a small snippet
- Include trace logs when asking about agent behaviour
- Say what you already tried
- Redact every key, token and private URL

**Don't:**

- Post API keys, `.env` contents, passwords or tokens
- Post the same question in several rooms at once
- Direct-message organizers first unless asked to
- Paste your entire repository into a message
- Say only "it doesn't work"
- Ask someone to build it for you

---

## 3. Severity

Put a severity label at the front of your post.

| Level | Meaning | Examples |
|---|---|---|
| **P0 — Deadline risk** | You cannot submit, or many teams are affected | Platform outage, submission failing hours before the deadline |
| **P1 — Blocking my team** | You cannot proceed, but it looks team-specific | Docker build broken, agent loop crashing, partner service unreachable |
| **P2 — Need guidance** | You can keep working but need advice | Trace design, scope, which partner layer fits |
| **P3 — Clarification** | Non-blocking question | Demo length, README wording, a deadline detail |

Example title:

```text
P1 — Postgres connection refused from inside Docker, works locally
```

---

## 4. What Every Request Needs

### Context

```text
Team name:
Track:
Framework and provider:
Local or Docker:
OS:
Python version:
When it started:
Blocking submission? Yes/No
```

### What you expected

> Expected: the run endpoint accepts `input_examples/example_1.json` and returns JSON in under two minutes.

### What actually happened

> Actual: the server starts, but the run returns a 500 after the Planner hands off to the Evaluator.

### The exact error

Paste it in full, secrets removed. A paraphrased error is usually the wrong error.

### What you already tried

```text
1. Confirmed the base URL in .env
2. Regenerated .env from .env.example
3. Ran the provider connection test — works
4. Confirmed no hardcoded endpoint remains in app/agents.py
```

That last section is what separates a five-minute answer from a fifty-minute one.

---

## 5. Never Share Secrets

Before you post a log, screenshot or snippet, strip:

- API keys and tokens of any kind
- `.env` contents
- Git tokens and cloud credentials
- Dataset URLs with credentials embedded
- Personal or confidential data

Use placeholders:

```text
OPENAI_API_KEY=[REDACTED]
Authorization: Bearer [REDACTED]
```

**If you expose a key:**

1. **Rotate it immediately** with your provider. This is the step that matters.
2. Delete or edit the post.
3. Tell a moderator, so they can confirm it's gone from any cached view.

Deleting the message does not un-leak the key.

---

## 6. By Issue Type

### 6.1 Provider errors (401, 403, 429, model not found)

These are between you and your provider. Check first:

- Does your connection test script work outside the agent framework?
- Does the environment variable reach the process, in Docker as well as locally?
- Is the model name current for that provider?
- Is billing active and is the account entitled to that model?

If a minimal script works but your framework doesn't, it's a framework configuration problem, and that one belongs at mentor office hours. If the minimal script fails too, it's a provider problem, and your provider's support is faster than we are.

**Include:**

```text
Provider and model:
Framework:
Does a minimal SDK call work? Yes/No
Does it fail locally, in Docker, or both?
Exact error (no keys):
```

### 6.2 Partner stack

Check the partner's resource area on HackOS first: getting started, docs, troubleshooting and FAQs. Then post in your track room.

**Include:**

```text
Partner: Zetaris / NVIDIA / Cursor / Meterless
What you were doing:
Exact error:
Local or Docker:
Does the partner's own quickstart work for you? Yes/No
```

That last question separates "my code is wrong" from "my access is wrong", which are handled by different people.

### 6.3 Agent design and collaboration

Track rooms for "does this count", mentor office hours for "why doesn't this work".

**Include:**

```text
Track:
Problem you are solving:
Agents and roles:
Current flow:
Where critique, retry or escalation happens:
Your question:
```

**Good example:**

```text
P2 — Is our agent pattern strong enough for Fragmented?

Team: SupplyLens
Track: Fragmented

Agents:
1. Source Mapper — decides which of 3 sources can answer which part
2. Reconciler — merges records and resolves conflicts
3. Conflict Critic — challenges resolutions with weak support
4. Reporter — produces the sourced summary

Flow:
Source Mapper plans retrieval. Reconciler merges. Conflict Critic
rejects unsupported resolutions and sends them back. Reconciler
re-queries the disputed source. Unresolved conflicts are reported
as unresolved rather than guessed.

Question:
Is the critic loop enough, or do judges expect branching on
confidence as well?
```

### 6.4 Trace log issues

**Include:** the trace file path, 10 to 30 relevant lines, what looks wrong, and what pattern you were aiming for. Never paste thousands of lines.

```text
Trace file: logs/agent_trace.jsonl

Problem: our traces look linear even though we have retries.

Relevant lines:
[10-20 JSONL lines]

Question: are we logging the feedback loop wrong, or is the
architecture actually too linear?
```

### 6.5 Docker, Python, dependencies

**Include:**

```text
Local or Docker:
OS and Python version:
Dependency manager:
The exact command you ran:
The full build or run error:
Relevant files: Dockerfile, requirements.txt, run.py
```

Share the last 100 to 200 lines of `docker logs`, not the whole thing.

### 6.6 Submission questions

The Official Rules are the authority. If the rules genuinely don't cover your case, ask in your track room and quote the section you already read.

---

## 7. Screenshots

**Useful for:** platform access problems, browser console errors, upload failures, visual UI bugs.

**Not enough for:** API errors, Docker failures, Python stack traces, trace validation, dependency conflicts. Those need text.

Before uploading, check the screenshot doesn't show a key, a `.env` file, a token or personal data. Terminal screenshots leak keys more often than anything else.

---

## 8. Sharing Code

Share the smallest useful piece.

**Good:**

```text
File: app/agents/planner.py
Lines: 35-82
Branch: debug/planner-retry
```

**Not good:** the entire repository pasted into a message.

| Issue | Share |
|---|---|
| Provider not connecting | Client initialisation, env loading |
| Agent loop failing | Orchestration function, the relevant agent |
| Docker build failing | Dockerfile, requirements.txt, build log |
| Endpoint failing | run.py, the route, the request and response |
| Traces missing | Logging function, 10-30 trace lines |
| Structure question | The directory tree |

```bash
find . -maxdepth 3 -type f -not -path "./.git/*" -not -path "./.venv/*" | sort
```

---

## 9. Templates

### 9.1 Technical issue

```text
[Severity] — [Short title]

Team:
Track:
Framework and provider:
Local or Docker:
OS / Python:
Relevant files:

Expected:

Actual:

Exact error:

Steps to reproduce:
1.
2.

Already tried:
1.
2.

Question:
```

### 9.2 Partner stack

```text
[Severity] — [Partner] — [Short title]

Team:
Track:
What I was doing:
Local or Docker:

Does the partner quickstart work for me? Yes/No

Exact error:

Already tried:

Question:
```

### 9.3 Agent design

```text
[Severity] — [Short title]

Team:
Track:
Problem:
Agents and roles:
Current flow:
Where critique / retry / escalation happens:

Question:
```

### 9.4 Admin

```text
[Severity] — [Short title]

Name:
Team:
Category: team formation / access / schedule / other

Question:

Deadline impacted? Yes/No
```

---

## 10. Good Versus Weak

### Good

```text
P1 — Agent loop hangs after the evaluator requests a retry

Team: ResearchMesh
Track: Autonomous Intelligence
Framework: LangGraph + [provider] SDK
Local and Docker: both
OS: Ubuntu 22.04, Python 3.11
Files: app/graph.py, app/agents/evaluator.py, logs/agent_trace.jsonl

Expected:
Planner → Retriever → Summarizer → Evaluator completes and returns
a report.

Actual:
When evaluator confidence is under 0.7 it requests a retry from the
Summarizer, and the graph then loops until the request times out.

Log excerpt:
[10-20 lines]

Trace excerpt:
[relevant JSONL lines]

Already tried:
1. Set max retries to 2
2. Added a timeout on each model call
3. Reduced retrieved documents from 10 to 3
4. Confirmed a minimal provider call works

Question:
Is our LangGraph edge condition wrong, or is the retry state not
being updated?
```

Right room, clear severity, expected versus actual, evidence, what was already tried, and a specific question.

### Weak

```text
My agents are broken. Can someone help?
```

No context, no error, no logs, no question anyone can answer.

---

## 11. For Mentors

### First response

1. Confirm the severity and whether it blocks submission
2. Check the post is in the right room
3. Ask for the missing information rather than guessing
4. Don't diagnose from a screenshot alone; ask for text
5. Suggest the smallest next diagnostic step
6. When it's fixed, ask the participant to post the fix for others

Example:

```text
This looks like a framework configuration issue rather than an
auth one. Could you share:
1. Whether a minimal SDK call works outside the framework
2. The exact model name you're passing
3. Your client initialisation, keys removed

Don't paste your key. With those three we can narrow it down.
```

### Triage

```text
Provider auth, limits or model names?
→ Confirm whether a minimal call works. If it fails, it's the
  provider's support, not ours.

Partner technology?
→ Partner resource area first, then the track room.

Track scope, "does this count"?
→ Track room.

Code, Docker, framework, orchestration?
→ Mentor office hours.

Submission requirements?
→ Official Rules.

Exposed credentials, sensitive data or a safety concern?
→ Take it private immediately. Do not continue the public thread.
```

### Fairness

Everything you tell one team, you should be willing to tell every team. If a question would take you an hour of writing their code, that's the line, and the answer is a pointer rather than a patch.

### Escalation

| Escalate to | When |
|---|---|
| **Organizers** | Platform outage, access problems, schedule, conduct, anything affecting many teams |
| **Partner support** | Partner service down, credentials not provisioning, platform-level errors |
| **The participant's own provider** | Model auth, rate limits, billing |
| **Organizers, privately** | Exposed credentials, sensitive data, security or safety concerns |

```text
Escalation summary

Severity:
Team and track:
Issue:
Impact on submission:
Evidence: [error / logs / paths]
Already tried:
Recommended owner:
Sensitive information involved? Yes/No
```

---

## 12. Submission Day

Before you ask for help on 20 October, check:

- [ ] The project runs from a clean clone
- [ ] A judge can drive it without your UI
- [ ] `.env.example` exists, no real keys
- [ ] Sample inputs and outputs are in the repository
- [ ] Traces show agent interaction, not a straight line
- [ ] Sample mode works with no credentials
- [ ] Demo video is recorded and the link works
- [ ] README covers setup and running
- [ ] Nothing secret is committed

**Don't leave these to the last hours:** a broken Docker build, a project that only runs on your laptop, a missing demo link, or repository access problems. They are the things that cost teams their scores, and they need hours, not minutes.

### If it's genuinely a deadline risk

```text
P0 — Deadline risk — [issue]

Blocking submission: Yes
First observed:
Last successful run:
What changed:
Current blocker:
Evidence: [attached]
```

Submissions close at **20 October, 23:45 UTC**, and it's a hard deadline. Submit early and update, rather than submitting once at 23:44.

---

## 13. Private Escalation

Do **not** continue in a public room if the issue involves an exposed credential, sensitive or personal data, a security vulnerability, suspicious platform behaviour or a safety concern.

Post a minimal message asking for private contact, with no details:

```text
P0 — Private escalation needed

Team: [name]
We may have exposed a credential. Public reference removed.
Need guidance on next steps — please advise a private route.
```

Then rotate the credential immediately while you wait.

---

## 14. Before You Post

- [ ] Right room
- [ ] Severity label
- [ ] Team and track
- [ ] Expected versus actual
- [ ] Exact error text
- [ ] Relevant logs or trace lines
- [ ] File paths or a small snippet
- [ ] What I already tried
- [ ] Secrets removed
- [ ] A specific question at the end

---

## 15. The Five Questions

A good request lets someone answer these immediately:

1. What are you building?
2. What's broken?
3. Where's the evidence?
4. What have you tried?
5. What do you need from us?

Answer those five and you'll be back to building in minutes.

Use the help desk to remove blockers. Keep ownership of the architecture, the code and the submission.
