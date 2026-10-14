# Meterless "model runtime" — what it actually is

Written 2026-10-14, Alan (researcher). Sources checked directly: `meterless.ai` (home,
`how-it-works.html`, `engines.html`), `github.com/Meterless` (all 8 repos — Swarms, Relay,
Meterless, Gaia, H-MEM, World-Model, Markovian-Engine, genai-agentos), direct PyPI/npm registry
queries, and the two organiser docs named in the task
(`organiser-docs/2026-10-14/strong-submission-examples.md` and `vibe-coding-starter-guide.md`).
No signup, no install, no purchase attempted.

## Short answer

There is no hosted "Meterless API" a Python project can call. The one real product with an
OpenAI-compatible endpoint (**Nightshift**) is an unreleased, Mac/DGX-only, $199 consumer
creative-AI preorder with no hackathon connection anywhere. The three things actually shipping
under github.com/Meterless (Relay, Gaia, Swarms) are desktop-agent products, not model-call
routers. No `meterless` package exists on PyPI or npm — checked both registries directly, not
just search engines. The organiser docs' "Meterless (model runtime)" almost certainly describes
a team's **own adapter code** implementing the open-source engines' documented "injected
generator" pattern — the same thing the HackOS Meterless folder already describes as
implement-yourself — not a separate product you sign up for.

---

## 1. Is there an API, SDK or local server that model calls go through?

**The one real candidate: Nightshift — but it's not available, and has no hackathon tie.**

`meterless.ai`'s actual commercial product is called **Nightshift**: "Turn your computer into an
AI hotspot." Its own integration-details panel, quoted directly from the homepage:

> Nightshift exposes **one OpenAI-compatible base URL and key** on your network, for the text,
> image, video and speech models you have installed, plus any cloud provider you add with your
> own key. Any client that speaks that API can connect.

Example shown on the page: `Base URL http://192.168.1.20:8088/v1`, `Key rt-local` — explicitly
labelled "Illustrative address."

**But Nightshift is not released.** From the preorder panel (`meterless.ai/`, scrolled to the
Mac section), quoted exactly:

> Your Apple Silicon Mac becomes an AI hotspot for your apps and a night shift for your work.
> Your models, your compute. **Preorder now; the download and license arrive when the Mac
> release ships.**
>
> The download link isn't live yet. Come back here when the release is available.
>
> $199.00 USD now, the full price. Nothing more to pay at release.

So today, for any team: there is nothing to download, install, or point a base URL at. It's a
pre-order, not a product.

**No PyPI or npm package exists.** Checked both registries directly (not a search engine):

```text
GET https://pypi.org/pypi/meterless/json          -> 404
GET https://registry.npmjs.org/meterless          -> {"error":"Not found"}
GET https://registry.npmjs.org/@meterless/sdk      -> 404
GET https://registry.npmjs.org/meterless-sdk       -> 404
```

**The open-source "engines" are not a server or SDK either.** `meterless.ai/engines.html` and
`github.com/Meterless/Meterless`'s own README (fetched 6 Oct, re-confirmed today) describe H-MEM,
World Model, Markovian and Scout Intent as **reference architectures and conformance suites you
implement in your own codebase** — cloned via `npx degit meterless/meterless/engines/<name>`,
verified by running `npx tsx conformance/runner.ts` against *your own implementation*. There is
no server to call. This matches the HackOS Meterless folder exactly (`platform-resources/
meterless-*.md`: "not a hosted service... no API key, no Docker").

**What the engines do instead — the "injected generator" pattern.** Every engine takes a
model-calling function *you* supply, rather than calling a model itself (confirmed in the
engine docs read on 6 Oct: `MARKOVIAN_Agent_Engine.md` §12, `H-MEM_Agent_Engine.md` §6). This is
almost certainly what "Meterless (model runtime)... gives us one configuration for local
development and cloud runs" in `strong-submission-examples.md` is describing: **one shared
generator function in your own code, wired once, reused by every agent and engine** — not a
separate Meterless-hosted service. The vibe-coding guide's own phrasing supports this reading
directly: "attach a Meterless prompt file with `@` **if you're using the library**"
(`vibe-coding-starter-guide.md` line 220) — "library," not "service."

**What's actually shipping under github.com/Meterless (Relay, Gaia, Swarms) is unrelated to
model routing.** Checked `github.com/Meterless/Relay`'s README directly: it's "a Tauri + Rust
desktop automation engine" for driving real OS windows on Windows — explicitly "Relay's native
automation layer is Windows-first... Windows for native automation" under Requirements. Its own
README places the other two products in context: "Gaia decides what to do. Swarms thinks in
parallel. Relay executes in reality." None of the three is a model-call gateway.

