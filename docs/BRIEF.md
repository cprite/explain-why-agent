# Open Agent Hackathon 2026 — working brief

Single source of truth for agents helping Nikolay. Built from the organisers' documents in
`organiser-docs/` (received 2026-10-06). If this file and those documents disagree, the documents win.
Coordination: Nikolay talks to Claude Code; Claude Code posts tasks to agents in Discord through Niclaw's bot.

## Rules that shape the build

- **Required in every submission:** Zetaris and Meterless integrated; Cursor used for development.
  NVIDIA is used wherever it contributes. Sponsor Tech is 10 of 100 points.
- **No early commits:** work committed before 15 Oct 00:00 UTC is not eligible, except clearly
  declared pre-existing components (prepared data counts and must be declared).
- **One primary track** per submission; it can be changed until the deadline.
- **Data:** open, legally usable, no real personal data, small samples in the repo, a
  `SAMPLE_MODE=true` fallback so it runs when an external service is down.
- **Secrets:** environment variables only, `.env.example` with placeholders.
- **Where things happen:** HackOS (announcements, sponsor Resources folders, #help desk, mentor office
  hours, submission, results call). Rules questions: hackathons@genai.works. Discord is community only.

## What the sponsor technologies actually are (from HackOS Resources, read 2026-10-06)

- **Meterless** — not a hosted service. Three reference architectures you implement yourself: H-MEM
  (shared memory), Markovian (bounded-context long-task reasoning), World Model (shared entities and
  provenance). No API key, no Docker. For an investigation agent the docs suggest Markovian for the
  long investigation and World Model for the evidence trail. Files: `platform-resources/meterless-*.md`.
  Source and template prompts: https://github.com/Meterless/Meterless, https://meterless.ai/engines.html
- **Zetaris** — a free instance per participant plus Markdown docs; access details not yet published.
- **NVIDIA** — credits for Nemotron models through API keys; how to claim them not yet published.
- **Cursor** — access for each team during the hackathon; how to get it not yet published.
- The README and a `metadata.json` in the repo must say which sponsor technologies were used and where.

## Technical expectations (recommended practice in `platform-resources/rules-and-requirements-technical-execution-requirements.md`)

`run.py` entry point and a JSON-in/JSON-out run endpoint, not only a UI · Dockerfile, CPU only, no
installs at run time · full run in 5–10 minutes with timeouts and capped loops · `SAMPLE_MODE=true`
that works with no network · traces as JSONL in `logs/` and on stdout showing handoffs, critique,
retries · at least three sample inputs with outputs · no hardcoded outputs or hand-written logs.

## Known conflict in the organisers' material

The older "Official Rules" copy on HackOS (updated 30 Sep) says the partner stack is not mandatory and
lists four differently named tracks. The newer Start-here documents (1 Oct) say Zetaris, Meterless and
Cursor are required and list three tracks plus Wildcard. Plan as if required until the organisers say
otherwise. All 32 platform documents are in `platform-resources/`.

## Dates (UTC → London)

| What | UTC | London |
|---|---|---|
| NVIDIA + Meterless workshop | 8 Oct 22:00 | 8 Oct 23:00 |
| Zetaris + Cursor workshop | 12 Oct 22:00 | 12 Oct 23:00 |
| Registration closes | 13 Oct 00:00 | 13 Oct 01:00 |
| Participant onboarding | 14 Oct 16:00–17:30 | 14 Oct 17:00–18:30 |
| Build window opens | 15 Oct 00:00 | 15 Oct 01:00 |
| Submissions close (hard) | 20 Oct 23:45 | 21 Oct 00:45 |
| Results call | 30 Oct 16:00 | 30 Oct 16:00 |

## Submission (on HackOS)

Demo video 1–4 min · slide deck · GitHub repo with README (setup, usage, dependencies) · sponsor
technology explanation (how Zetaris and Meterless were integrated, how Cursor was used, where NVIDIA
contributes) · declaration of pre-existing components. Judges also look for logs or traces, sample
inputs and outputs, and a repo that runs from a clean setup. At least three judges per submission.

