# Escalation Path

Folder: Community and Support · updated 2026-10-07

# Escalation Path

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**

Where to route urgent issues before and during the hackathon. For **participants, mentors, moderators and organizers**.

Use this when something is **time-sensitive, blocking, sensitive, or beyond normal support**.

---

## 1. Quick Routing

| Issue type | Route to | Where | Examples |
|---|---|---|---|
| **Agent build issues** | Mentors | Mentor office hours on HackOS | Architecture, debugging, frameworks, Docker, orchestration, logs |
| **Track scope and feasibility** | Moderators and organizers | Your track room | What counts, scope, dataset suitability, whether an approach fits |
| **Partner technology** | That partner | Partner resource area, then your track room | Zetaris, NVIDIA, Cursor or Meterless: access, setup, service errors |
| **Your model provider** | Your provider | Their own support | Auth, rate limits, billing, model availability |
| **Submission requirements** | Official Rules, then organizers | Event page, then your track room | What to submit, format, deadlines |
| **Platform and admin** | Organizers | Announcements, or a moderator | HackOS access, registration, teams, schedule |
| **Security, privacy, abuse, safety** | Organizers, **privately** | [TBC: private escalation route] | Leaked credentials, exposed data, harassment, threats, vulnerabilities |

> **[TBC — the most important gap in this document.]** A private escalation route needs to exist before the build window opens: an email address or a named contact that works when someone can't or shouldn't post publicly. "Message a moderator" is circular for someone who has just leaked a key in a public room at 3am.

---

## 2. Severity

| Severity | Definition | Examples | Action |
|---|---|---|---|
| **P0 — Critical** | Security, safety, privacy, or an event-wide outage | A key leaked in a public repo, exposed personal data, harassment or a threat, HackOS down, submission broken near the deadline | Escalate immediately. Don't wait for a normal response. |
| **P1 — Blocking** | A team cannot continue building or submitting | Docker build broken, partner service down, can't access HackOS, submission upload failing | Post in the right place with full details. Escalate if unresolved. |
| **P2 — Important** | Progress affected, but there's a workaround | Framework incompatibility, intermittent errors, unclear scope, dependency conflict | Normal support. Include logs and reproduction steps. |
| **P3 — Informational** | Non-blocking question | Resource links, clarifications, best practice | Ask in the relevant room. |

---

## 3. Routing by Category

### 3.1 Agent build issues → Mentors

Architecture, multi-agent design, frameworks (LangGraph, CrewAI, AutoGen, the OpenAI Agent SDK, custom stacks), tool use, retrieval, memory, orchestration, Docker, runtime behaviour, trace and log design.

**Where:** mentor office hours on HackOS.

**Examples:**

- "My planner ↔ executor ↔ evaluator loop isn't producing usable traces."
- "My container starts but the run endpoint returns a 500."
- "Does this workflow count as the agent doing real work, or is it just chaining?"
- "How should I structure memory across sessions for my track?"

Mentors help you get unstuck. They don't build your project, and what they tell one team they'd tell any team that asked.

### 3.2 Track scope → Your track room

What counts for your track, whether your scope is feasible in six days, dataset suitability, what judges are looking for.

**Escalates to organizers** when the ambiguity affects every team in a track. In that case the answer is confirmed and published publicly, not given to one team privately.

### 3.3 Partner technology → The partner

Access and credentials, setup, connection errors, service behaviour for Zetaris, NVIDIA, Cursor or Meterless.

**Where:** the partner's resource area on HackOS first. Then your track room.

**The triage question:** does the partner's own quickstart work for you?

- **Yes, but your code doesn't** → your code. Mentor office hours.
- **No** → access or the service. The partner's resource area.

**Escalates to** that partner's support when a service is down or credentials aren't provisioning.

### 3.4 Model provider → Your provider

Model choice is open here, so auth failures, rate limits, billing and model availability are between you and the provider you chose.

**Before escalating anywhere:** does a minimal SDK call work outside your agent framework?

