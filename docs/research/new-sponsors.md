# New sponsors — Bright Data and Space XAI

Written 2026-10-07, Alan (researcher). Covers: what each sponsor actually offers, whether either
earns a place in the build, and what's changed on the public hackathon pages since 7 Oct.

---

## 1. Bright Data

### What it offers developers

Bright Data is a web-data infrastructure company. Relevant developer-facing products:

- **Web Unlocker API** — fetch any public page, auto-bypassing bot detection/CAPTCHAs/rate limits.
- **SERP API** — structured search results from Google, Bing, Yandex.
- **Web Scraper API** — 60+ pre-built, maintained scrapers for major sites (Amazon, LinkedIn, etc).
- **Scraper Studio** — build custom scrapers in a cloud IDE, 1 credit/page load.
- **Browser API** — Puppeteer/Playwright/Selenium on their cloud browsers, unblocking built in.
- **MCP server** — `brightdata-mcp` (MIT, 2.7k★ on GitHub), exposes **69 tools** over Model Context
  Protocol: `search_engine` (web search), `scrape_as_markdown` (any URL → clean Markdown),
  `discover` (AI-ranked relevant sources for a research question), `extract` (structured JSON from
  any page, no schema needed), batch variants (`search_engine_batch`, `scrape_batch`, 10 at a time),
  plus per-site structured extractors and 13 interactive-browser tools.
  Source: <https://github.com/brightdata/brightdata-mcp>

### Free tier / calling pattern

- **5,000 free credits/month**, no card, renews on the 1st, shared pool across Web Unlocker, SERP,
  Web Scraper, Scraper Studio and Browser API (Browser API costs 5 credits/MB). MCP requests draw
  from the same pool (so also effectively 5,000 free MCP requests/month).
  Source: <https://docs.brightdata.com/general/account/billing-and-pricing/free-tier>
- **Call pattern:** hosted MCP endpoint, no install — `https://mcp.brightdata.com/mcp?token=<token>`
  — or `npx @brightdata/mcp` locally with `API_TOKEN` env var. Add as an MCP server to Cursor,
  Claude Code, etc. (config snippets for each client in the README). This means the Investigator
  agent could call it as an ordinary tool, same shape as any other MCP tool in the stack.
- **Limits beyond free tier:** PAYG $1.50/1,000 results (search/scrape/extract), $8/GB (browser
  navigation). Free/unfunded accounts are rate-limited to 1,000 requests/minute. A hackathon demo
  using a handful of search calls across 3 example questions is trivially inside the free tier —
  cost/limits are a non-issue here.
  Source: <https://github.com/brightdata/brightdata-mcp>, <https://brightdata.com/pricing/mcp-server>

### Judging the proposed idea (web search for external events the internal data can't explain)

**Would it work well for 2017–2018 Brazil events?** Yes, for the real ones. Bright Data searches
and reads the *current* live web, not a historical archive — but that's fine here, because
retrospective documentation of real 2017–2018 events still exists online today. Checked directly:
the 21 May–1 Jun 2018 Brazilian truck drivers' strike has extensive, easy-to-find coverage —
Portuguese and English Wikipedia (`pt.wikipedia.org/wiki/Greve_dos_caminhoneiros_no_Brasil_em_2018`,
`en.wikipedia.org/wiki/2018_Brazil_truck_drivers'_strike`), Brazilian news archives (Globo, Veja).
Black Friday is a globally known recurring date, trivially findable. A `search_engine` call for
something like `"greve caminhoneiros" Brasil maio 2018` or `"Black Friday" Brasil 2017 varejo` would
return these directly; `scrape_as_markdown` on the top hit gives a clean, citable summary.

**What the calls would look like** (conceptually, for the Critic testing the "external cause"
hypothesis family already in `architecture.md` §4):
```
search_engine("Brazil [metric/sector] events " + window_start + " to " + window_end)
  -> ranked results
scrape_as_markdown(top_result_url)
  -> page text, used as a citation, never as a number
```

**The risk to incidents 9 and 10 is real and specific, not hypothetical.** A general web search
essentially always returns *something* for any date range and country — the question is whether the
system is built to resist treating "found something" as "found the cause":
- **Incident 9** (tiny seller, n=3, genuinely no cause anywhere) is a *small-sample* problem, not a
  *broad unexplained change*. A web search here is categorically the wrong tool — there's nothing
  about this seller's 3 reviews that a web search could legitimately corroborate, but a naive
  implementation that fires a web search whenever `determinable` trends false would very likely
  surface *some* plausible-sounding December 2017 news and misattribute it.
