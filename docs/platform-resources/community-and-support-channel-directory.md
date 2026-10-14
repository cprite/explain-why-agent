# Channel Directory

Folder: Community and Support · updated 2026-10-13

# Where to Get Help

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**

This guide explains where to post questions, blockers and urgent issues during the hackathon.

Everything during the event happens on **HackOS**. Discord is the community space for after the hackathon.

Read this before posting. Posting in the right place gets you a faster answer and keeps the space useful for everyone.

---

## 1. Quick Routing

| If you need help with… | Go to |
|---|---|
| Track scope, what counts, whether your approach fits the track | **Challenge pages**, then **#help desk** |
| Zetaris, Meterless, Cursor or NVIDIA: setup, access, errors | **The sponsor's folder in Resources**, then **that sponsor's Help channel** |
| Agent design, frameworks, Docker, Python, orchestration bugs, logs and traces | **#help desk** or **mentor office hours** |
| Submission requirements, what to include, deadlines | **Submission Requirements** and **Official Rules** on HackOS, then **#help desk** |
| Finding teammates, forming a team | **Team-finding** |
| Platform access, schedule, admin | **Announcements**, or message a moderator |
| Rules questions or private issues | **hackathons@genai.works** |
| A non-sponsor model provider: auth, rate limits, billing, model names | **That provider's own support** |

That last row catches people out. If you use a model provider outside the sponsors, a `401` from it is between you and that provider. Mentors can help if a minimal call works but your framework doesn't.

---

## 2. What HackOS Has

1. **Announcements:** official updates, read-only
2. **Challenge pages:** one per track, with the statement and requirements
3. **#help desk:** general technical and track questions
4. **Sponsor Help channels:** Help Zetaris, Help Meterless, Help Cursor, Help NVIDIA
5. **Sponsor folders in Resources:** setup guides, documentation and workshop recordings
6. **Mentor office hours:** scheduled sessions
7. **Team-finding:** forming and joining teams

The tracks are:

| Track | |
|---|---|
| Solving Fragmented Intelligence | Main track |
| The Agent That Can Explain Why | Main track |
| Reasoning Architecture | Main track |
| Wildcard [Tinkerer] | Bonus track: extend an existing project with Zetaris and Meterless; scored on new work only |

Please don't start parallel support threads outside these unless a moderator asks you to.

---

## 3. Posting Rules

### 3.1 Before you post

1. Check the FAQ and the Troubleshooting Guide
2. Check the sponsor's folder in Resources if it's a sponsor issue
3. Search #help desk and the sponsor Help channel; someone has probably hit it already
4. Gather the details someone would need to reproduce it

### 3.2 Never post secrets

Do **not** post API keys of any kind, `.env` files with real values, tokens, passwords, private credentials, or personal and confidential data.

Terminal screenshots leak keys more often than anything else. Check before you upload.

**If you expose a key:**

1. **Rotate it immediately.** For a Zetaris, Meterless or NVIDIA key, create a new one in that service. For any other provider, rotate it with that provider. Deleting the message doesn't un-leak it.
2. Delete or edit the post.
3. Tell a moderator.

### 3.3 Use a clear title

Prefix where it helps:

- `[Zetaris]` · `[Meterless]` · `[Cursor]` · `[NVIDIA]` · `[Docker]` · `[Submission]` · `[Track]` · `[Teams]` · `[Deadline]`

````text
[Docker] Build fails on python:3.11-slim, missing system dependency
````

### 3.4 Include enough context

| Post type | Include |
|---|---|
| **Technical** | What you were doing, what happened, the exact error, a minimal snippet (not your whole repo), your environment, whether it fails locally or in Docker, and what you already tried |
| **Track** | Your track, your intended agents and roles, your data source, and the decision you need help with |
| **Submission** | Which requirement is unclear, what you've already read, and whether it blocks you |

### 3.5 Keep threads tidy

Reply in threads. Don't cross-post the same question. If it turns out to belong elsewhere, link the original and move. When it's solved, say so:

> **Resolved: the container was binding to 127.0.0.1 instead of 0.0.0.0.**

Many questions in a 144-hour window have already been answered. Marking yours resolved saves the next person time.

---

## 4. #help desk

### Purpose

Use it for general technical questions and anything about the tracks.

- Choosing and scoping your use case
- Whether your architecture fits the track
- Dataset suitability
- Whether your scope is too broad for six days
- Build problems that aren't specific to one sponsor

### Track question format

````markdown
**Track:**
**Team size:** solo / team of X
**Problem and user:**
**Proposed agents:**
1. name — role
2. name — role
3. name — role

**Data sources:**
**How Zetaris and Meterless are used:**
**Planned output:**
**Main question:**
**What I need:** scope / architecture / data / feasibility
````

### Do and don't

