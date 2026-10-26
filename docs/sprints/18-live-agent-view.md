# Sprint 18 — Agents at work: the live trace on the web page

UI only: `web/app.js`, `web/index.html`, `web/style.css`, their checks (`tests/web/render_check.js`,
`eval/browser_check.py`) and the README. No agent, prompt, schema, API or cache change, so every
recorded reply still replays and the scores do not move.

## What it does

The page now picks the run id itself, starts the run with `POST /run`, and while the run goes it
polls `GET /runs/{id}/trace` every two seconds (the endpoint already served the trace during a run).
`readTrace()` turns the trace events into a picture of the team at work:

- **Team strip**: Orchestrator, Planner, Investigator, Data, World Model, Critic, Reporter. The agent
  working now pulses; agents that have taken part are marked.
- **"Investigator is working… 1:20"**: who has the task and for how long, so a live Nemotron call of
  several minutes no longer looks like a frozen page.
- **Hypothesis board**: H1…H4 from the plan, each moving from untested to testing to the Critic's
  verdict (supported, refuted, not enough evidence).
- **Hand-off feed**: Planner → Investigator ("Test H1 logistics_delay: …"), Investigator → Data
  (the SQL, folded), Data → Investigator (rows back), Investigator → World Model (the finding),
  Critic → Orchestrator (verdict and reason), Reporter → Orchestrator (the answer). Every model call
  is a quieter line with its Nemotron route, time and tokens; failed calls (timeout, offline) show
  in red.
- **After the run** the panel stays below the answer as "How the agents worked it out", with a
  **Replay step by step** button that plays the hand-offs again (useful for sample mode, where the
  run takes seconds, and for the demo video).

All data reaches the page as text (no markup from strings), and the page still fetches through the
one `requestJson` helper (it now also reads text, for the NDJSON trace).

## Tests

- `tests/web/render_check.js`: two new checks — a trace reads as hand-offs (active agent, hypothesis
  states, verdict, failed call, query count), and the live view renders the team, the working
  agent with its clock, the SQL, and markup from the trace as text.
- `eval/browser_check.py` (CI, headless Chromium): after the Day 1 question, the panel has at least
  five steps, a hypothesis and a Replay button; Replay shows an active agent and finishes.