- **Incident 10** (macro AOV drift, Aug–Oct 2017, broad and diffuse) is exactly the shape the
  proposed feature is designed to trigger on. Brazil had real macroeconomic/political news in that
  window (inflation, exchange-rate moves, the ongoing pension-reform debate under Temer) that a
  search could easily surface as a superficially plausible story — converting a correctly
  indeterminate answer into an unverifiable guess.

**Mitigation, if this is built:** don't gate the search on "we couldn't find a cause" (true for both
9 and 10) — gate it on the specific, already-planned condition: a *confirmed broad, multi-segment*
anomaly with every internal hypothesis exhausted (this is incident 10's signature, not incident 9's —
9 fails on sample size, which a web search can't fix or even address). Write any finding to a
separate field (e.g. `external_context`, not `causes`), explicitly marked unverified/uncorroborated,
and never let it flip `determinable` to `true` or appear in `ruled_out`'s place. `eval/run_eval.py`
already only checks `causes`, `ruled_out` and `determinable` (§9 of `architecture.md`) — as long as
the external-search output never writes to those three fields, the eval can't be fooled by it even
if the feature is built. That's a cheap, concrete guardrail, not just a design intention.

**Verdict: earns a place, narrowly.** Not as a new agent or a required integration — as one
additional tool the existing Critic already needs for the "external cause not present in the data"
hypothesis family in §4 of `architecture.md`. It's a good fit for testing (and often *disproving*)
that hypothesis for incidents 1 and 2, where it would find real corroborating public record. For 9
and 10 it should be either not triggered at all (9) or used only to positively confirm *absence* of
a clean external story, written to a side channel that cannot touch the scored fields (10).

---

## 2. Space XAI

### What it actually is (not what the name suggests)

"Space XAI" is **SpaceXAI** — SpaceX's AI division (the rebranded former **xAI**, maker of Grok).
This is not a niche conference sponsor; it's confirmed via mainstream coverage:

- April 2026: SpaceX and Cursor announced a partnership, with SpaceX given an option to acquire
  Cursor for $60B (or pay $10B for the collaboration), explicitly "to accelerate our model training
  efforts." Source: <https://www.cnbc.com/2026/04/21/spacex-says-it-can-buy-cursor-later-this-year-for-60-billion-or-pay-10-billion-for-our-work-together.html>
- 8 Jul 2026: SpaceXAI and Cursor released **Grok 4.5**, their first jointly-trained model, "built to
  excel at coding, agentic tasks, and knowledge work." Source: <https://x.ai/news/grok-4-5>
- 12 Aug 2026: **Grok 4.6** released, aimed at "complex coding, knowledge work, and long-running
  agent tasks."
- 14 Aug 2026: SpaceX **completed its acquisition of Cursor**. Source: <https://cursor.com/blog/joining-spacex>

So "Space XAI (with Cursor)" as a joint sponsor listing makes sense literally: they are now the same
corporate structure. This is also consistent with what's live on the hackathon page today (checked
directly) — the sponsor logo row shows **NVIDIA, Zetaris, SpaceX AI, Meterless**, with no separate
Cursor logo; Cursor's requirement is stated independently in the rules text, not as a sponsor tile.

### What it provides, and how it relates to Cursor here

- **Models:** Grok 4.5 / Grok 4.6, trained jointly with Cursor, available inside Cursor's model
  picker (reported to sit "alongside Composer 2.5" as a different weight class) **and** via a
  standalone API.
- **API:** `docs.x.ai` / the SpaceXAI developer console. **Confirmed OpenAI SDK-compatible** — swap
  `base_url` to `https://api.x.ai/v1` and an API key, use the standard `openai` Python client
  unchanged. Source: <https://docs.x.ai/developers/model-capabilities/legacy/chat-completions>,
  corroborated independently on Stack Overflow and Cloudflare's AI Gateway docs.
- **Pricing (standard, not hackathon-specific):** Grok 4.5/4.7 flagship: **$2/million input tokens,
  $6/million output tokens** (cached input $0.50/M). Long-context (>200K tokens) rates differ
  ($4 in / $12 out). Source: <https://x.ai/api>, <https://docs.x.ai/developers/pricing>.