## Scoring

Impact 30 · Technical 20 · Innovation 15 · Demo 15 · Product & UX 10 · Sponsor Tech 10.
Rewarded: agents that critique, retry, branch and recover; traceable evidence; reliable runs.
Discounted: linear pipelines, single agents dressed up as several, hardcoded demo paths, UI polish
without depth, sponsor technology bolted on at the end.

## Project (working idea, Nikolay's choice on 2026-10-05)

Track 02, "The Agent That Can Explain Why". A business asks "why did this number change?"; the agent
investigates across separate data sources and returns ranked causes, each tied to its evidence, plus
what it ruled out. Data: the public Olist e-commerce dataset (CC BY-NC-SA 4.0) as a small sample,
with injected incidents as an answer key. Solo build. Not final until the sponsor workshops show what
Zetaris and Meterless can do.

## Channels (category OPEN-AGENT-HACKATHON)

`alerts` date reminders · `hq` decisions and status · `intel` research · `build` task runner posts ·
`scorecard` rubric scores.

## Task board (HackOS)

The team's progress is tracked on the HackOS task board, which Nikolay sees at
https://hackathon.genai.works/board?hackathon_id=019fd164-82b9-7382-a536-d9093c576ed2.
Read and update it only through `hackos_board.py` in this folder:

    ./hackos_board.py list
    ./hackos_board.py move "<title>" todo|in_progress|blocked|done
    ./hackos_board.py comment "<title>" "<what changed, with evidence>"
    ./hackos_board.py add "<title>" --priority high|medium|low

Move a task only when its state really changed, and leave a comment saying why. Never mark something
done that Nikolay has to confirm. The board is the only part of HackOS agents may change.

## Cursor on this machine

Cursor's command-line agent runs unattended here (verified 2026-10-06). Login tokens are in
`~/.openclaw/credentials/cursor-auth.json`. Run it as:

    CURSOR_AUTH_TOKEN=$(python3 -c "import json;print(json.load(open('/home/pi/.openclaw/credentials/cursor-auth.json'))['accessToken'])") \
      cursor-agent -p --force --trust --output-format text --workspace <repo dir> "<task>"

Do not point it at the project repo before 15 Oct 00:00 UTC.

## Repository

`https://github.com/cprite/explain-why-agent` — private. On 2026-10-06 Nikolay decided that all
supporting documents and plans live in the repo under `docs/`; they are declared as pre-existing in
`docs/PRE-EXISTING.md`. No project code, data or configuration is committed before 15 Oct 00:00 UTC.
Local working copy: `/home/pi/.openclaw/workspace/projects/open-agent-hackathon/explain-why-agent/`.
Commits are authored as Nikolay <3dutka@gmail.com> with no mention of AI tools in commit messages or
pull requests. The repo has to be made accessible to judges before submission; `docs/organiser-docs/`
and `docs/platform-resources/` are the organisers' own material and should be removed or cleared with
them before the repo is made public.

## NVIDIA model access (tested 2026-10-06)

Nikolay's personal key is in `~/.openclaw/credentials/nvidia.env` (`NVIDIA_API_KEY`). Endpoint:
`https://integrate.api.nvidia.com/v1`, OpenAI-compatible. Test call, one small JSON task:

| Model | Result |
|---|---|
| `nvidia/nemotron-3-super-120b-a12b` | 1.9 s, valid JSON — first choice for the agents |
| `nvidia/nemotron-3-ultra-550b-a55b` | 3.3 s, valid JSON — candidate for the critic |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | 5.0 s, spent its token budget on reasoning text, no JSON |
| `nemotron-4-340b-instruct`, `nemotron-nano-3-30b-a3b`, the `llama-3.1-nemotron` models | listed by the API but return 404 for this account |

The models return a separate `reasoning_content` field; parse `content` only. Free-tier limits were not
measured. Hackathon credits are separate and not yet published.
