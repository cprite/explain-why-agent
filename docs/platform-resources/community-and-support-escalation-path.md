# Escalation Path

Folder: Community and Support · updated 2026-10-13

# Escalation Path

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**

Where to route urgent issues before and during the hackathon. For **participants, mentors, moderators and organizers**.

Use this when something is **time-sensitive, blocking, sensitive, or beyond normal support**.

**Private escalation route:** **hackathons@genai.works**

---

## 1. Quick Routing

| Issue type | Route to | Where | Examples |
|---|---|---|---|
| **Agent build issues** | Mentors | Mentor office hours on HackOS | Architecture, debugging, frameworks, Docker, orchestration, logs |
| **General technical questions** | Technical team | #help desk channel on HackOS | Errors, setup, anything not covered elsewhere |
| **Track scope and feasibility** | Organizers | Challenge pages, then #help desk | What counts, scope, dataset suitability, whether an approach fits |
| **Sponsor technology** | That sponsor | Sponsor folder in Resources, then Help Zetaris, Help Meterless, Help Cursor or Help NVIDIA | Access, setup, credits, service errors |
| **Your own model provider** | Your provider | Their own support | Auth, rate limits, billing on a non-sponsor provider |
| **Submission requirements** | Official Rules, then organizers | Event page, then #help desk | What to submit, format, deadlines |
| **Rules questions** | Organizers | hackathons@genai.works | Eligibility, pre-existing work, prizes |
| **Platform and admin** | Organizers | Announcements, a moderator, or #help desk | HackOS access, registration, teams, schedule |
| **Security, privacy, abuse, safety** | Organizers, **privately** | **hackathons@genai.works** | Leaked credentials, exposed data, harassment, threats, vulnerabilities |

---

## 2. Severity

| Severity | Definition | Examples | Action |
|---|---|---|---|
| **P0 — Critical** | Security, safety, privacy, or an event-wide outage | A key leaked in a public repo, exposed personal data, harassment or a threat, HackOS down, submission broken near the deadline | Escalate immediately. Don't wait for a normal response. |
| **P1 — Blocking** | A team cannot continue building or submitting | Docker build broken, Zetaris unreachable, can't access HackOS, submission failing | Post in the right place with full details. Escalate if unresolved. |
| **P2 — Important** | Progress affected, but there's a workaround | Framework incompatibility, intermittent errors, unclear scope, dependency conflict | Normal support. Include logs and reproduction steps. |
| **P3 — Informational** | Non-blocking question | Resource links, clarifications, best practice | Ask in the relevant channel. |

---

## 3. Routing by Category

### 3.1 Agent build issues → Mentors

Architecture, agent design, frameworks (LangGraph, CrewAI, AutoGen, the OpenAI Agent SDK, custom stacks), tool use, retrieval, memory, orchestration, Docker, runtime behaviour, trace and log design.

**Where:** mentor office hours on HackOS. General technical questions can also go to #help desk.

**Examples:**

- "My planner ↔ executor ↔ evaluator loop isn't producing usable traces."
- "My container starts but the run endpoint returns a 500."
- "Does this workflow count as the agent doing real work, or is it just chaining?"
- "How should I structure memory across sessions for Reasoning Architecture?"

Mentors help you get unstuck. They don't build your project, and what they tell one team they'd tell any team that asked.

### 3.2 Track scope → Challenge pages, then #help desk

What counts for your track, whether your scope is feasible in six days, dataset suitability, what judges are looking for.

**Escalates to organizers** when the ambiguity affects every team in a track. In that case the answer is confirmed and published in Announcements, not given to one team privately.

### 3.3 Sponsor technology → The sponsor

Access and credentials, credits, setup, connection errors and service behaviour for Zetaris, Meterless, Cursor or NVIDIA.

**Where:** the sponsor's folder in Resources on HackOS first. Then that sponsor's Help channel: Help Zetaris, Help Meterless, Help Cursor or Help NVIDIA.

**The triage question:** does the sponsor's own quickstart or verification step work for you?

- **Yes, but your code doesn't** → your code. Mentor office hours.
- **No** → access or the service. The sponsor's Help channel.

**Escalates to** that sponsor's support team, through organizers if needed, when a service is down or credentials or credits aren't provisioning.

### 3.4 Model provider

If your product runs on Meterless or NVIDIA, key, credit and rate-limit problems go to that sponsor's Help channel.

If you chose another provider, auth failures, rate limits, billing and model availability are between you and that provider.

**Before escalating anywhere:** does a minimal SDK call work outside your agent framework?

- **Yes** → framework configuration. Mentor office hours.
- **No** → the provider: the sponsor's Help channel for Meterless or NVIDIA, or your own provider's support.

Nobody at the hackathon can reset a non-sponsor API key, raise its rate limit or fix its billing.

