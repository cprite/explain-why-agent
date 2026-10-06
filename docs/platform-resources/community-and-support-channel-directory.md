# Channel Directory

Folder: Community and Support · updated 2026-09-30

# Where to Get Help

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**

This directory explains where to post questions, blockers and urgent issues during the hackathon.

Everything during the event happens on **HackOS**. Discord is the community space for after the hackathon.

Read this before posting. The right room gets you a faster answer and keeps the space useful for everyone.

---

## 1. Quick Routing

| If you need help with… | Go to |
|---|---|
| Track scope, what counts, use case feasibility, whether your approach fits the track | **Your track room** |
| Zetaris, NVIDIA, Cursor or Meterless: setup, access, errors | **The partner's resource area**, then your track room |
| Agent design, frameworks, Docker, Python, orchestration bugs, logs and traces | **Mentor office hours** |
| Submission requirements, what to include, deadlines | **Official Rules** on the event page, then your track room |
| Finding teammates, forming a team | **Team-finding** |
| Platform access, schedule, admin | **Announcements**, or message a moderator |
| Your model provider: auth, rate limits, billing, model names | **Your provider's own support** |

That last row catches people out. Model choice is open at this hackathon, so a `401` from your provider is between you and them. Mentors can help if a minimal call works but your framework doesn't.

---

## 2. What HackOS Has

1. **Announcements** — official updates, read-only
2. **Track rooms** — one per track: Fragmented, Autonomous Intelligence, Persistent Memory Agents, Real-World Industry Agents
3. **Partner resource areas** — Zetaris, NVIDIA, Cursor, Meterless
4. **Mentor office hours** — scheduled sessions
5. **Team-finding** — forming and joining teams

Please don't start parallel support threads outside these unless a moderator asks you to.

---

## 3. Posting Rules

### 3.1 Before you post

1. Check the FAQ and the troubleshooting guide
2. Check the relevant partner resource area if it's a partner issue
3. Search your track room; someone has probably hit it already
4. Gather the details someone would need to reproduce it

### 3.2 Never post secrets

Do **not** post API keys of any kind, `.env` files with real values, tokens, passwords, private credentials, or personal and confidential data.

Terminal screenshots leak keys more often than anything else. Check before you upload.

**If you expose a key:**

1. **Rotate it with your provider immediately.** This is the step that matters; deleting the message doesn't un-leak it.
2. Delete or edit the post.
3. Tell a moderator.

### 3.3 Use a clear title

Prefix where it helps:

- `[Partner]` · `[Docker]` · `[Submission]` · `[Track]` · `[Teams]` · `[Deadline]`

````text
[Docker] Build fails on python:3.11-slim, missing system dependency
````

### 3.4 Include enough context

**Technical posts:** what you were doing, what happened, the exact error, a minimal snippet (not your whole repo), your environment, whether it fails locally or in Docker, and what you already tried.

**Track posts:** your track, your intended agents and roles, your data source, and the decision you actually need help with.

**Submission posts:** which requirement is unclear, what you've read already, and whether it blocks you.

### 3.5 Keep threads tidy

Reply in threads. Don't cross-post the same question. If it turns out to belong elsewhere, link the original and move. When it's solved, say so:

> **Resolved — the container was binding to 127.0.0.1 instead of 0.0.0.0.**

That last habit is worth more than it sounds. Half the questions in a 144-hour window are ones someone already answered.

---

## 4. Track Rooms

### Purpose

One room per track. Use yours for anything about the track itself and for general build discussion with people solving the same shape of problem.

Use it for:

- Choosing and scoping your use case
- Whether your architecture fits the track
- Dataset suitability
- What judges are looking for in this track
- Whether your scope is too broad for six days
- General build discussion with your track's community

### Posting format

````markdown
**Track:**
**Team size:** individual / team of X
**Problem and user:**
**Proposed agents:**
1. name — role
2. name — role
3. name — role

**Data sources:**
**Planned output:**
**Main question:**
**What I need:** scope / architecture / data / feasibility
````

### Do and don't

**Do:** name your track, explain the decision you're trying to make, keep it focused, share an architecture sketch if it helps.

**Don't:** ask someone to design your whole solution, ask whether your idea will win, paste a long document without a question, or bring provider auth errors here.

### A reminder on what scores

Judges are looking for agents that do real work.

Weak:

````text
Agent A → Agent B → Agent C
````

Strong: planner ↔ executor ↔ evaluator loops, agents critiquing each other, delegation based on context, shared memory or state, branching, retries, escalation, and traces that show all of it.

---

## 5. Partner Resource Areas

### Purpose

Each partner has its own area on HackOS with getting started, documentation, a tutorial, the workshop recording, troubleshooting, FAQs and technical support.

| Layer | Partner |
|---|---|
| Data | Zetaris |
| Models | NVIDIA |
| Cognition | Meterless |
| Coding | Cursor |

### Use them for

Access and credentials, setup, connection errors, service behaviour, and anything specific to that technology.

### The triage question

Before posting, ask: **does the partner's own quickstart work for me?**

- **Yes, but my code doesn't** → your code. Bring it to your track room or mentor office hours with the error.
- **No** → access or the service. Post in the partner's resource area.

That one question routes most partner issues correctly and saves a round trip.

### Posting format

````markdown
**Partner:** Zetaris / NVIDIA / Cursor / Meterless
**What I was doing:**
**Environment:** local / Docker
**Does the partner quickstart work for me?** yes / no
**Exact error:**
**What I tried:**
**Blocking?** yes / no
````

### Remember

Sponsor Tech is worth **10 points**. Wrap every partner call behind an adapter with a timeout and a fallback, so a service outage during judging degrades your project instead of killing it.

---

## 6. Mentor Office Hours

