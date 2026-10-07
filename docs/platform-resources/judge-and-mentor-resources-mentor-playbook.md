# Mentor Playbook

Folder: Judge and Mentor Resources · updated 2026-10-07

# Mentor Playbook

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**
**Internal guide for mentors during the 22–27 October build window**

---

## 1. Purpose

This playbook standardises how mentors support teams during the build window.

Your role is to **guide, unblock, challenge and escalate**. Not to build on anyone's behalf.

Use it to understand what mentors should and shouldn't do, how sessions run, how to steer teams toward agents that actually work, how to answer the common questions, and when to escalate.

---

## 2. Event Context

| Item | Detail |
|---|---|
| Event | **Open Agent Hackathon 2026** |
| Audience | Builders worldwide, 16 and over, free to enter |
| Format | Fully online, 144 hours |
| Teams | 1–5 builders |
| Participant onboarding | **21 October** |
| Build window | **22–27 October** |
| Registration closes | **22 October, 23:59 UTC** |
| Submissions close | **27 October, 23:45 UTC** |
| Results | **6 November, 16:00 UTC** |
| Tracks | 4 |
| Partners | Zetaris (data), NVIDIA (models), Meterless (cognition), Cursor (coding) |
| Models | Open choice, including closed-source and paid APIs |
| Prize pool | Up to $20,000 |
| Platform | HackOS |

### The mission

This is not a prompt-writing competition or a UI showcase. Teams build agents that can access relevant information, understand context and relationships, reason across multiple steps, maintain useful context, and turn that into something useful.

**Six days.** Everything you advise should account for that. Ambition that can't ship by 23:45 on 27 October is a scoring problem, not a virtue.

---

## 3. The Mentor Role

### 3.1 What you're here to do

- Clarify requirements
- Help teams scope realistically
- Review architecture at a conceptual level
- Ask probing questions about how agents actually work together
- Flag anything that would make a project unscoreable
- Suggest debugging approaches
- Point at the right resource or room
- Escalate blockers
- Push teams toward something a judge can run

### 3.2 What you're not here to do

- Write production code
- Build agent workflows for a team
- Debug a full repository line by line
- Create or edit submissions
- Share credentials
- Approve exceptions
- Promise anyone will pass or win
- Tell a team exactly what to build
- Give one team information others don't have
- Score submissions unless you're formally a judge

---

## 4. Principles

**Be fair.** Equal access for every team. If advice is broadly useful, tell them to ask it in their track room so everyone benefits.

**Be practical.** Prioritise whatever helps them ship something working by the deadline. A simple, well-logged agent that runs beats an ambitious one that doesn't.

**Protect ownership.** Teams own their architecture, code and decisions. Guide and challenge; don't take over.

**Reinforce what matters.** Runs from a clean clone. Drivable without the UI. Traces that show the work. Sample mode with no credentials. No committed secrets. Honest README. Demo that works.

**Push for agents that do real work.** Delegation, critique, retry, recovery. Not a chain with three labels on it.

---

## 5. Scope by Topic

| Topic | You can | You must not |
|---|---|---|
| Track and scope | Compare feasibility, data availability, difficulty | Choose for them |
| Architecture | Review roles, loops, memory, tools, orchestration | Design the whole thing |
| Agent collaboration | Explain strong vs weak, suggest patterns | Write their prompts or workflow |
| Partner tech | Point at docs, explain env vars, diagnose common errors | Share credentials |
| Model providers | Explain the abstraction seam, help with framework config | Debug their provider account |
| Frameworks | Discuss trade-offs | Mandate one, or rewrite their implementation |
| Debugging | Isolate error types, suggest next steps | Take the keyboard |
| Submission | Walk the checklist, flag gaps | Certify it will pass |
| Demo | Suggest structure and clarity | Produce it |
| Judging | Explain the rubric | Reveal deliberations or guarantee outcomes |

---

## 6. What to Reinforce

### 6.1 Model choice is open

There is **no mandated provider**. Closed-source models and paid APIs are fine. Teams pay their own costs.

What you should push instead:

- Credentials from environment variables, never hardcoded
- The provider seam abstracted so a switch costs one line
- Capped agent rounds and retries, so a runaway loop doesn't drain a budget overnight
- **A sample mode that runs with no credentials**, because judges may not have theirs

That last one replaces everything the G42 playbook said about a mandated endpoint, and it's the single most useful thing you can tell a team on day one.

### 6.2 Partner technology