### 3.5 Submission → Official Rules, then organizers

The Official Rules on the event page are the authority. If they genuinely don't cover your case, ask in #help desk and quote the section you read, or email hackathons@genai.works.

**Escalates to organizers** for platform failures and anything that affects deadline compliance. Extensions are decided by organizers only, through an official announcement.

### 3.6 Platform and admin → Organizers

HackOS access, registration, team formation and changes, schedule clarification, results call logistics, prize questions.

**Where:** Announcements, a moderator, or #help desk.

Remember that team composition locks when a team's first submission is created. Roster problems after that point go to hackathons@genai.works.

### 3.7 Security, privacy and safety → Organizers, privately

**Do not post details in a public channel.**

**Where:** **hackathons@genai.works**, or a direct message to a moderator.

Use this path for:

- Leaked API keys, committed credentials, exposed tokens
- Sensitive, personal or confidential data exposure
- Vulnerability disclosure
- Suspected account compromise
- Harassment, threats, intimidation
- Any Code of Conduct incident needing confidential handling
- Anything where public discussion would make it worse

If you need to flag something publicly first, post a minimal message asking for private contact, with no details, and act on the immediate steps in section 7 while you wait.

---

## 4. Decision Tree

````text
Is anyone at risk, or is this security, privacy or safety?
│
├─ Yes → hackathons@genai.works. Do not post publicly.
│
└─ No
   │
   ├─ Is it your model provider (auth, limits, billing)?
   │  ├─ Does a minimal SDK call work outside your framework?
   │  │  ├─ No  → Meterless or NVIDIA: that sponsor's Help channel
   │  │  │        Any other provider: your provider's support
   │  │  └─ Yes → Framework config → mentor office hours
   │
   ├─ Is it Zetaris, Meterless, Cursor or NVIDIA?
   │  ├─ Does the sponsor quickstart or verification step work for you?
   │  │  ├─ No  → Sponsor folder in Resources, then its Help channel
   │  │  └─ Yes → Your code → mentor office hours
   │
   ├─ Is it agent code, architecture, Docker, logs?
   │  └─ Yes → Mentor office hours, or #help desk
   │
   ├─ Is it track scope or "does this count"?
   │  └─ Yes → Challenge pages, then #help desk
   │
   ├─ Is it what to submit?
   │  └─ Yes → Official Rules, then #help desk
   │
   └─ Is it access, teams, schedule, prizes?
      └─ Yes → Announcements, a moderator, or hackathons@genai.works
````

---

## 5. What to Include

### Technical issues

Team name, track, severity, a one-line summary, what you expected, what happened, steps to reproduce, the exact error, the relevant file or endpoint, whether it fails locally or in Docker, whether it blocks submission, and relevant log lines.

**Never include:** API keys, `.env` contents, credentials, private data.

````markdown
**Severity:** P1 — blocking
**Team:**
**Track:**
**Category:** build / sponsor / provider / submission / platform
**Summary:** <one sentence>

**Expected:**
**Actual:**

**Steps to reproduce:**
1.
2.

**Error:**
```text
<redacted>
```

**Impact:** blocked build / blocked submission / intermittent
**Already tried:**
````

### Sponsor issues

````markdown
**Severity:** P1
**Team:**
**Sponsor:** Zetaris / Meterless / Cursor / NVIDIA
**What I was doing:**
**Environment:** local / Docker
**Does the sponsor quickstart or verification step work for me?** yes / no
**Timestamp (UTC):**
**Error:**
**Impact:** blocking the demo / blocking the build
**Credentials:** not shared
````

### Security and safety

Privately, to hackathons@genai.works, include: your name and team if it's safe to say, the severity, what happened, who or what is affected, when and where, evidence if you have it, whether it's ongoing, and whether something urgent is needed like key revocation or content removal.

**Do not:** tag the person publicly, post screenshots publicly, repost the leaked secret, further inspect exposed data, or try to prove a vulnerability by exploiting it.

---

## 6. Timing

| Severity | First action | Escalate if no response within | Then |
|---|---|---:|---|
| **P0** | hackathons@genai.works, immediately | Immediately | Organizers, and the relevant sponsor or provider |
| **P1** | Post in the right channel with full details | A few hours during the build window; faster on 27 October | Ask a moderator to route it |
| **P2** | Post in the right channel | A day | Ask a moderator to route it |
| **P3** | Ask in the relevant channel | — | — |

This is a global event running 144 hours across every time zone. Moderators and mentors aren't awake at all hours, and response times stretch in the final 24. **Raise anything structural early.** A broken Docker build at 22:00 on 27 October is not a support problem anymore.

---

## 7. Special Cases

### 7.1 A key was committed or exposed

**P0.**