### Purpose

For build problems: agent design, framework behaviour, debugging, architecture.

Use it for:

- Multi-agent architecture and orchestration
- FastAPI, Flask, Docker, Python, dependencies
- LangChain, CrewAI, AutoGen, LangGraph, the OpenAI Agent SDK
- Retrieval, vector stores, tool calling
- Logging and trace design
- Runtime, timeouts, retries and fallback design
- Sample mode
- "Works locally, fails in Docker"

### Posting format

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

They help you understand the tracks, navigate the tools and get unstuck. They will not build your project, and they can't debug your provider account for you. Anything they tell one team, they'd tell any team that asked.

---

## 7. Submission Questions

The **Official Rules** on the event page are the authority on what to submit. Read section 6 before asking.

If the rules genuinely don't cover your case, ask in your track room and quote the section you already read.

### Deadlines

| Milestone | Date (UTC) |
|---|---|
| Registration closes | **13 October, 00:00** |
| Build window opens | 15 October, 00:00 |
| Judging opens | 20 October, 00:00 |
| **Submissions close** | **20 October, 23:45** |
| Results | 30 October, 16:00 |

Both deadlines are hard. Submit early and update, rather than submitting once at 23:44.

### Ask early

Don't leave these to the final hours: a broken Docker build, a project that only runs on your laptop, a missing demo link, or repository access problems. They need hours, not minutes, and they're what costs teams their scores.

---

## 8. Team-Finding

Use it to find teammates and form teams. Teams are 1 to 5 builders, and you can only be on one.

Form or join your team **before the build window opens**.

One thing to settle on day one: **how a prize would be split.** The default is equal shares among team members. If your team wants something else, agree it in writing before you submit, not after you win.

---

## 9. Announcements

Official updates, read-only: deadline reminders, resource releases, workshop dates, judging updates, results notices, and any change to the rules or schedule.

**Do:** read every one, treat them as authoritative, check daily during the build window.

**Don't:** reply with questions there, or treat a screenshot reposted elsewhere as official.

Questions about an announcement go to your track room or to a moderator.

---

## 10. Escalation

| Issue | First stop | Escalates to |
|---|---|---|
| Track scope and expectations | Your track room | Organizers, if it affects every team |
| Partner setup, access, service errors | Partner resource area | That partner's support |
| Agent design, frameworks, debugging | Mentor office hours | — |
| Model provider auth, rate limits, billing | Your provider's support | — |
| Submission requirements | Official Rules | Organizers, if genuinely ambiguous |
| Platform access, schedule, admin | A moderator | Organizers |
| Exposed credentials, sensitive data, safety | **Private message to a moderator** | Organizers, privately |
| Official rule or schedule change | Announcements | — |

**Anything sensitive goes private first.** Exposed credentials, personal data, a security concern or a safety issue: ask for a private route without posting the details, and rotate anything exposed while you wait.

---

## 11. What Counts as Urgent

Use `[URGENT]` only when it's time-critical and blocks participation or submission.

**Urgent:**

- `[URGENT][Submission]` Can't submit because the form or platform is failing
- `[URGENT][Partner]` A partner service is down and it's blocking the final run
- `[URGENT][Access]` Registered participant can't get into HackOS

**Not urgent:**

- General architecture feedback
- Non-blocking improvements
- Requests for ideas
- Questions already answered in the FAQ or Announcements

Overusing it makes it useless for the people who genuinely need it at 23:00 on 20 October.

---

## 12. Response Expectations

| Priority | Example | Handling |
|---|---|---|
| **Critical** | Platform access failure, submission blocked | Fastest available, escalated |
| **High** | Build failure near the deadline, partner outage blocking a demo | Prioritised |
| **Medium** | Architecture clarification, track scope, a framework issue with a workaround | Normal |
| **Low** | Optimisation ideas, polish, general opinions | Best effort |

This is a global event across every time zone, running for 144 hours. Moderators and mentors aren't awake at all hours. Response times stretch during the final 24 hours, so raise anything structural early.

---

## 13. Good Examples

**Partner**

````markdown
[Partner][Zetaris] 401 Unauthorized from inside Docker, works locally

**Partner:** Zetaris
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

**Track:** Fragmented
**Framework:** Custom FastAPI + [provider] SDK
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
[Track] Is our reconciliation loop enough for Fragmented?

**Track:** Fragmented
**Team size:** 3
**Problem:** Supplier records disagree across three systems
**Agents:** Source Mapper, Reconciler, Conflict Critic, Reporter
**Data:** One CSV export, one public API, one ticket extract
**Question:** The critic sends unsupported resolutions back for a re-check.
Is that enough, or do judges expect branching on confidence too?
````

---

## 14. Checklist Before Posting

1. Is it about a partner technology? → **Partner resource area**, then your track room
2. Is it about your model provider's auth, limits or billing? → **Your provider's support**
3. Is it about scope, or what counts for your track? → **Your track room**
4. Is it about code, Docker, frameworks or architecture? → **Mentor office hours**
5. Is it about what to submit? → **Official Rules**, then your track room
6. Is it about teammates? → **Team-finding**
7. Is it sensitive? → **Private message to a moderator**
8. Is it an official update? → **Read Announcements**

---

## 15. Final Reminders

- **Right room, faster answer.**
- **Never post secrets.** If you do, rotate the key first, then tell a moderator.
- **Search first.** Someone has probably hit it already.
- **Be specific.** The exact error and what you already tried save the most time.
- **Announcements are the source of truth** for deadlines and rule changes.
- **Ask early.** Don't validate your core requirements in the final hour.
- **Post your fix when you solve it.** You'll save someone else an hour.

The rooms exist to unblock you. Use them actively, respectfully, and with enough detail for someone to actually help.