Zetaris, NVIDIA, Cursor and Meterless are available and **Sponsor Tech is worth 10 points**. Not mandatory.

Push for: layers that genuinely help, an adapter with a timeout and fallback around each call, and documentation of where each one sits. A partner named in the README but absent from the code scores worse than not mentioning it.

**The triage question:** does the partner's own quickstart work for them? Yes but their code fails → their code, you can help. No → access or the service, so it goes to the partner's resource area.

### 6.3 What judges need

[TBC: the binding submission requirements are in section 6 of the Official Rules.]

Whatever the specifics, a judge needs to: clone it, run it, drive it without the UI, see traces showing how it worked, and watch a demo that isn't only slides.

### 6.4 What costs teams points

- A judge can't run it
- No traces
- Hardcoded outputs
- Secrets committed
- Partner tech named but unused
- README overclaims
- Only works on the author's machine
- Dead demo link
- Submitted at 23:44

---

## 7. Strong vs Weak Collaboration

### Weak

```text
Agent A → Agent B → Agent C → Final Output
```

Signals: agents run once in fixed order, nobody critiques anybody, no feedback, no retries, no branching, no shared state, agents are renamed prompts, logs show sequential calls only.

### Strong

```text
Planner → Executor → Evaluator
   ↑          ↓          |
   └── refinement loop ←─┘
```

```text
Research Agent → Draft Agent → Critic Agent
       ↑              ↓          |
       └──── evidence request ←──┘
```

Signals: dynamic delegation, agents challenging each other, an evaluator sending work back, plans revised on results, shared state, retry logic, branching, escalation, multiple turns in the traces, a final output that visibly reflects refinement.

### Questions to ask

- What decision does each agent own?
- Where does one agent challenge another?
- What happens when an agent produces a weak answer?
- Can the workflow branch on confidence or risk?
- Where is shared context stored?
- What will your traces show to prove it?
- Can the evaluator send work back?
- What happens when your provider rate-limits you mid-run?
- Can a judge run this without your API keys?

That last question catches more teams than any other.

---

## 8. Session Formats

Office hours run through the build window, 22–27 October.

| Format | Length | Best for |
|---|---|---|
| **Quick triage** | 10 min | A specific blocker. **The default in a six-day event.** |
| Standard session | 25 min | Architecture feedback, framework debugging, data strategy |
| Final-day review | 20 min | Submission readiness on 26–27 October |
| Group clinic | 45 min | Common topics: partner setup, pipeline-to-collaboration, Docker, submission |
| Async | — | Track room replies; often faster than waiting for a slot |

**A written answer in 40 minutes beats a session in eight hours.** Say so when a team books a slot for something answerable in a thread.

### Group session agenda

| Time | Activity |
|---|---|
| 0–5 | Welcome, deadline reminder, boundaries |
| 5–10 | Known issues, announcements |
| 10–35 | Questions, grouped by topic |
| 35–40 | Common mistakes and checklist reminders |
| 40–45 | Escalations, where to follow up |

### Triage categories

| Category | Examples | Route |
|---|---|---|
| Partner | Zetaris, NVIDIA, Cursor, Meterless: access, setup, errors | Partner resource area |
| Provider | Auth, rate limits, billing, model names | Their own provider |
| Architecture | Roles, orchestration, collaboration, memory | Mentor office hours |
| Framework | LangGraph, CrewAI, AutoGen, custom | Mentor office hours |
| Data | Sources, APIs, sample mode, reproducibility | Mentor office hours or track room |
| Runtime | Build failure, Docker, dependencies, CPU | Mentor office hours |
| Submission | Structure, README, demo, examples | Official Rules, then track room |
| Programme | Dates, teams, eligibility | Moderators or organizers |
| Security | Exposed secrets, sensitive data | **Private escalation** |

### Ground rules to state at the start

Come with a specific question. Share errors, logs and snippets. **Never share keys.** Don't ask mentors to write code. Keep it concise so everyone gets time. Post follow-ups in your track room so others benefit.

---

## 9. Hard Boundaries

### 9.1 Don't write their code

**Acceptable:**

> "Your evaluator should probably send low-confidence outputs back to the planner. Log that retry as its own trace event."

**Not acceptable:**

> "Send me your repo and I'll implement the evaluator loop."

You may explain an approach, point at examples, suggest debugging steps. You may not write functions, prompts or workflows, commit to their repository, open pull requests, take screen control to code, or produce their README, demo script or Dockerfile.