**Do:** name your track, explain the decision you're trying to make, keep it focused, and share an architecture sketch if it helps.

**Don't:** ask someone to design your whole solution, ask whether your idea will win, paste a long document without a question, or bring sponsor access problems here.

### What judges look for

Judges are looking for agents that do real work.

Weak:

````text
Agent A → Agent B → Agent C
````

Strong: planner ↔ executor ↔ evaluator loops, agents critiquing each other, delegation based on context, shared memory or state, branching, retries, escalation, and traces that show all of it.

---

## 5. Sponsor Folders and Help Channels

### Purpose

Each sponsor has a folder in Resources on HackOS with setup guides, documentation and workshop recordings, and a Help channel staffed by the sponsor team.

| Sponsor | Role | Requirement |
|---|---|---|
| Zetaris | Data | Required in every submission |
| Meterless | Cognition | Required in every submission |
| Cursor | Development environment | Required development environment |
| NVIDIA | Models | Used wherever it contributes |

### Use them for

Access and credentials, setup, connection errors, service behaviour, and anything specific to that technology.

### The triage question

Before posting, ask: **does the sponsor's own quickstart work for me?**

- **Yes, but my code doesn't:** the problem is in your code. Bring it to #help desk or mentor office hours with the error.
- **No:** the problem is access or the service. Post in that sponsor's Help channel.

### Posting format

````markdown
**Sponsor:** Zetaris / Meterless / Cursor / NVIDIA
**What I was doing:**
**Environment:** local / Docker
**Does the sponsor quickstart work for me?** yes / no
**Exact error:**
**What I tried:**
**Blocking?** yes / no
````

### Remember

Sponsor Tech is worth **10 points**. Wrap every sponsor call behind an adapter with a timeout and a fallback, so a service outage during judging degrades your project instead of breaking it.

---

## 6. Mentor Office Hours

### Purpose

For build problems: agent design, framework behaviour, debugging and architecture.

- Multi-agent architecture and orchestration
- FastAPI, Flask, Docker, Python, dependencies
- LangChain, CrewAI, AutoGen, LangGraph, the OpenAI Agent SDK
- Retrieval, vector stores, tool calling
- Logging and trace design
- Runtime, timeouts, retries and fallback design
- Sample mode
- "Works locally, fails in Docker"

### Bring this

````markdown
**Issue type:** Docker / Python / API / framework / logs / architecture
**Track:**
**Framework and provider:**
**Environment:** local / Docker
**Command:**
```bash
paste here
```
**Expected:**
**Actual:**
**Error:**
```text
paste here
```
**Relevant file or snippet:**
**Already tried:**
**Blocking?** yes / partially / no
````

### Do and don't

**Do:** include the exact failing command, a minimal reproducible snippet, whether it fails in Docker or locally, and relevant log lines.

**Don't:** paste your whole repository, post keys, or ask someone to write your code.

### What mentors do

They help you understand the tracks, navigate HackOS and the sponsor technologies, and get unstuck. They will not build your project, and they can't debug your provider account. Anything they tell one team, they'd tell any team that asked.

---

## 7. Submission Questions

The **Submission Requirements** and **Official Rules** on HackOS are the authority on what to submit. Read them before asking.

If they don't cover your case, ask in #help desk and say which section you already read. For anything private, email hackathons@genai.works.

### Deadlines

| Milestone | Date (UTC) |
|---|---|
| Build window opens | 22 October, 00:00 |
| Registration closes | **22 October, 23:45** |
| **Submissions close** | **27 October, 23:45** |
| Judging opens | 28 October, immediately after submissions close |
| Results | 6 November, 16:00 |

Both deadlines are hard. Submit early and update, rather than submitting once at 23:44.

### Ask early

Don't leave these to the final hours:

- A broken Docker build
- A project that only runs on your laptop
- A missing demo video or slide deck
- A repository that is still private (it must be public)
- A README missing setup, usage or dependencies

They need hours, not minutes, and they're what costs teams their scores.

---

## 8. Team-Finding

Use it to find teammates and form teams.

| Rule | |
|---|---|
| Team size | 1 to 5 builders |
| Teams per participant | One |
| Building solo | Select "happy to build solo" in the registration form |
| Team lock | Your team locks when the first submission is created |
| Prize split | Equal shares by default; any other split must be agreed in writing before you submit |

Settle the prize split on day one, not after you win.

---

## 9. Announcements

Official updates, read-only: deadline reminders, resource releases, workshop dates, judging updates, results notices, and any change to the rules or schedule.

**Do:** read every one, treat them as authoritative, and check daily during the build window.

**Don't:** reply with questions there, or treat a screenshot reposted elsewhere as official.

Questions about an announcement go to #help desk or to a moderator.

---

## 10. Escalation