- **Yes** → framework configuration. Mentor office hours.
- **No** → your provider's support will be faster than we can be.

Nobody at the hackathon can reset your API key, raise your rate limit or fix your billing.

### 3.5 Submission → Official Rules, then organizers

The Official Rules on the event page are the authority. If they genuinely don't cover your case, ask in your track room and quote the section you read.

**Escalates to organizers** for platform failures and anything that affects deadline compliance. Extensions are decided by organizers only, through an official announcement.

### 3.6 Platform and admin → Organizers

HackOS access, registration, team formation and changes, schedule clarification, results call logistics, prize questions.

**Where:** announcements, or a message to a moderator.

### 3.7 Security, privacy and safety → Organizers, privately

**Do not post details in a public room.**

Use this path for:

- Leaked API keys, committed credentials, exposed tokens
- Sensitive, personal or confidential data exposure
- Vulnerability disclosure
- Suspected account compromise
- Harassment, threats, intimidation
- Any Code of Conduct incident needing confidential handling
- Anything where public discussion would make it worse

**[TBC: the private route.]** Until it's published, post a minimal message asking for private contact with no details, and act on the immediate steps in section 6 while you wait.

---

## 4. Decision Tree

````text
Is anyone at risk, or is this security, privacy or safety?
│
├─ Yes → Private escalation. Do not post publicly.
│
└─ No
   │
   ├─ Is it your model provider (auth, limits, billing)?
   │  ├─ Does a minimal SDK call work outside your framework?
   │  │  ├─ No  → Your provider's support
   │  │  └─ Yes → Framework config → mentor office hours
   │  └─
   │
   ├─ Is it a partner technology?
   │  ├─ Does the partner quickstart work for you?
   │  │  ├─ No  → Partner resource area
   │  │  └─ Yes → Your code → mentor office hours
   │  └─
   │
   ├─ Is it agent code, architecture, Docker, logs?
   │  └─ Yes → Mentor office hours
   │
   ├─ Is it track scope or "does this count"?
   │  └─ Yes → Your track room
   │
   ├─ Is it what to submit?
   │  └─ Yes → Official Rules, then your track room
   │
   └─ Is it access, teams, schedule, prizes?
      └─ Yes → Announcements, or a moderator
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
**Category:** build / partner / provider / submission / platform
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

### Partner issues

````markdown
**Severity:** P1
**Team:**
**Partner:** Zetaris / NVIDIA / Cursor / Meterless
**What I was doing:**
**Environment:** local / Docker
**Does the partner quickstart work for me?** yes / no
**Timestamp (UTC):**
**Error:**
**Impact:** blocking the demo / blocking the build
**Credentials:** not shared
````

### Security and safety

Privately, include: your name and team if it's safe to say, the severity, what happened, who or what is affected, when and where, evidence if you have it, whether it's ongoing, and whether something urgent is needed like key revocation or content removal.

**Do not:** tag the person publicly, post screenshots publicly, repost the leaked secret, further inspect exposed data, or try to prove a vulnerability by exploiting it.

---

## 6. Timing

| Severity | First action | Escalate if no response within | Then |
|---|---|---:|---|
| **P0** | Private escalation immediately | Immediately | Organizers, and the relevant partner or provider |
| **P1** | Post in the right place with full details | A few hours during the build window; faster on 27 October | Ask a moderator to route it |
| **P2** | Post in the right place | A day | Ask a moderator to route it |
| **P3** | Ask in the relevant room | — | — |

This is a global event running 144 hours across every time zone. Moderators and mentors aren't awake at all hours, and response times stretch in the final 24. **Raise anything structural early.** A broken Docker build at 22:00 on 27 October is not a support problem anymore.

---

## 7. Special Cases

### 7.1 A key was committed or exposed

**P0.**

1. **Rotate the key with your provider now.** Not after the message is deleted. Now.
2. Don't post the key anywhere, including in the report.
3. Remove it from the repository.
4. Preserve evidence of where it appeared.
5. Report it privately.
6. Assume the old key is compromised even if the repo was private.

