# Office Hours Guide

Folder: Judge and Mentor Resources · updated 2026-09-30

# Mentor Office Hours Guide

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**

How office hours run during the **15–20 October build window**. For **participants** and **mentors**.

Office hours exist to unblock teams fast, improve architecture decisions, clarify requirements, and help teams submit something judges can actually run. They are not a substitute for building.

> **144 hours total.** A session that takes a day to book is a session that arrives too late. Everything below is designed around that constraint.

---

## 1. Purpose

Office hours help teams:

- Clarify track scope and feasibility
- Debug agent frameworks: LangGraph, CrewAI, AutoGen, LangChain, the OpenAI Agent SDK, custom stacks
- Improve how agents actually work together
- Sort out data, reproducibility and runtime problems
- Get partner technology integrated
- Check submission readiness before **20 October, 23:45 UTC**

Every session should end with a clear next action.

---

## 2. Key Dates

All times **UTC**.

| Milestone | Date | Notes |
|---|---|---|
| Registration closes | 13 October, 00:00 | Hard deadline |
| Participant onboarding | 14 October | Tracks, partner stack, HackOS walkthrough |
| **Build window opens** | **15 October, 00:00** | Office hours active |
| Mid-build checkpoint | 17 October | Teams should have a working end-to-end loop |
| Final day | 20 October | Focus shifts entirely to validation and packaging |
| **Submissions close** | **20 October, 23:45** | Hard deadline |
| Results | 30 October, 16:00 | Live call |

---

## 3. Who Office Hours Are For

**For:** individuals and teams blocked on technical, data, architecture, partner or submission questions; teams wanting feedback on how their agents collaborate; teams checking submission readiness.

**Not for:** asking a mentor to write your code, prompts or architecture; requesting private credentials or exceptions; replacing reading the documentation; line-by-line debugging of a large codebase with no minimal reproducible case.

---

## 4. Principles

### 4.1 Be specific

Arrive with a clear question, error or decision.

**Good:**

- "Our Postgres call works locally but fails in Docker. Here's the error and our compose setup."
- "We're on CrewAI and our agents run linearly. How do we add an evaluator feedback loop?"
- "Our data load takes 20 minutes. What's the right fallback?"
- "Can you sanity-check whether our traces show what judges are looking for?"

**Not useful:**

- "Can you help us build the whole thing?"
- "What should we make?"
- "Can you review our repo with no context?"

### 4.2 Fairness

**Mentors may:** explain requirements, review architecture at a high level, suggest debugging approaches, point to templates and docs, help interpret errors, flag risks, recommend next steps.

**Mentors must not:** write production code, create the agent prompts or business logic, give one team information others don't have, change judging criteria, grant extensions, or approve a non-compliant submission.

The test: would you give this same help to every team that asked?

### 4.3 Push toward something judges can run

Whatever the question, mentors should bring teams back to the minimum:

- It runs from a clean clone
- A judge can drive it without the UI
- Traces show how the agent reached its output
- Sample mode works with no credentials
- Sample inputs and outputs exist
- No secrets committed
- Demo video recorded and the link works
- Partner technology use documented

---

## 5. Booking

Book through the office hours area on HackOS.

### 5.1 Steps

1. Log in to HackOS
2. Open **Mentor office hours**
3. Pick a triage category: **Partner / Framework / Data / Submission / General**
4. Choose a slot
5. Fill in the form
6. Watch for confirmation

### 5.2 Lead time

Because the whole event is six days, lead times are hours, not days.

| Request | Lead time |
|---|---|
| Architecture review | Same day |
| Framework or partner debugging | A few hours |
| Submission readiness check | Book on day 4 or 5, not day 6 |
| Urgent blocker on 20 October | As soon as you hit it |

**If a slot isn't available in time, post in your track room.** A written question answered in 40 minutes beats a session in eight hours. Office hours are for problems that need conversation.

### 5.3 Limits

- One active slot at a time per team
- Don't book duplicates for the same issue
- **Cancel if you get unblocked**, so someone else can use it
- On 20 October, priority goes to teams blocked from submitting at all

### 5.4 Booking form

```markdown
Team name:
Track:
Framework / stack:
Model provider:
Current status:
Main blocker:
What we've tried:
Relevant files or snippets:
Error or log excerpt:
What we want out of the session:
```

**Example:**

```markdown
Team name: SupplyLens
Track: Fragmented
Framework / stack: LangGraph + FastAPI
Model provider: [provider]
Current status: Source Mapper and Reconciler working locally; Docker run fails on Postgres
Main blocker: localhost:5432 unreachable from inside the container
What we've tried: Confirmed the instance runs; passed env vars with docker run
Relevant files: run.py, app/db.py, Dockerfile
Error: connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused
Want: the right Docker networking pattern for a local Postgres instance
```