## 2. Can it route to NVIDIA Nemotron? How is the provider configured?

**Via the open-source engines (the real, accessible path):** yes, trivially — the injected
generator is provider-agnostic by design, so wiring it to NVIDIA's OpenAI-compatible endpoint
(`https://integrate.api.nvidia.com/v1`, per `BRIEF.md`'s own tested record) is exactly the
one-line config change the engine docs describe. This is the same mechanism the vibe-coding
guide's `llm.py` already uses directly with `MODEL_BASE_URL`/`MODEL_API_KEY`/`MODEL_NAME` — there
is no meaningful difference between "call NVIDIA directly" and "call NVIDIA through a Meterless
engine's injected generator," since the engine never touches the network itself.

**Via Nightshift specifically:** partially, and not via NVIDIA's hosted API. Nightshift's own
model catalog (`meterless.ai/models.html`, listed on the homepage) includes four Nemotron
variants — **Nemotron 3.5 Lightning, Nemotron 3 Nano 30B-A3B, Nemotron 3 Super, Nemotron 3
Ultra** — but every one of them is tagged **"Local"** in that catalog, meaning Nightshift runs
them as locally-downloaded model weights on your own machine, not as calls to NVIDIA's hosted
inference API that the hackathon's NVIDIA credits (per `BRIEF.md`) are for. Since Nightshift
itself isn't released, this is moot for the hackathon regardless.

## 3. Does it run on a Raspberry Pi 5 (ARM64)? Or only elsewhere?

**No build exists for Linux/ARM64 at all, and even the closest available platform (Mac) excludes
most Macs.** Quoted directly from the preorder panel's requirements:

> **Supported Macs**: Macs with an **M5 or later** chip: any MacBook Air, MacBook Pro, iMac, Mac
> mini, Mac Studio or Mac Pro with 16 GB or more. macOS 15 Sequoia or later. **M1 to M4 and Intel
> Macs are not supported.**
> **Memory**: 16 GB unified memory minimum; 32 GB or more recommended for larger local models.

The homepage's own platform summary names exactly two hardware targets: "RUNS ON THE **MAC &
DGX EDITIONS**" (DGX = NVIDIA's own DGX Spark workstation hardware) plus a third, separate "FREE
WEB EDITION" (a browser-based hosted demo, not a local server you point a base URL at). No Linux
build, no ARM64-Linux build, no Raspberry Pi mention anywhere on the site, in any repo, or in any
search result. A Raspberry Pi 5 is excluded on every count that matters: it's not a Mac (so the
chip restriction doesn't even apply), and it isn't a DGX Spark.

**The open-source engines, by contrast, run anywhere** — they're plain TypeScript/JavaScript
(the `Meterless/Meterless` repo is TypeScript) executed via `npx tsx`/Node, with no model calls
of their own, so there's no hardware restriction at all. This is the one Meterless-branded thing
that genuinely runs on a Pi 5.

## 4. Hackathon participant access — keys, credits, signup

**Not found.** No mention anywhere checked — not on `meterless.ai`, not in the `github.com/
Meterless` org (8 repos, none referencing a hackathon or participant credit scheme), not in a
targeted web search for "meterless hackathon API key credits" (results returned only the
hackathon's own general sponsor list and unrelated hackathons' credit programs, e.g. Meta's and
Fireworks AI's — nothing Meterless-specific). The organiser's own `.env.example` templates
(`strong-submission-examples.md` line 514, `vibe-coding-starter-guide.md` line 133) both include
a `METERLESS_API_KEY`/`MODEL_API_KEY=your-meterless-or-provider-key-here` placeholder, but neither
document says where that key comes from, and nothing independently confirms a real issuance
process exists. Treat this placeholder as aspirational template text, not confirmed access,
until the Meterless HackOS Help channel says otherwise.

---

## Bottom line for our build

Nothing changes about the plan already in `architecture.md` §5–6: implement the open-source
H-MEM/World Model/Markovian specs ourselves (as already decided), wire NVIDIA Nemotron through
one shared, provider-agnostic generator function, and call our own adapter module
`adapters/meterless.py` if that naming helps match the organisers' example structure — but it
should contain our own generator-wiring code, not a call to any external Meterless service,
because no such accessible service exists. If a real hosted Meterless runtime does surface
before 22 Oct (the HackOS Meterless Resources folder or its Help channel would be the place it'd
appear), re-check this note before committing to the adapter design.
