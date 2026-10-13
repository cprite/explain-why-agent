# Data Day workshop (Zetaris), 12 October 2026 — notes

Source: the organisers' recording on HackOS (46 minutes), read from its English auto-captions, saved
next to this file as `data-day-zetaris-2026-10-12.transcript.txt`. The captions are machine-made and
garble names ("Zotaris", "the Taurus"), so product details below should be confirmed against Zetaris's
own material before they are relied on. Speakers: Samuel Cummings (GenAI Works) and Michael, CTO of
Zetaris. Bright Data did not present in this recording.

## What Zetaris is, as presented

- A SQL query engine that federates across data sources, with a graphical interface. The pitch is
  "zero copy": it attaches to data where it lives and serves it to agents.
- You program it in ANSI SQL with Zetaris extensions. With SQL you attach sources: a REST API, a
  Postgres instance over JDBC, a Kafka stream, a PDF. Plain CSV files were not mentioned.
- On top of the sources you define a **Unified Semantic Layer (USL)**: a named model of tables and
  relationships written in DDL and bound to the sources through SQL queries. Once activated it is
  queried like a database with ordinary SQL. This is what they recommend agents consume.
- Clients connect over **JDBC (preferred) or a REST API**. The agent runs separately, in whatever
  framework, and talks to the USL through one of those.

## What participants get

- A "free forever" distribution in two flavours:
  1. **On AWS**, sized to fit the AWS free tier (about 4 vCPU, 8 GB). It needs an AWS free-tier
     account, which gives up to $200 in credits and a time limit, whichever runs out first.
  2. **A Docker image to run locally**: about 4–5 cores, 8 GB of memory, 15 GB of storage, on Linux,
     macOS or Windows, with Docker Desktop. On macOS "make sure Rosetta is" enabled, which suggests
     the image is built for x86 processors.
- Install path: "Start free" on the Zetaris site → sign in (Microsoft single sign-on or email) →
  dashboard → download a package generated for you → sign in to their container registry → unzip →
  run the verify script inside the install folder → open `localhost:3000`. Credentials are on the
  download page; change the password.
- First query: the getting-started repository has an onboarding guide that adds a REST source (a
  Pokémon API) and queries it as a SQL table.
- A GitHub getting-started repository (Apache licence) with example open data sources, worked
  examples, and connection guides for Cursor, Codex, Claude Code and SQL tools; a GitHub page with a
  "core prompt" for coding tools; a YouTube channel with three videos (repository walkthrough, first
  data source, building a USL with a coding tool).
- Support: a Zetaris help channel on HackOS, staffed through the build.

## What the organisers said about the event

- **The challenge statements are not announced yet.** In answer to a question: "The actual challenge
  statements are not announced. Those are going to be announced on the day of." The tracks are the
  frame; a concrete problem statement comes at kickoff. His example: the track is reasoning
  architecture, the statement is "make better predictions on bank statements and when companies should
  invest".
- Advice on preparation: spend roughly 40% on learning Zetaris, 40% on learning Meterless and 20% on
  the use case. He warned against "over-baking an idea or building out a solution already" and said
  that existing work belongs in the Tinkerer track.
- "Get your Zetaris instance up and running" was named as the first thing to do now.
- More technical sessions before kickoff, "between now and the 20th"; he mentioned the 15th, 19th and
  20th without assigning sessions to them. Build Day is with Cursor, Power Day with NVIDIA.
- NVIDIA will offer "a surprise win opportunity".
- Every participant needs a team on HackOS, including solo builders, because submissions and judging
  run through teams. A help agent is built into HackOS.
- Kickoff is 22 October; the sprint runs to Tuesday 27 October.

## Consequences for our plan

1. **Zetaris has to run somewhere we control.** There is no hosted instance handed to us. The local
   image needs about 8 GB and probably an x86 processor, so the Raspberry Pi that runs the build
   agents is unlikely to host it. Candidates: Nikolay's Mac with Docker Desktop, an x86 machine on the
   home network, or the AWS free tier.
2. **Our four sources should be databases, not files.** The natural fit is four small Postgres
   databases, one per source system, registered in Zetaris over JDBC, with a USL across them. This
   answers the open question "how does the data reach Zetaris".
3. **Judges will not have our Zetaris instance.** Sample mode on the local adapter is therefore the
   path a judge actually runs; the Zetaris path is shown in the video, the logs and a recorded query
   log. The README must say this plainly.
4. **The use case may be redirected at kickoff.** If a specific challenge statement is given for
   Track 02, the investigation engine (planner, investigator, critic, evidence record) carries over;
   the data, the questions and the answer key may not. Keep the engine independent of the Olist
   schema, and do not treat the Olist scenario as fixed until the statements are published.
5. **Do not over-prepare.** The organisers are explicit that a pre-built solution belongs in the
   Tinkerer track. Everything prepared so far is plans, research and one data sample, all declared.
   No project code exists and none should before the window opens.