---

## 6. Triage Categories

Pick the one that describes your **first** blocker.

### 6.1 Partner

Zetaris, NVIDIA, Cursor, Meterless: access, setup, connection errors, service behaviour.

**Bring:** which partner, what you were doing, the exact error, local or Docker, and **whether the partner's own quickstart works for you**.

That last question decides everything. Quickstart works but your code doesn't → your code, and a mentor can help. Quickstart doesn't work → access or the service, so it goes to the partner's resource area.

[TBC: partner setup specifics are published in each partner's resource area on HackOS.]

### 6.2 Framework

Agent framework, orchestration, backend, implementation design.

**Common:** LangGraph state flow, CrewAI delegation, AutoGen conversation loops, retrieval integration, custom orchestration, the run endpoint, trace logging, retry handling, shared memory, turning a prompt chain into agents that actually collaborate.

**Bring:** framework and version, your architecture in a few lines, your agents and roles, the current interaction pattern, an example trace, and the specific failure or design question.

**What mentors push toward:**

Weak:

```text
Agent A produces output
Agent B rewrites it
Agent C summarises it
Done
```

Stronger:

```text
Planner creates a task plan
Executor attempts the solution
Evaluator checks the output against criteria
Planner revises the plan on the critique
Executor retries the failed section
Risk Agent flags remaining uncertainty
Synthesizer produces the answer with caveats and a trace
```

Patterns worth suggesting: Planner–Executor–Evaluator, Researcher–Critic–Synthesizer, Router–Specialists–Reviewer, Tool Agent–Reasoning Agent–Validator, memory-backed collaboration loops.

Mentors suggest the pattern. Teams implement it.

### 6.3 Data

Dataset choice, ingestion, licensing, size, automated downloads, public APIs, reproducibility.

**Bring:** your track, the data source and size, whether it's committed, downloaded or fetched at runtime, whether auth is needed, your ingestion flow, expected runtime, and your fallback.

**Rules to reinforce:**

1. **Static data in the repository** — small, documented sources, keep the repo light
2. **Automated download** — scripted, no login, no manual clicks
3. **Runtime public APIs** — timeouts, retries, and a fallback

**Not allowed:** private datasets without permission, manual downloads during evaluation, credentials a judge can't have, long downloads inside a run.

**Triage questions:** Can it run on a small sample? Does `SAMPLE_MODE=true` work? Does the judged path avoid heavy downloads? Are sources documented? Are API failures handled?

### 6.4 Submission

Repository structure, validation, demo video, logs, Docker, readiness.

**Bring:** the repo link or structure, your README, your Dockerfile, an example request and response, a log excerpt, demo video status, and any known failures.

**Readiness check before booking:**

- [ ] Runs from a clean clone
- [ ] A judge can drive it without the UI
- [ ] `.env.example` exists, no real keys
- [ ] No secrets committed anywhere
- [ ] Traces show real agent interaction
- [ ] Sample mode works with no credentials
- [ ] At least 3 sample inputs and matching outputs
- [ ] README covers setup, architecture and limitations
- [ ] Partner technology use documented
- [ ] Demo video 2–3 minutes, link accessible

[TBC: the binding submission requirements are in section 6 of the Official Rules.]

**Risks mentors should flag immediately:** a build that fails from a clean clone, a project only the author can run, hardcoded outputs, no traces, committed secrets, a dead demo link, partner tech named but not used.

### 6.5 General

Team formation, track choice, scope reduction, planning, demo planning, where to ask.

**Bring:** team size, track, current stage, main uncertainty, decision needed, deadline sensitivity.

Mentors help teams choose a feasible scope, cut complexity, prioritise the working system over polish, and understand what the rubric rewards.

---

## 7. Session Formats

### 7.1 Quick triage — 10 minutes

For confirming a category, pointing at the right place, clarifying one error, deciding whether to escalate.

| Time | Activity |
|---|---|
| 0–2 | Team states the blocker and what they want |
| 2–5 | Mentor asks clarifying questions |
| 5–8 | Mentor identifies the likely cause and next step |
| 8–10 | Agree the action and where follow-up happens |

**This should be the default format during the build window.** Most blockers are a category error or a missing environment variable, and both are ten-minute problems.

### 7.2 Standard — 25 minutes

For architecture feedback, framework debugging, data strategy.

| Time | Activity |
|---|---|
| 0–3 | Confirm team, track, session goal |
| 3–8 | Team shows current status and evidence |
| 8–15 | Mentor diagnoses or reviews the design |
| 15–21 | Options, trade-offs, risks |
| 21–24 | Agree next actions |
| 24–25 | Confirm owner and follow-up |

### 7.3 Final-day review — 20 minutes

For 19–20 October.

| Time | Activity |
|---|---|
| 0–3 | Confirm status and deadline risk |
| 3–8 | Does it run from a clean clone? |
| 8–12 | Do the traces show the agent working? |
| 12–16 | Demo, README, examples, secrets scan |
| 16–20 | Blockers by priority, next actions |

### 7.4 Group clinic — 45 minutes

For common topics: partner setup, "from pipeline to real collaboration", Docker and runtime, the submission checklist, demo video.

Record or summarise these. One clinic answering a common question saves twenty individual sessions, which matters enormously when the whole event is six days.

---

## 8. Session Structure

**Opening.** Confirm team, track, category, desired outcome, time available.

> "We have 25 minutes. The goal is to work out why your Postgres call fails in Docker and leave with a fix or a clear escalation."

**Evidence.** Get the error, snippet, logs, architecture or screen share early. Don't spend the session on verbal description.

**Diagnosis.** Classify it: requirement misunderstanding, architecture gap, implementation bug, partner service, provider configuration, data reproducibility, submission risk, or a programme question.

**Recommendation.** Preferred next step, a faster alternative if time is short, the risks, the relevant resource, and an escalation path if needed.

**Closeout.**

```markdown
Decision:
Next action:
Owner:
By when:
Follow-up:
Escalation needed: yes/no
```

---

## 9. Participant Preparation

### Technical issues

- [ ] The exact error
- [ ] A minimal reproducible example
- [ ] The relevant snippet
- [ ] Framework, version, provider
- [ ] Local, Docker, or both
- [ ] Environment variable names used
- [ ] Log excerpt
- [ ] What you already tried

### Architecture feedback

- [ ] Track
- [ ] Agents and roles
- [ ] Interaction flow
- [ ] Where delegation, critique, retry or escalation happens
- [ ] Memory or shared context approach
- [ ] Tools, APIs, models, datasets
- [ ] Known limitations

### Submission review

- [ ] Repo structure
- [ ] README
- [ ] `.env.example`
- [ ] An example request and response
- [ ] Sample inputs and outputs
- [ ] Trace logs
- [ ] Demo video status
- [ ] Build status from a clean clone

---

## 10. Mentor Preparation

**Before a block:**

- [ ] Review bookings, sorted by category and urgency
- [ ] Spot likely escalations in advance
- [ ] Keep the guides open: submission requirements, technical guide, troubleshooting, partner resource areas, the self-check
- [ ] Confirm which rooms are active for escalation

**During:**

- [ ] Keep the team on one primary blocker
- [ ] Ask for evidence
- [ ] Don't write their code
- [ ] Flag anything that would make the project unscoreable
- [ ] Document the next step

**After:**

- [ ] Post follow-up notes
- [ ] Escalate what's unresolved
- [ ] **Flag recurring problems to organizers** — two teams with the same issue means twenty have it
- [ ] Feed common answers back into the FAQ

---

## 11. Follow-Up

### Participants

1. Do the agreed action
2. Reply in the agreed thread with the outcome
3. Share updated evidence if it persists
4. Book again only if you've made progress and have a new specific blocker

```markdown
Office hours follow-up

Team:
Track:
Original issue:
Action taken:
Result:
Remaining blocker:
Evidence:
Need more support: yes/no
```

### Mentors

```markdown
Office hours note

Date/time (UTC):
Mentor:
Team:
Track:
Category:
Issue:
Advice given:
Owner:
By when:
Escalation needed:
Follow-up location:
```

### Response targets

Targets, not guarantees.

| Issue | Target |
|---|---|
| Blocked from submitting on 20 October | Immediately |
| Partner service issue affecting several teams | Same day |
| Framework or architecture question | Within hours during the build window |
| Data or reproducibility question | Same day |
| General question | Same day |
| Non-urgent suggestion | Best effort |

This is a global event with mentors across time zones. Publish the rota so teams know when coverage exists rather than guessing at silence.

### Escalate when

- Several teams report the same partner problem
- A team can't get partner access at all
- HackOS appears to be down
- Someone reports a security or privacy concern
- A submission requirement looks genuinely ambiguous
- A team may be blocked from submitting despite doing everything right
- A question needs an official decision
- Credentials have been committed to a repository
- There's a Code of Conduct concern

---

## 12. Escalation

| Issue | First stop | Owner |
|---|---|---|
| Partner access, setup, service errors | Partner resource area | That partner's support |
| Model provider auth, rate limits, billing | Your provider's support | Your provider |
| Agent architecture, frameworks, debugging | Mentor office hours | Mentors |
| Track scope | Your track room | Moderators, then organizers |
| Submission requirements | Official Rules | Organizers |
| Platform, schedule, teams | Announcements or a moderator | Organizers |
| Security, sensitive data, safety | **Private escalation** | Organizers, privately |

**Nobody at the hackathon can fix a participant's provider account.** If a minimal SDK call fails outside their framework, that's their provider's support, and saying so quickly saves everyone time.

[TBC: the private escalation route needs publishing before 15 October.]

---

## 13. Guidance by Stage

### Day 1–2 (15–16 October)

**Focus:** track confirmed, architecture decided, partner tech connected, repo scaffolded, first agent-to-agent interaction working.

Mentors should ask: Is this scope feasible in six days? Are the agents distinct and useful? Does the provider connection work in Docker as well as locally? Is this more than a chain?

**Milestone by end of day 2:** a minimal end-to-end run works, even if the output is poor.

### Day 3–4 (17–18 October)

**Focus:** depth of agent behaviour, data, logging, tool use, error handling.

Mentors should ask: Do agents critique or validate each other? Do the traces show it? Does data load automatically? Does it survive a partial failure? Is there a fallback mode?

**Milestone by end of day 4:** traces exist, data is stable, output quality is testable, and **the full validation flow has been run once**. Two days is enough to fix what it finds. Two hours isn't.

### Day 5–6 (19–20 October)

**Focus:** reproducibility, packaging, demo, README, final validation.

Mentors should ask: Does it run from a clean clone on another machine? Does sample mode work with no credentials? Are there secrets anywhere, including the video? Does the demo show the real system? Is the link accessible?

**Milestone by midday 20 October:** submitted. Then improve and resubmit if time allows.

---

## 14. Common Patterns

**"Our agents are just a chain."**

Ask what decision each agent actually owns. Add a critic or evaluator. Add a revision loop. Add shared context. Make sure the traces show it.

```text
Current:  Scraper → Summarizer → Recommender

Better:   Research Planner assigns queries
          Scraper retrieves
          Summarizer extracts findings
          Risk Critic challenges unsupported claims
          Planner requests more retrieval when confidence is low
          Recommender synthesizes with confidence and caveats
```

**"It works locally but not in Docker."**

Check environment variables reach the container. Check the app binds to `0.0.0.0`, not `127.0.0.1`. Check no dependency installs at runtime. For a local partner service, `localhost` inside a container is the container, not the host.

**"Our dataset is too large."**

Smaller representative sample, `SAMPLE_MODE=true`, heavy work moved outside the run path, lightweight API calls, limitations documented.

**"We have a great UI but nothing a judge can call."**

Product & UX is 10 points; Technical is 20 and Demo is 15, and both depend on a judge being able to run it. Get the programmatic path working before polishing screens.

**"Which model provider should we use?"**

Their choice, entirely. What matters: credentials from environment variables, the seam abstracted so a switch costs one line, capped loops so a runaway retry doesn't drain their budget, and a sample mode so a judge without their keys still sees it work.

**"How much partner tech do we need to use?"**

Sponsor Tech is 10 points and rewards genuine use. One layer that's load-bearing beats three that are decorative, and judges can tell the difference.

---

## 15. Quality Bar

**A good session ends with:** a diagnosed issue, one or two realistic next actions, clear ownership, a documented follow-up place, escalation if needed, and less risk of the project being unscoreable.

**A poor session:** tries to solve everything at once, produces no written next step, turns into the mentor implementing, ignores the requirements, offers unofficial exceptions, or records nothing.

---

## 16. What Teams Should Prioritise

| Focus on | Not this | Why |
|---|---|---|
| A working agent | Slideware | Judges run what you submit |
| Agents that act and recover | Linear chains | It's what separates real work from prompting |
| Traces | Hidden reasoning | Judges need evidence |
| Reproducibility | Manual setup | If they can't run it, they can't score it |
| Sample mode | Credential dependence | Judges may not have your keys |
| A small reliable data path | Heavy downloads | Long runs are hard to demo and easy to break |
| Partner tech that earns its place | Decorative integration | 10 points, and it's checked |
| A clear README | Assumed knowledge | It's the first thing they open |

---

## 17. Before You Book

1. What exactly is blocked?
2. What evidence can I show?
3. Which category fits?
4. What decision do I need?
5. Have I checked the guide first?
6. **Would a written question in my track room be faster?**

The strongest teams use office hours to make one decision quickly and get back to building.

The goal isn't a polished demo. It's an agent that does real work, that someone other than you can run.