### 9.2 Don't create unfair advantage

Nothing exclusive that materially changes a team's competitive position. If a question reveals a common ambiguity, get it answered publicly.

The test: would you give this same answer to every team that asked?

### 9.3 Don't approve exceptions

Not for late submissions, missing components, manual setup, or anything else. Route exception requests to organizers.

### 9.4 Don't handle secrets

Never ask anyone to paste an API key, a real `.env`, credentials or sensitive data. If a secret is exposed, escalate immediately and tell them to **rotate it with their provider first**.

### 9.5 Don't make judging commitments

Avoid "this will win", "you'll pass", "judges will love this".

Use: "This looks aligned with the published requirements, but scoring follows the official process."

---

## 10. Escalation

| Issue | Escalate to | Where |
|---|---|---|
| Partner service, access, credentials | That partner | Partner resource area, then their support |
| Model provider auth, limits, billing | The participant's provider | Their support |
| Track scope ambiguity affecting everyone | Organizers | Track room, then published publicly |
| Submission requirement ambiguity | Organizers | Official Rules, then escalate |
| Platform, schedule, teams, eligibility | Organizers | Moderator or announcements |
| Exposed secrets, sensitive data, safety | Organizers, **privately** | [TBC: private route] |

**Nobody at the hackathon can fix a participant's provider account.** Saying so quickly is more useful than trying.

### Escalate when

- Several teams report the same partner problem
- A team can't get partner access at all
- HackOS appears down
- Someone reports a security or privacy concern
- A requirement looks genuinely ambiguous
- A team may be blocked from submitting despite doing everything right
- Credentials have been committed
- There's a Code of Conduct concern

### Template

```text
Escalation type:
Team:
Track:
Issue summary:
Why it needs escalation:
Impact:
Blocking submission? yes/no
Logs or screenshots:
Secrets removed? yes/no
Already tried:
Recommended owner:
Deadline sensitivity:
```

---

## 11. Common Guidance

### 11.1 Scoping

**Good advice:** start narrow, build the core loop first, use sample data early, add real data once it runs, prioritise logs and reproducibility, no heavy downloads in the run path, UI only after the programmatic path works.

**Warning signs:** a whole day on UI, no working entry point by day three, partner tech "to be added later", agents not clearly defined, a pipeline needing manual setup, a GPU requirement, a run that takes an hour.

### 11.2 Build order

1. Confirm track, user and output
2. Define 2–5 agents with distinct responsibilities
3. Design the collaboration loop
4. Make one model call work, in Docker as well as locally
5. Get a programmatic entry point working
6. **Add trace logging** — day one, not day five
7. Add sample inputs and outputs
8. Add the data source and a sample mode
9. Connect the partner layers you actually need
10. Dockerise or validate clean local execution
11. Write the README
12. Record the demo
13. Run the full validation flow
14. Submit, then improve

### 11.3 Day 3–4 checkpoint

By 24–25 October a team should be able to say yes to:

- It runs locally
- It runs in Docker
- Provider calls work from inside the container
- At least two agents are implemented
- Traces show interaction between them
- There's a fallback or sample mode
- Sample inputs and outputs exist
- Partner tech is connected, if they're using it
- No secrets in the repo
- The demo story is clear

If a team is missing more than three of these on day four, the advice is cut scope, not push harder.

### 11.4 Final two days

From 26 October, push toward completion, not expansion.

> "Cut scope and make the core reliable."

**Encourage:** freeze architecture, test from a clean clone, remove local-only dependencies, scan for secrets, finish the README, record the demo early, **submit with hours to spare**.

**Discourage:** a new framework, rewriting orchestration, adding a partner integration late, building a complex UI, heavy runtime downloads, undocumented manual steps.

---

## 12. Common Questions

**Can you help us code?**
> I can help you think through the architecture, spot likely bugs, suggest debugging steps and point you at docs. I can't write or edit your submission code.

**Which model provider should we use?**
> Your choice, entirely. Closed-source and paid APIs are fine. What matters is that credentials come from environment variables, the seam is abstracted so you can switch, and there's a sample mode a judge can run without your keys.

**Do we have to use the partner technologies?**
> No, but Sponsor Tech is 10 points and rewards genuine use. One layer that's load-bearing beats three that are decorative.

**Can we use any framework?**
> Yes. LangGraph, CrewAI, AutoGen, the OpenAI Agent SDK, LangChain, LlamaIndex, custom. The framework isn't scored. What's scored is whether the agent does real work and whether you can show it.