Rotation is yours to do and only your provider can do it. Nobody at the hackathon can revoke it for you.

### 7.2 Rate-limited or out of credit mid-build

Usually **P1** if it blocks you, but it's not an event escalation.

1. Check your provider's dashboard: rate limit, quota or billing.
2. Lower concurrency, cap agent rounds, shorten prompts, cache repeated calls.
3. Switch routine steps to a cheaper model.
4. Run in `SAMPLE_MODE=true` while you work on plumbing.
5. If it's a provider outage rather than your usage, their status page will say so.

This is the case for building a documented sample mode early. When a provider throttles you on day five, a project that still runs on cached data is a project you can still demo.

### 7.3 Submission failing near the deadline

**P1**, or **P0** if event-wide.

1. Post in your track room and tell a moderator.
2. Include screenshots, timestamps and your artifact links.
3. Don't wait until the final minutes if it looks persistent.
4. Keep a timestamped backup of: repository URL, demo video link, architecture document link, final commit hash.

Submissions close **27 October, 23:45 UTC**. It's a hard deadline. Submit early and update.

### 7.4 Unsure whether it's your code, the partner, or your provider

Two questions settle almost everything:

1. **Does a minimal provider call work outside your framework?** No → your provider. Yes → keep going.
2. **Does the partner's quickstart work for you?** No → that partner. Yes → your code, so mentor office hours.

If you're still unsure, post a short summary in your track room and ask for triage.

### 7.5 Code of Conduct or harassment

**Private safety escalation.**

1. Don't engage publicly if it could make things worse.
2. Preserve evidence.
3. Report privately.
4. Moderators may hide content or pause a thread while it's reviewed.

---

## 8. Public vs Private

**Safe in public rooms:** redacted error messages, stack traces with secrets removed, framework and version, model name, general repo structure, non-secret config names, screenshots with secrets removed, public dataset links, general track questions.

**Never public:** API keys, `.env` files, credentials or tokens, personal data, confidential data, exploit details, harassment reports, screenshots containing any of the above.

---

## 9. Moderator Triage Checklist

**1. Classify.** Security, privacy or safety → private, immediately. Partner → partner area. Provider → their support. Build → mentor office hours. Track scope → track room. Submission → Official Rules. Admin → organizers.

**2. Assign severity.** P0 / P1 / P2 / P3.

**3. Ask for what's missing.** Team, track, error excerpt, timestamp, reproduction steps, whether it blocks submission.

**4. Route clearly.**

````markdown
Thanks — this looks like a <category> issue.

Routing to: <mentor office hours / partner resource area / your provider /
organizers / private escalation>

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
| **Mentors** | Build guidance, architecture, debugging, getting teams unstuck |
| **Moderators** | Room health, routing, conduct, escalation |
| **Zetaris / NVIDIA / Cursor / Meterless** | Their own platform access, credentials, service availability, technology support |
| **Your model provider** | Your API key, rate limits, billing, model availability |
| **You** | Your code, your credentials, your data, your submission |

That last row matters more here than at a hackathon with a mandated provider. Open model choice means your keys and your bill are yours, and rotating a leaked key is something only you can do.

---

## 11. Final Rules

1. **Route to the right owner first.** It's the fastest path, not a formality.
2. **Never post secrets.** If you do, rotate first, then report.
3. **Security and safety go private.** Never a public thread.
4. **Evidence, not noise.** Logs, timestamps, reproduction steps, redacted screenshots.
5. **Escalate blockers early.** Not in the final hour.
6. **Ask for triage when unsure.** A short summary in your track room is enough.

---

## 12. Emergency Reminder

If it involves **leaked credentials, sensitive data, harassment, threats or safety**, treat it as urgent and confidential.

**Do not post details publicly.**

Rotate anything exposed immediately, then report through the private route.

**[TBC: publish the private route here before 22 October.]**
