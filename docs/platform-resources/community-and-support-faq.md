# FAQ

Folder: Community and Support · updated 2026-10-07

# OPEN AGENT HACKATHON 2026 FAQ

**Build an agent that does real work**

Your first stop for questions about the schedule, teams, tracks, the partner stack, submissions, judging and prizes.

> All times are **UTC**. Registration closes **22 October 2026, 23:59** and submissions close **27 October 2026, 23:45**. Where this FAQ and the Official Rules disagree, the Official Rules apply.

---

## Contents

- [1. Event Basics](#1-event-basics)
- [2. Schedule](#2-schedule)
- [3. Eligibility](#3-eligibility)
- [4. Teams](#4-teams)
- [5. Tracks](#5-tracks)
- [6. Models, Providers and Cost](#6-models-providers-and-cost)
- [7. The Partner Stack](#7-the-partner-stack)
- [8. Frameworks and Tech Stack](#8-frameworks-and-tech-stack)
- [9. What Counts as a Strong Agent](#9-what-counts-as-a-strong-agent)
- [10. Data and Licensing](#10-data-and-licensing)
- [11. Technical Requirements](#11-technical-requirements)
- [12. Submission](#12-submission)
- [13. Demo Video](#13-demo-video)
- [14. Judging](#14-judging)
- [15. Prizes and Results](#15-prizes-and-results)
- [16. Support](#16-support)

---

## 1. Event Basics

### What is the Open Agent Hackathon?

A fully online global hackathon where builders create AI agents that do real work: agents that can access relevant information, understand context and relationships, reason across multiple steps, maintain useful context, and turn that understanding into a useful outcome.

It is not a prompt-writing competition and not a UI showcase. The strongest submissions show a working agent, a real problem, a clear user, and evidence of how the system reached its output.

### Who is it for?

Developers, researchers and builders worldwide, from students to senior engineers. You don't need to be an agent expert; you need to be able to ship something that runs.

### Is it online or in person?

Fully online. Everything happens on HackOS.

### How long is it?

144 hours, from 22 October 00:00 to 27 October.

### What do I actually have to do?

1. Register before 22 October
2. Pick one of the four tracks
3. Build a working agent during the build window
4. Submit on HackOS before 27 October, 23:45

---

## 2. Schedule

| Milestone | Date (UTC) |
|---|---|
| Registration opens | 14 August, 00:00 |
| Sponsor workshops | TBA |
| Participant onboarding | 21 October |
| Build window opens | 22 October, 00:00 |
| Registration closes | **22 October, 23:59** |
| Build window | 22–27 October |
| Judging opens | 27 October, 00:00 |
| Submissions close | **27 October, 23:45** |
| Results announced | 6 November, 16:00 |

### What time zone is used?

UTC, everywhere, for everything.

### Why does judging open before submissions close?

So judges can start on the submissions that are already in. It doesn't shorten your build window. Anything submitted before 23:45 on 27 October is judged.

### Are the two deadlines really hard?

Yes. Registration closes at 22 October 23:59 with no late entry, and submissions close at 27 October 23:45. Submit early and update rather than submitting once at the last minute.

---

## 3. Eligibility

### Who can take part?

Anyone aged 16 or older at the start of the build window, anywhere in the world.

### Does it cost anything?

No. Registration, the platform, mentor office hours and submission are free. You pay for any model API you choose to use.

### Can I create more than one account?

No. One account per participant. Duplicate accounts disqualify the whole team.

### Can organizer or sponsor employees take part?

They may participate, but they are not eligible for cash prizes.

### Do I need previous agent-building experience?

No. You need to be able to build something that runs and explain how it works.

### Is there a registration review or approval step?

[TBC: registration is open on hackathon.genai.works. Check the Official Rules for any approval or verification step.]

---

## 4. Teams

### Can I take part alone?

Yes. Teams are 1 to 5 builders.

### Can I register with a team already formed?

Yes.

### Can I find a team after registering?

Yes. Use team-finding on HackOS. Form or join a team before the build window opens.

### What's the maximum team size?

Five.

### Can I be on two teams?

No. One submission per participant.

### Does team size affect the prize?

No. Prizes are split equally among team members by default. If your team wants a different split, agree it in writing **before** you submit.

### Can we change the roster mid-build?

Yes, during the build window. The roster must be accurate at the deadline. After that, changes are only for correcting obvious administrative errors.

### What if the team falls out?

Teams resolve their own internal matters: who does what, how decisions are made, credit, and how a prize is shared. Organizers help with platform and admin problems but don't adjudicate who contributed more. Agree the split on day one.

---

## 5. Tracks

### How many tracks are there?

Four. Pick one and build for it.

| # | Track | What you build |
|---:|---|---|
| 1 | **Fragmented** | Agents that discover and query information scattered across disconnected systems, APIs, databases and data sources, and turn it into actionable insights, decisions, reports or recommendations. |
| 2 | **Autonomous Intelligence** | Agents that investigate complex questions across multiple data sources, connect findings, and produce evidence-backed answers or recommendations. |
| 3 | **Persistent Memory Agents** | Agents that remember previous interactions, maintain state, and continue useful work across longer-running tasks or workflows. |
| 4 | **Real-World Industry Agents** | Agents designed for a specific industry or community, solving a concrete operational problem that could realistically be used in practice. |

Full track statements are on HackOS.

### Can I submit to more than one track?

Pick one track and build for it. [TBC: see section 3 of the Official Rules.]

### Can I change track after starting?

[TBC: see section 3 of the Official Rules.]

### Which track is easiest?

None carries a difficulty rating. How ambitious you are matters far more than which track you pick. A focused solution that runs beats a broad one that doesn't.

### How do I pick?

Match the track to a problem you understand and data you can actually get. If you know an industry, track 4 gives you an unfair advantage. If you have access to several messy systems, track 1 does.

---

## 6. Models, Providers and Cost

### Which models can I use?

Any. Open choice, including closed-source models and paid APIs.

### Is there a mandated provider?

No.

### Who pays for the API calls?

You do, unless a partner provides credits. Two practical consequences:

- **Set a spend alert on day one.** Agent loops multiply token use fast, and an unbounded retry loop can burn a budget overnight.
- **Judges may not have your keys.** Ship a documented sample mode so someone can see the system work without your credentials.

### Can I run models locally?

Yes, but assume a judge has an ordinary CPU machine. If your project needs a GPU to run at all, most judges can't run it.

### How do I keep costs down?

Use a cheaper model for routine steps and the expensive one only where reasoning is hard. Cap agent rounds, cap retries, shorten prompts, cache repeated calls, and develop against sample mode rather than paying to test plumbing.

### Can I use AI coding assistants?

Yes. Cursor, Copilot, Claude Code, chat assistants, autocomplete, all fine. You remain responsible for the code: it must be reviewed, tested and understood by your team. Judges may ask how something works.

---

## 7. The Partner Stack

### What is it?

Four partners so you spend the build window on your solution rather than on infrastructure.

| Layer | Partner | Role |
|---|---|---|
| **Data** | Zetaris | [TBC] |
| **Models** | NVIDIA | [TBC] |
| **Cognition** | Meterless | [TBC] |
| **Coding** | Cursor | [TBC] |

### Is using it mandatory?

No. But **Sponsor Tech is worth 10 points** in the rubric, so a build that uses the stack meaningfully scores where one that ignores it doesn't.

### Do I have to use all three?

No. Use the layers that genuinely help. A partner bolted on at the end with no real role scores close to zero anyway, and judges can tell.

### How do I get access?

[TBC: access instructions are published in each partner's resource area on HackOS.]

### Where do I get help with a partner technology?

The partner's resource area on HackOS first: getting started, docs, tutorial, workshop recording, troubleshooting, FAQs. Then your track room.

### What if a partner service goes down during judging?

Put every partner call behind an adapter with a timeout and a fallback. A project that degrades gracefully still scores; one that crashes doesn't.

---

## 8. Frameworks and Tech Stack

### Which frameworks are allowed?

Any. LangGraph, CrewAI, AutoGen, the OpenAI Agent SDK, LangChain, LlamaIndex, or your own stack.

### Does the framework affect my score?

No. Judges evaluate agent behaviour, technical implementation, product quality and impact. The framework is a means.

### When would I use each?

- **LangGraph** — state-driven workflows, branching, planner/executor/evaluator loops, explicit control over state
- **CrewAI** — role-driven builds with specialist agents and delegation
- **AutoGen** — conversational multi-agent reasoning, debate, iterative refinement
- **OpenAI Agent SDK** — if your team already thinks in those abstractions
- **LangChain / LlamaIndex** — retrieval-heavy, document-heavy work
- **A custom stack** — Python, FastAPI, direct API calls, a trace log and a vector store is often enough and easier to debug at 2am

### Can I build without a framework?

Yes, and plenty of strong submissions do. Fewer moving parts means fewer things breaking on submission day.

---

## 9. What Counts as a Strong Agent

### How many agents do I need?

There's no fixed minimum. What matters is that the system does real work and you can show how. Quality of interaction beats number of agents; three that genuinely collaborate beat six that don't.

### What counts as an agent?

Something with a defined role, a decision boundary, access to context or tools, the ability to produce or transform output, and real interaction with other agents or shared state. Not a prompt with a label.

### What does strong look like?

- Tasks delegated dynamically based on context
- Agents that critique or validate outputs
- Planner ↔ executor ↔ evaluator loops
- Shared memory or context carried across steps
- Branching, retries, escalation
- Recovery from errors
- Traces showing how it got there

### What's weak?

- A fixed chain: A → B → C, no feedback
- Agents that are prompt wrappers
- No critique or validation anywhere
- One agent with several labels
- Hardcoded outputs

### Do I need logs?

Yes, in practice. Logs are how a judge verifies your agent did the work rather than took one long prompt. Add trace logging on day one; retrofitting it on day six is how teams lose Technical points.

### What should a trace line look like?

```json
{
  "timestamp": "2026-10-18T10:15:30Z",
  "agent_name": "ReconcilerAgent",
  "action": "merge_records",
  "input_summary": "Records from 3 supplier sources",
  "output_summary": "Merged 240 records; 3 conflicts unresolved",
  "target_agent": "ConflictCritic",
  "confidence": 0.84,
  "retry_count": 0,
  "status": "success"
}
```

### Can I write the logs by hand?

No. Fabricated traces are a disqualification risk, not a shortcut. A trace that doesn't match the code is worse than no trace.

---

## 10. Data and Licensing

### Can I use external datasets?

Yes: public datasets and public APIs with appropriate licences.

### Can I use private or proprietary data?

No, unless you're authorised to and it's legally permitted. Avoid real personal, clinical, financial or confidential records. When in doubt, use open or synthetic data.

### Is there a size limit on data in the repository?

[TBC: any repository size limit is set by the Official Rules.] Regardless, keep it light. A judge cloning a multi-gigabyte repo is a judge who moves on.

### What are my options?

**Static data in the repo** — small curated samples, sources documented.
**A download script** — fully automated, no login, no manual clicks.
**Runtime public APIs** — with timeouts, retries and a fallback.

### Do I need a sample mode?

Strongly recommended. `SAMPLE_MODE=true` running on cached data with no external calls is what lets a judge without your credentials see the system work.

### Can I use synthetic data?

Yes, especially for sensitive domains. Say so in the README.

### What about regulated domains?

If your use case touches health, finance, law or security, include caveats and safety boundaries. Don't present outputs as a diagnosis, investment advice or legal advice. Cybersecurity builds should focus on detection and response, not exploitation.

---

## 11. Technical Requirements

### What does my submission need to do technically?

[TBC: the requirements are in section 6 of the Official Rules. The guidance below is recommended practice.]

- Runs from a clean clone with a documented command
- Can be driven programmatically, not only through a UI
- Installs dependencies at build or setup time, never during a run
- Runs on a standard CPU machine
- Finishes in minutes, with timeouts and capped loops
- Loads secrets from environment variables
- Writes logs to stdout and `logs/`

### Is Docker required?

[TBC.] It's the most reliable way to make sure a judge gets the same result you do, and it's strongly recommended either way.

### Can I include a UI?

Yes, and Product & UX is worth 10 points. But give judges a way to run the agent without clicking through screens. A polished interface over a weak system scores badly.

### Is there a time limit per run?

[TBC.] Even without one, a run that takes an hour is hard to demo, hard to judge and more likely to fail. Aim for 5 to 10 minutes.

### Can dependencies install at runtime?

No. Install at build time.

### What should happen when something fails?

Fail gracefully: timeouts, capped retries with backoff, fallback to sample data, a clear error, and logs showing the failure and the recovery. Robustness is part of the Technical score.

---

## 12. Submission

### Where do I submit?

On HackOS, before 27 October, 23:45 UTC.

### What do I submit?

[TBC: see section 6 of the Official Rules.] At minimum, prepare:

| Component | Why |
|---|---|
| Repository | The working project, accessible to judges |
| README | Setup, run instructions, architecture, limitations |
| Demo video | 2–3 minutes showing the agent running |
| Logs or traces | Evidence of how the agent worked |
| Sample inputs and outputs | At least three of each |
| Partner technology record | What you used and where |

### Can I update my submission?

Yes, up to the deadline.

### Can I submit a notebook?

A notebook is fine as explanation, but the project needs to run as a system, not only as cells someone steps through.

### Can I submit a UI-only project?

It would be hard to judge. Give judges something they can run.

### Can I hardcode the demo output?

No. Hardcoded outputs are a disqualification risk. The default mode must run real agent logic.

### What are the most common ways teams lose points?

A judge can't run it, the traces don't exist, the README claims more than the code does, secrets are committed, the partner tech is decorative, or the project only works on the author's laptop.

---

## 13. Demo Video

### Is it required?

Yes, and Demo is worth **15 points**.

### How long?

2 to 3 minutes.

### What should it cover?

| Segment | Time | Show |
|---|---:|---|
| Problem | 15–25s | What you're solving and for whom |
| Solution | 20–30s | What your agent does |
| Agents | 30–45s | The roles and how they interact |
| Live run | 45–60s | The system actually running |
| Output | 30–45s | The result, and why it's useful |
| Value | 15–25s | Who benefits |

### Does it have to be live?

No, recorded is fine.

### Can I use sample data?

Yes, label it clearly.

### Should I focus on the interface?

No. Show the agent working. A video of only slides doesn't demonstrate a working system, and a video of only screens doesn't demonstrate an agent.

---

## 14. Judging

### How does it work?

Expert judges review submissions against the published criteria. Judging opens 27 October, 00:00 and runs while final submissions come in.

### What's the scoring?

| Criterion | Points | What judges look for |
|---|---:|---|
| **Impact** | 30 | A real problem, a clear user, an output that improves a decision or workflow |
| **Technical** | 20 | A functional working system, effective use of tools, APIs, models and data |
| **Innovation** | 15 | Novel approach, creative use of agent design patterns |
| **Demo** | 15 | Clarity of explanation and quality of the demonstration |
| **Product & UX** | 10 | Whether the output is usable by the person it's meant for |
| **Sponsor Tech** | 10 | Meaningful use of the partner stack where it helps |
| **Total** | **100** | |

### What happens in a tie?

Ties for third place are decided on the **Impact** score.

### What do judges reward?

Agents that act rather than describe, a clear problem and user, critique and recovery instead of a fixed pipeline, reliable execution, partner tech that's load-bearing, an output someone could actually use, and a demo that explains itself.

### What do they discount?

UI polish without depth, single-agent systems presented as more, hardcoded demo paths, broad concepts with weak implementation, and overclaiming.

### Will judges test with their own inputs?

Possibly. Your project should handle reasonable unseen inputs for your track, not just the three you shipped.

### Do I get feedback?

[TBC: see the Official Rules.]

### Are decisions final?

Yes, on eligibility, disqualification, scoring and winner selection.

---

## 15. Prizes and Results

### What's the prize?

A prize pool of **up to $20,000** across the winning submissions, with a feature in the community showcase for the top project.

### How is a team prize split?

Equally among team members by default.

### Does team size change the prize?

No.

### When are winners announced?

6 November, 16:00 UTC, on the live results call on HackOS.

### How and when do prizes get paid?

[TBC: payment method, timeline and any identity or tax documentation required.]

### Who owns what I built?

[TBC: see section 9 of the Official Rules for the IP terms.]

### Is there an incubation or deployment pathway?

No formal pathway runs after this event. What continues is the community: the showcase, future hackathons and workshops on Discord.

---

## 16. Support

### Where do I ask questions?

Everything during the event is on HackOS.

| Need | Where |
|---|---|
| Track scope and expectations | Your track room |
| Partner setup and errors | Partner resource area, then your track room |
| Agent design, frameworks, debugging | Mentor office hours |
| Submission requirements | Official Rules on the event page |
| Finding teammates | Team-finding |
| Official updates | Announcements, check daily |
| Your model provider's errors | Your provider's own support |

### What is Discord for?

Community activity after the hackathon: showcases, future events, workshops, staying in touch.

### What do mentors do?

They help you understand the tracks, navigate HackOS and the partner technologies, answer technical and use-case questions, and get you unstuck. They don't build your project, and they can't debug your provider account for you.

### How do I get a fast answer?

Include: what you're trying to do, what you expected, what happened, the exact error, your framework and provider, whether it fails locally or in Docker, and what you already tried. That last one saves the most time.

Good:

> "LangGraph with [provider]. Works locally, fails in Docker with a 401. Key is passed as an environment variable and a minimal SDK call works. Sanitised error below. Any ideas?"

Not useful:

> "Nothing works. Please fix."

### What if my provider key doesn't work?

1. Check the environment variable actually reaches the process, in Docker as well as locally
2. Check the base URL character by character
3. Run a minimal SDK call outside your framework

If the minimal call works and your framework doesn't, that's a configuration problem and mentors can help. If the minimal call fails too, it's your provider's support.

### What if I accidentally commit a key?

**Rotate it immediately.** Then remove it from the repository and tell a moderator. Deleting the commit is not enough on its own.

### What if my issue is sensitive?

Exposed credentials, personal data, a security concern or a safety issue: don't post details publicly. Ask for a private route and rotate anything exposed while you wait.

### Final checklist before submitting

- [ ] Picked one track and built for it
- [ ] Runs from a clean clone with a documented command
- [ ] A judge can drive it without your UI
- [ ] `.env.example` present, no real keys
- [ ] Sample mode works with no credentials
- [ ] At least 3 sample inputs and matching outputs
- [ ] Logs show real agent interaction
- [ ] No secrets committed anywhere
- [ ] README covers setup, architecture and limitations
- [ ] Partner technology use documented
- [ ] Demo video 2–3 minutes, link works
- [ ] Submitted before 27 October, 23:45 UTC

---

## Final Reminder

| Focus on | Avoid |
|---|---|
| Systems | Prompt-only demos |
| Agents that act and recover | Fixed chains |
| A real problem and a real user | Novelty without usefulness |
| Working execution | Slides without code |
| Partner tech that earns its place | Decorative integrations |
| Honest logs | Unverifiable claims |
| Reproducibility | "Works on my machine" |

Build something that runs, explains itself, recovers when something breaks, and hands back something useful.