**Is a linear pipeline acceptable?**
> It's weak. Add feedback, validation, critique, retries, branching, shared memory or dynamic delegation — and make sure the traces show it.

**Do we need a UI?**
> Product & UX is 10 points, so a usable output helps. But give judges a way to run the agent without clicking through screens, or Technical and Demo both suffer.

**Do we need Docker?**
> Strongly recommended. It's the most reliable way to make sure a judge gets the same result you do. Either way it has to run from a clean clone.

**Can we use external public APIs?**
> Yes, with timeouts, retries and a fallback. And a sample mode, so it still runs when the API is down during judging.

**How big can our dataset be?**
> [TBC: any limit is in the Official Rules.] Keep the repo light regardless. A judge cloning a multi-gigabyte repo moves on.

**We're rate-limited. Can you help?**
> That's between you and your provider. Check their dashboard. Meanwhile: lower concurrency, cap agent rounds, shorten prompts, cache repeated calls, switch routine steps to a cheaper model, and develop in sample mode.

**Can our demo be UI only?**
> The UI can be in the demo, but the video needs to show the system actually working, and judges need to be able to run it themselves.

**What logs do we need?**
> Agent name, action, input summary, output summary, target agent, status, confidence, retries, timestamp. Written to stdout and `logs/`. They must reflect the actual run — never hand-written.

**Can we hardcode outputs for demo stability?**
> No. Sample mode and cached data are fine; a stored answer presented as generated is not, and judges test with their own inputs.

---

## 13. Guidance by Track

Use these to help teams think, without designing for them.

### Fragmented

Agents that query scattered information across disconnected systems and turn it into decisions, reports or recommendations.

**Ask:**

- Which sources, and do they actually disagree with each other?
- What happens when two sources conflict? Who decides?
- Does the output show where each fact came from?
- What does the agent do with a conflict it can't resolve? Guessing is worse than flagging.
- Can a judge see the reconciliation happening, or only the result?

The interesting problem here is disagreement, not retrieval. Push teams toward sources that conflict.

### Autonomous Intelligence

Agents that investigate complex questions across multiple sources and produce evidence-backed answers.

**Ask:**

- How are sources retrieved and validated?
- Which agent checks whether a claim is actually supported?
- How does the system avoid confident unsupported conclusions?
- Does it distinguish evidence from inference?
- What happens when the evidence is thin? Does it say so?

Push toward a critic that can reject, not just review.

### Persistent Memory Agents

Agents that remember, maintain state and continue work across longer tasks.

**Ask:**

- What's worth remembering, and what should decay?
- What happens when two memories contradict?
- How does retrieval decide what's relevant now?
- Can you show a second session doing something different because of the first?
- Does memory survive a restart?

**The demo problem is specific to this track:** memory is invisible in a single run. Push teams to demo three sessions showing what carried over and what changed as a result. A team that doesn't plan this loses the Demo score on a build that actually worked.

### Real-World Industry Agents

Agents for a specific industry or community, solving a concrete operational problem.

**Ask:**

- Who is the actual user, and have you spoken to one?
- What decision or workflow does this improve?
- Is the output in a form they could use?
- What does it do with an ambiguous or malformed input?
- Could this be used next week, or does it need six months?

This track rewards domain knowledge. A team with a real user beats a team with better engineering and no user.

### Sensitive domains

Any track can land on health, finance, law or security. Remind teams to include caveats, avoid presenting output as professional advice, use no real personal data, and keep security work defensive. Escalate anything unsafe.

---

## 14. Do / Don't

**Architecture**

Do: "Your architecture looks like a single pass. Consider an evaluator that can send output back to the planner when confidence is low."

Don't: "Here's the exact LangGraph state machine to implement."

**Debugging**

Do: "That looks like an environment variable issue. Check the variable reaches the process inside the container, not just your shell."

Don't: "Send me your `.env` and I'll test it."

**Submission**

Do: "Check that your repo runs from a clean clone, has sample inputs and outputs, and that sample mode works with no credentials."

Don't: "I confirm this will pass."

**Code**

Do: "The error suggests your server isn't binding to `0.0.0.0` inside Docker. Look at your launch command."

Don't: "I'll rewrite your entry point."

---

## 15. Routing

