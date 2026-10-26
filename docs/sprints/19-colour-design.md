# Sprint 19 — Colour design

UI only: `web/style.css`, small class additions in `web/app.js` and `web/index.html`, and
`eval/ui_screenshots.py` (review screenshots). No agent, prompt, schema, API or cache change.

- **Colour with meaning.** Each agent has one colour (Planner purple, Investigator blue, Data teal,
  World Model cyan, Critic amber, Reporter green, Orchestrator slate), used in the team strip, the
  hand-off feed and the "working" line. Rises are green, falls red; the Critic's verdicts use the
  same scheme (supported green, refuted red, not enough evidence amber).
- **Header**: a gradient band with the product name and what the agents do.
- **Answer**: the change as a headline ("0.031 → 0.132 +330%"); the top cause as a highlighted card
  with a confidence ring; ruled-out explanations as red ✘ cards; limitations in a soft yellow box.
- **Anomaly cards**: a rise/fall stripe and the change in a coloured chip.
- **Dark theme**: follows the system setting (`prefers-color-scheme`), one set of colour tokens.
- **Replay** slides in only the new hand-offs (no flicker on every redraw).

`eval/ui_screenshots.py` drives the page in headless Chromium against the Nemotron recordings and
saves the board, the live panel half-way through a replay, the finished panel and the answer, in the
light and the dark theme (`UI_SHOTS_URL`, `UI_SHOTS_DIR`, `UI_SHOTS_CHROMIUM` for a system Chromium).