| Issue | First stop | Escalates to |
|---|---|---|
| Track scope and expectations | Challenge pages, then #help desk | Organizers, if it affects every team |
| Sponsor setup, access, service errors | Sponsor folder in Resources | That sponsor's Help channel |
| Agent design, frameworks, debugging | #help desk or mentor office hours | — |
| Non-sponsor provider auth, rate limits, billing | That provider's support | — |
| Submission requirements | Submission Requirements and Official Rules | Organizers, if genuinely ambiguous |
| Platform access, schedule, admin | A moderator | HackOS escalations |
| Rules questions | hackathons@genai.works | Organizers |
| Exposed credentials, sensitive data, safety | **Private message to a moderator** or hackathons@genai.works | Organizers, privately |
| Official rule or schedule change | Announcements | — |

**Anything sensitive goes private first.** If it involves exposed credentials, personal data, a security concern or a safety issue, ask for a private route without posting the details, and rotate anything exposed while you wait.

---

## 11. What Counts as Urgent

Use `[URGENT]` only when it's time-critical and blocks participation or submission.

**Urgent:**

- `[URGENT][Submission]` Can't submit because the form or platform is failing
- `[URGENT][Zetaris]` or `[URGENT][Meterless]` A sponsor service is down and it's blocking the final run
- `[URGENT][Access]` Registered participant can't get into HackOS

**Not urgent:**

- General architecture feedback
- Non-blocking improvements
- Requests for ideas
- Questions already answered in the FAQ or Announcements

If everyone uses `[URGENT]`, it stops working for the people who need it at 23:00 on 27 October.

---

## 12. Response Expectations

| Priority | Example | Handling |
|---|---|---|
| **Critical** | Platform access failure, submission blocked | Fastest available, escalated |
| **High** | Build failure near the deadline, sponsor outage blocking a demo | Prioritised |
| **Medium** | Architecture clarification, track scope, a framework issue with a workaround | Normal |
| **Low** | Optimisation ideas, polish, general opinions | Best effort |

This is a global event across every time zone, running for 144 hours. Moderators and mentors aren't available at all hours. Response times stretch during the final 24 hours, so raise anything structural early.

---

## 13. Good Examples

**Sponsor**

````markdown
[Zetaris] 401 Unauthorized from inside Docker, works locally

**Sponsor:** Zetaris
**What I was doing:** Querying our Zetaris instance from the ingest pipeline
**Environment:** Docker
**Does the quickstart work for me?** Yes, locally
**Error:** 401 Unauthorized
**Tried:** Confirmed the key works locally; confirmed ZETARIS_API_KEY is in .env
**Blocking?** Yes
````

**Build**

````markdown
[Docker] FastAPI runs locally but the container exits immediately

**Track:** Solving Fragmented Intelligence
**Framework:** Custom FastAPI + Meterless
**Environment:** Docker
**Command:** docker run -p 8000:8000 oah-submission
**Expected:** API on localhost:8000
**Actual:** Container exits at startup
**Error:** ModuleNotFoundError: No module named 'app.agents'
**Tried:** Checked requirements.txt and the local import path
**Blocking?** Yes
````

**Track**

````markdown
[Track] Is our reconciliation loop enough for Solving Fragmented Intelligence?

**Track:** Solving Fragmented Intelligence
**Team size:** 3
**Problem:** Supplier records disagree across three systems
**Agents:** Source Mapper, Reconciler, Conflict Critic, Reporter
**Data:** Three internal sources served through Zetaris
**Question:** The critic sends unsupported resolutions back for a re-check.
Is that enough, or should we also branch on confidence?
````

---

## 14. Checklist Before Posting

| Question | Go to |
|---|---|
| Is it about a sponsor technology? | **Sponsor folder in Resources**, then **that sponsor's Help channel** |
| Is it about a non-sponsor provider's auth, limits or billing? | **That provider's support** |
| Is it about scope, or what counts for your track? | **Challenge pages**, then **#help desk** |
| Is it about code, Docker, frameworks or architecture? | **#help desk** or **mentor office hours** |
| Is it about what to submit? | **Submission Requirements** and **Official Rules**, then **#help desk** |
| Is it about teammates? | **Team-finding** |
| Is it sensitive? | **Private message to a moderator** or **hackathons@genai.works** |
| Is it an official update? | **Read Announcements** |

---

## 15. Final Reminders

- **Post in the right place for a faster answer.**
- **Never post secrets.** If you do, rotate the key first, then tell a moderator.
- **Search first.** Someone has probably hit it already.
- **Be specific.** The exact error and what you already tried save the most time.
- **Announcements are the source of truth** for deadlines and rule changes.
- **Ask early.** Don't check your core requirements in the final hour.
- **Post your fix when you solve it.** You'll save someone else an hour.

These channels exist to unblock you. Use them actively, respectfully, and with enough detail for someone to help.