| Room | For |
|---|---|
| Announcements | Official updates only |
| Track rooms | Track scope, discussion, general build questions |
| Partner resource areas | Zetaris, NVIDIA, Cursor, Meterless |
| Mentor office hours | Architecture, frameworks, debugging |
| Team-finding | Forming and joining teams |
| Private escalation | Secrets, sensitive data, conduct, safety |
| Their own provider | Auth, rate limits, billing |

---

## 16. Before a Session

- [ ] Check the date and where teams should be by now
- [ ] Read any new announcements
- [ ] Check for known partner issues
- [ ] Note the common questions from the last block
- [ ] Keep the guides open: submission requirements, technical guide, troubleshooting, self-check, partner areas
- [ ] Confirm who's covering escalation

## 17. During

- [ ] Remind teams of the deadline: **27 October, 23:45 UTC**
- [ ] Ask them to redact secrets from screenshots and logs
- [ ] Triage by category
- [ ] Keep answers concise and fair
- [ ] Don't write code
- [ ] Push common questions into the track room
- [ ] Note repeated questions for the FAQ
- [ ] Escalate quickly
- [ ] Ask "can a judge run this without your keys?"

## 18. After

- [ ] Post a summary of general guidance where useful
- [ ] Document what's unresolved
- [ ] Escalate to the right owner
- [ ] **Flag recurring problems to organizers** — two teams with the same issue means twenty have it
- [ ] Feed answers back into the FAQ

---

## 19. Readiness Checklist to Share

- [ ] Runs from a clean clone on another machine
- [ ] A judge can drive it without the UI
- [ ] Credentials from environment variables only
- [ ] `.env.example` with placeholders
- [ ] **Sample mode works with no credentials**
- [ ] No secrets anywhere, including the demo video
- [ ] At least 3 sample inputs and matching outputs
- [ ] Traces show real agent interaction
- [ ] README covers setup, architecture and limitations honestly
- [ ] Partner technology use documented and real
- [ ] Demo video 2–3 minutes, link works when logged out
- [ ] Submitted before **27 October, 23:45 UTC**

---

## 20. Red Flags

Warn or escalate when you hear:

- "We'll add the partner tech at the end"
- "The UI is the main submission"
- "We only tested on my machine"
- "The agents just run one after another"
- "We don't have logs yet" (after day three)
- "You have to set it up manually after cloning"
- "The data has to be downloaded by hand"
- "We committed `.env` but the repo is private"
- "The output is fixed for the demo"
- "Only one of us can run it"
- "We're sharing an API key in the team chat"
- "We need an extension"
- "We're using our company's internal data"

The one to react to fastest is **"only one of us can run it."** That team is one dead laptop away from not submitting.

---

## 21. Language

| Instead of | Say |
|---|---|
| "I'll fix that for you" | "I can help you isolate it and suggest what to check next" |
| "This will pass judging" | "This looks aligned with the requirements, but scoring follows the official process" |
| "Use this exact architecture" | "Planner ↔ executor ↔ evaluator often works. Does it fit your case?" |
| "Send me your key" | "Don't share your key. Confirm the env var is set and post the sanitised error" |
| "Your idea is too hard" | "Given six days, consider narrowing the first version to something that runs reliably" |
| "That's a provider problem, not ours" | "Does a minimal call work outside your framework? If not, their support will be faster than we can be" |

---

## 22. Decision Tree

```text
Security, secrets, or sensitive data?
 └─ Yes → Private escalation immediately.
 └─ No  → Continue.

Provider auth, rate limits, or billing?
 └─ Does a minimal SDK call work outside their framework?
    ├─ No  → Their provider's support.
    └─ Yes → Framework config. You can help.

Partner technology?
 └─ Does the partner quickstart work for them?
    ├─ No  → Partner resource area.
    └─ Yes → Their code. You can help.

Agent design, frameworks, Docker, runtime, logs?
 └─ Yes → You. This is the job.

Submission requirements?
 └─ Yes → Official Rules, then organizers if genuinely ambiguous.

Teams, dates, eligibility, platform?
 └─ Yes → Moderators or organizers.
```

---

## 23. Final Guidance

The best mentoring isn't doing the work. It's helping teams make clear decisions under time pressure.

Keep them focused on:

- **Systems, not prompts**
- **Agents that act and recover, not chains**
- **A real problem and a real user, not novelty**
- **Working prototypes, not slideware**
- **Reproducibility, not "works on my machine"**
- **Traces and evidence, not claims**
- **Sample mode, so a judge without their keys still sees it work**

When in doubt: reinforce the published requirements, stay inside the boundaries, and escalate early.