1. **Rotate the key now.** Not after the message is deleted. Now.
2. Don't post the key anywhere, including in the report.
3. Remove it from the repository history.
4. Preserve evidence of where it appeared.
5. Report it privately to hackathons@genai.works.
6. Assume the old key is compromised. Your repository will be public, so treat any committed key as exposed.

Rotation is yours to do. For a Zetaris, Meterless or NVIDIA key, create a new one in that service; for any other provider, only that provider can revoke it.

### 7.2 Rate-limited or out of credit mid-build

Usually **P1** if it blocks you.

1. Check your usage: Meterless credit, NVIDIA rate limits, or your own provider's dashboard.
2. Lower concurrency, cap agent rounds, shorten prompts, cache repeated calls.
3. Switch routine steps to a smaller model.
4. Run in `SAMPLE_MODE=true` while you work on plumbing.
5. For Meterless or NVIDIA, ask in that sponsor's Help channel. For other providers, check their status page.

This is the case for building a documented sample mode early. When you're throttled on day five, a project that still runs on cached data is a project you can still demo.

### 7.3 Submission failing near the deadline

**P1**, or **P0** if event-wide.

1. Post in #help desk and tell a moderator.
2. Include screenshots, timestamps and your links.
3. Don't wait until the final minutes if it looks persistent.
4. Keep a timestamped backup of: repository URL, demo video, slide deck, sponsor technology explanation, final commit hash.

Submissions close **27 October, 23:45 UTC**. It's a hard deadline. Submit early and update.

### 7.4 Unsure whether it's your code, a sponsor, or your provider

Two questions settle almost everything:

1. **Does a minimal provider call work outside your framework?** No → the provider. Yes → keep going.
2. **Does the sponsor's quickstart or verification step work for you?** No → that sponsor's Help channel. Yes → your code, so mentor office hours.

If you're still unsure, post a short summary in #help desk and ask for triage.

### 7.5 Code of Conduct or harassment

**Private safety escalation.**

1. Don't engage publicly if it could make things worse.
2. Preserve evidence.
3. Report privately to hackathons@genai.works, or by direct message to a moderator.
4. Moderators may hide content or pause a thread while it's reviewed.

---

## 8. Public vs Private

**Safe in public channels:** redacted error messages, stack traces with secrets removed, framework and version, model name, general repo structure, non-secret config names, screenshots with secrets removed, public dataset links, general track questions.

**Never public:** API keys, `.env` files, credentials or tokens, personal data, confidential data, exploit details, harassment reports, screenshots containing any of the above.

---

## 9. Moderator Triage Checklist

**1. Classify.** Security, privacy or safety → private, immediately. Sponsor technology → sponsor folder and Help channel. Own provider → their support. Build → mentor office hours or #help desk. Track scope → challenge pages and #help desk. Submission → Official Rules. Admin → organizers.

**2. Assign severity.** P0 / P1 / P2 / P3.

**3. Ask for what's missing.** Team, track, error excerpt, timestamp, reproduction steps, whether it blocks submission.

**4. Route clearly.**

````markdown
Thanks — this looks like a <category> issue.

Routing to: <mentor office hours / #help desk / Help Zetaris / Help Meterless /
Help Cursor / Help NVIDIA / your provider / organizers / private escalation>

Please add:
- <missing item>
- <missing item>

Reminder: don't share API keys, .env files or sensitive data here.
````

**5. Follow up.** For P0 and P1, confirm the owner acknowledged, check whether the team is still blocked, move sensitive details private, and log anything event-wide for the retrospective.

---

## 10. Who Owns What

| Owner | Responsible for |
|---|---|
| **Organizers** | Event decisions, deadlines, eligibility, prizes, announcements, platform, conduct, anything affecting many teams |
| **Technical team** | The #help desk channel and general technical questions |
| **Mentors** | Build guidance, architecture, debugging, getting teams unstuck |
| **Moderators** | Channel health, routing, conduct, escalation |
| **Zetaris / Meterless / Cursor / NVIDIA** | Their own platform access, credentials, credits, service availability, technology support |
| **Your own model provider** | Your API key, rate limits, billing, model availability |
| **You** | Your code, your credentials, your data, your submission |

That last row matters. Open model choice means your keys are yours, and rotating a leaked key is something only you can do.

---

## 11. Final Rules

1. **Route to the right owner first.** It's the fastest path, not a formality.
2. **Never post secrets.** If you do, rotate first, then report.
3. **Security and safety go private.** Never a public thread.
4. **Evidence, not noise.** Logs, timestamps, reproduction steps, redacted screenshots.
5. **Escalate blockers early.** Not in the final hour.
6. **Ask for triage when unsure.** A short summary in #help desk is enough.

---

## 12. Emergency Reminder

If it involves **leaked credentials, sensitive data, harassment, threats or safety**, treat it as urgent and confidential.

**Do not post details publicly.**

Rotate anything exposed immediately, then report to **hackathons@genai.works**.
