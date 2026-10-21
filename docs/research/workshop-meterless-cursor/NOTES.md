# Workshop: "BUILD with Meterless and Cursor (Session 2, APAC)" — notes

YouTube lj32MxNWFWI (GenAI Works, 64 min, uploaded 19 Oct 2026). YouTube had no captions;
`transcript.txt` is a local faster-whisper small.en transcription — names may be slightly off.
Speakers: Samuel Cummings (GenAI Works, VP AI Engineering), Michael (Cursor technical partnerships, Singapore).
Format: mostly a recorded clip session ("7–8 clips syndicated during the event"), not a Q&A.
**No Meterless setup details** (no base URL, keys, credits or model IDs) — those stay open.

## What matters for our build
1. **Meterless must be a provider inside the product** — "as a core part of your solution you will need to add
   Meterless as a provider inside of your product", also the condition for the DGX Spark prize [60:41].
   Nightshift is pitched as the "AI hotspot" that powers the app; serves text, video, transcription, 3D.
2. **Sam's playbook** [15:00–18:20]:
   - Get an end-to-end loop working first (aim: day 2–3), not plan-everything-up-front.
   - Then hand the working product to the agent: "run it a hundred times", benchmark, self-optimise, fix.
   - Last step: have the agent run the whole product, take screenshots and build an interactive
     demo/landing page for the submission. Prompt guides: HackOS Resources + meterless.ai.
3. **Cursor = rebranded "GrokBuild"** (now in the SpaceX AI portfolio); same product, names interchangeable.
   Any model is allowed (auto router can optimise for intelligence / balance / cost; own models Composer
   and Grok 4.7; Anthropic and Google also listed).

## Cursor features shown (Michael's demo, 27:17–58:50)
- Docs: cursor.com/docs. Cloud agents run 24/7 (laptop can close); Bugbot (finds bugs), security agents;
  "Origin" = Cursor's own git forge; SDK, CLI, and a "BDK" (bot development kit, API to bots).
- **Projects**: groups agents, activity list, a review/queued board, and a library (the repo).
- **Multitask** mode: give several tasks at once, they run in parallel threads.
- Slash commands: `/plan` (writes a plan file, no code), summarise, set a **goal** pursued to completion, bugbot review.
- **GrokBot** (for "knowledge workers"): chat-app bots in the cloud, each with its own computer (desktop,
  terminal, Chrome; you can take control), routines on schedules, MCP connectors (Slack, Calendar, Drive,
  Figma, Vercel…), same login as Cursor. Bots can open PRs in Cursor (his "Travel Historian" bot mines
  email and opens data PRs). Suggested first bot: a DocsBot that answers questions from cursor.com/docs;
  "Dr. Eggbot" is a bot that creates bots. Pattern: one "Big Boss" bot as single point of contact delegating to workers.