- **Relation to Cursor in this hackathon:** since Cursor use is already mandatory for development,
  and Grok models are reportedly available inside Cursor's own model picker, the practical read is
  that Space XAI's contribution *for coding* may already be covered by "use Cursor" — it likely adds
  a specific, jointly-optimized coding model option inside the tool teams must use anyway, not a
  separate mandatory integration.

### Does it replace or sit beside NVIDIA?

**Beside, architecturally — and it's a clean fit.** `architecture.md` §6 already plans exactly this
seam: "one injected generator function, OpenAI-compatible... Default: NVIDIA Nemotron... Fallback: a
second OpenAI-compatible provider set by environment variable." Grok's confirmed OpenAI compatibility
means it could be that fallback slot (or the primary, if NVIDIA credits turn out limited) with a
one-line config change — no code change. There's no indication anywhere that Space XAI is meant to
*replace* NVIDIA for this hackathon; both are listed as separate sponsor logos on the live page.

### What could not be confirmed

- **Hackathon-specific Grok/SpaceXAI credits or API keys for participants.** Nothing found — same
  "not yet published" situation as NVIDIA's Nemotron credits per `BRIEF.md`. All pricing above is
  SpaceXAI's standard public pricing, not a hackathon allowance.
- **Whether Grok access through this hackathon is "through Cursor's quota" or "a separate API key."**
  Not stated anywhere I found.
- **Whether Space XAI/Grok is a *required* technology** ("integrate wherever it contributes," like
  NVIDIA) **or just available.** The live Official Rules page (checked directly, §5.1–5.2) still
  only names Zetaris, Meterless, Cursor and NVIDIA as required/contributing technologies — Space XAI
  is not mentioned in the rules text at all, only as a sponsor logo.

---

## 3. What's changed on the public pages since 7 Oct (checked today, 2026-10-07)

Checked `hackathon.genai.works/event/open-agent-hackathon-2026` directly (not cached search
snippets) and `academy.genai.works/courses/open-agent-hackathon-2026/details` (renders almost no
content without login — not useful).

**Confirmed live on the event page, matches `BRIEF.md`:**
- Dates: build 22–27 Oct, registration closes 22 Oct 23:59 UTC, judging opens 27 Oct 00:00,
  submissions close 27 Oct 23:45, results 6 Nov 16:00 UTC.
- 3 tracks + Wildcard bonus (unchanged): Fragmented Intelligence, The Agent That Can Explain Why,
  Reasoning Architecture, + Wildcard [Tinkerer] (explicitly requires Zetaris + Meterless only).
- Prize pool still $20,000 total ($15,000 cash + $5,000 in-kind), same scoring weights (Impact 30,
  Technical 20, Innovation 15, Demo 15, Product&UX 10, Sponsor Tech 10).
- Sponsor logos shown: **NVIDIA, Zetaris, SpaceX AI, Meterless.**
- Official Rules §5.1–5.2 (required tech) unchanged: "every submission must integrate Zetaris and
  Meterless, and teams must use Cursor for development... Integrate NVIDIA technology wherever it
  contributes." Submission requirements §6.1/6.2/6.4 also still only name Zetaris, Meterless, Cursor,
  NVIDIA — no mention of Bright Data or Space XAI in the required-technology text.

**Discrepancy worth flagging:** `BRIEF.md` lists Bright Data as a sponsor "as of 7 Oct," but **Bright
Data does not appear anywhere on the live event page today** — not in the sponsor logo row, not in
the rules text, not in the FAQ (checked the full page text programmatically: zero matches for "Bright
Data"). This isn't necessarily wrong — `BRIEF.md` says its source was "their announcement and the
HackOS event record," which may be a Discord/HackOS-only channel I can't reach from here — but it
means Bright Data's sponsorship is **not independently confirmed from any public page** as of this
check. Worth a direct look at HackOS/Discord to confirm before relying on it, since the one channel I
could check (the public event page) disagrees.

**Nothing found changing the required-technology list, new challenge statements, or new prize
details** beyond what's already in `BRIEF.md`. The organisers' own framing stands: extra challenges
and prizes are presented at onboarding (21 Oct), so re-check then.
