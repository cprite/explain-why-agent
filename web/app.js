/* Anomaly board and result view (architecture §1 and §7). Vanilla JS, no build step, no other host.
 *
 * Every piece of card or result data reaches the page through textContent (el() below); markup is
 * never built from strings. The render functions are pure (they return elements) so they can be
 * tested outside a browser: tests/web/render_check.js loads this file in node with a small DOM shim.
 */
"use strict";

const EW = (() => {
  const CACHE_MISS_TEXT = "No recorded answer for this question in sample mode";
  const UNDETERMINABLE_TEXT = "Cannot be determined from the data";
  const METRIC_LIMIT = 25; // the API's cap for ?metric=KEY&limit=N
  const BOARD_TIMEOUT_MS = 330 * 1000; // the scan's own cap is SCANNER_TIMEOUT_S (300 s)
  const BOARD_BUSY_RETRIES = 40; // board load waits for a running investigation, every 3 s
  const BOARD_BUSY_DELAY_MS = 3000;

  // ---------------------------------------------------------------- helpers
  function el(tag, props, children) {
    const node = document.createElement(tag);
    const p = props || {};
    if (p.className) node.className = p.className;
    if (p.text !== undefined && p.text !== null) node.textContent = String(p.text);
    if (p.attrs) for (const [k, v] of Object.entries(p.attrs)) node.setAttribute(k, String(v));
    for (const child of children || []) if (child) node.appendChild(child);
    return node;
  }

  function fmt(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
    const v = Number(value);
    const a = Math.abs(v);
    if (a >= 1000) return Math.round(v).toLocaleString("en-US");
    if (a >= 10) return v.toFixed(1);
    return v.toFixed(3);
  }

  function signed(text, value) {
    return (Number(value) > 0 ? "+" : Number(value) < 0 ? "−" : "") + text.replace(/^-/, "");
  }

  function changeText(card) {
    const pct = card.change_pct === null || card.change_pct === undefined
      ? "n/a" : signed(`${Math.round(Math.abs(card.change_pct) * 100)}%`, card.change_pct);
    return `${signed(fmt(Math.abs(card.change)), card.change)} (${pct})`;
  }

  function periodText(period) {
    const span = period.start === period.end ? period.start : `${period.start} to ${period.end}`;
    if (period.grain === "week") return `${period.periods === 1 ? "week" : "weeks"} ${span}`;
    return span;
  }

  // ---------------------------------------------------------------- cards
  function renderCard(card, onExplain) {
    const item = el("article", { className: `card ${card.direction === "fall" ? "fall" : "rise"}`,
                                 attrs: { "data-card-id": card.id } }, [
      el("div", { className: "card-head" }, [
        el("span", { className: "metric", text: card.metric_label }),
        el("span", { className: "rank", text: `#${card.overall_rank || card.rank}` }),
      ]),
      el("div", { className: "segment", text: card.segment ? card.segment.label : "" }),
      el("div", { className: "period", text: card.period ? periodText(card.period) : "" }),
      el("div", { className: "values" }, [
        el("span", { className: "baseline", text: fmt(card.baseline) }),
        el("span", { className: "arrow", text: " → " }),
        el("span", { className: "observed", text: fmt(card.observed) }),
        el("span", { className: "change", text: ` ${changeText(card)}` }),
      ]),
      card.top_attribution ? el("div", { className: "attribution", text: card.top_attribution }) : null,
    ]);
    const button = el("button", { className: "explain", text: "Explain", attrs: { type: "button" } });
    button.addEventListener("click", () => onExplain && onExplain(card));
    item.appendChild(button);
    return item;
  }

  function renderTile(board, onExplain, onMore) {
    const list = el("div", { className: "cards" }, board.cards.map((c) => renderCard(c, onExplain)));
    const count = board.episodes_found === 1 ? "1 flagged episode" : `${board.episodes_found} flagged episodes`;
    const tile = el("section", { className: "tile", attrs: { "data-metric": board.metric } }, [
      el("h3", { text: board.metric_label }),
      el("p", { className: "count", text: count }),
      list,
    ]);
    if (board.episodes_found > board.cards.length && onMore) {
      const more = el("button", { className: "show-more", text: "Show more", attrs: { type: "button" } });
      more.addEventListener("click", () => onMore(board, list, more));
      tile.appendChild(more);
    }
    if (!board.cards.length) list.appendChild(el("p", { className: "none", text: "Nothing flagged." }));
    return tile;
  }

  // ---------------------------------------------------------------- result
  function section(title, className, children) {
    return el("section", { className }, [el("h3", { text: title }), ...children]);
  }

  function renderEvidence(item) {
    return el("li", { className: "evidence" }, [
      el("details", {}, [
        el("summary", { text: `${item.source} · query ${item.query_id}` }),
        el("p", { className: "finding", text: item.finding }),
      ]),
    ]);
  }

  function renderCause(cause) {
    const evidence = cause.evidence || [];
    const pct = Math.round(Number(cause.confidence) * 100);
    return el("li", { className: cause.rank === 1 ? "cause top" : "cause" }, [
      el("div", { className: "cause-head" }, [
        el("span", { className: "ring", attrs: { style: `--p:${Number.isFinite(pct) ? pct : 0}`, "aria-hidden": "true" } }, [
          el("span", { text: Number.isFinite(pct) ? `${pct}` : "?" }),
        ]),
        el("span", { className: "cause-rank", text: `#${cause.rank}` }),
        el("span", { className: "cause-type", text: cause.type }),
        el("span", { className: "confidence", text: `confidence ${pct}%` }),
      ]),
      el("p", { className: "cause-summary", text: cause.summary }),
      el("p", { className: "label", text: `Evidence (${evidence.length})` }),
      el("ul", { className: "evidence-list" }, evidence.map(renderEvidence)),
    ]);
  }

  function renderResult(result) {
    const root = el("div", { className: "result-body", attrs: { "data-run-id": result.run_id } });
    root.appendChild(el("h2", { text: "Answer" }));
    root.appendChild(el("p", { className: "question", text: result.question }));

    const c = result.change;
    if (c) {
      const significant = c.significant === true ? "yes" : c.significant === false ? "no" : "not checked";
      const rows = [["Metric", c.metric], ["Segment", c.segment], ["Window", c.window],
        ["Baseline", fmt(c.baseline)], ["Observed", fmt(c.observed)], ["Significant", significant]];
      const base = Number(c.baseline);
      const obs = Number(c.observed);
      const rel = base && Number.isFinite(base) && Number.isFinite(obs) ? (obs - base) / Math.abs(base) : null;
      const dir = rel === null ? "" : rel >= 0 ? " rise" : " fall";
      root.appendChild(section("The change", `change${dir}`, [
        el("div", { className: "headline" }, [
          el("span", { className: "from", text: fmt(c.baseline) }),
          el("span", { className: "arrow", text: "→" }),
          el("span", { className: "to", text: fmt(c.observed) }),
          rel === null ? null : el("span", { className: "pct", text: signed(`${Math.round(Math.abs(rel) * 100)}%`, rel) }),
        ]),
        el("dl", {}, rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })])),
      ]));
    }

    if (result.status === "error" && result.error) {
      root.appendChild(el("p", { className: "run-error", text: `The run ended early (${result.error.code}): ${result.error.message}` }));
    }

    const causes = result.determinable ? (result.causes || []) : [];
    if (!result.determinable) {
      root.appendChild(el("p", { className: "undeterminable", text: UNDETERMINABLE_TEXT }));
    } else {
      root.appendChild(section("Ranked causes", "causes", [
        causes.length ? el("ol", { className: "cause-list" }, causes.map(renderCause))
          : el("p", { text: "No cause was supported." }),
      ]));
    }

    const ruled = result.ruled_out || [];
    root.appendChild(section("Ruled out", "ruled-out", [
      ruled.length
        ? el("ul", {}, ruled.map((r) => el("li", { className: "ruled" }, [
          el("span", { className: "ruled-type", text: r.type }),
          el("span", { text: `: ${r.why}` }),
          r.evidence && r.evidence.length ? el("span", { className: "query-ids", text: ` (queries ${r.evidence.join(", ")})` }) : null,
        ])))
        : el("p", { text: "Nothing was ruled out." }),
    ]));

    const limits = result.limitations || [];
    root.appendChild(section("Limitations", "limitations", [
      limits.length ? el("ul", {}, limits.map((t) => el("li", { text: t }))) : el("p", { text: "None stated." }),
    ]));

    const checks = causes.flatMap((cause) => (cause.next_checks || []).map((t) => `Cause ${cause.rank}: ${t}`));
    root.appendChild(section("Next checks", "next-checks", [
      checks.length ? el("ul", {}, checks.map((t) => el("li", { text: t }))) : el("p", { text: "None suggested." }),
    ]));

    const meta = [`run ${result.run_id}`, result.sample_mode ? "sample mode" : "live model",
      `${fmt(result.execution_time_seconds)} s`].join(" · ");
    root.appendChild(el("p", { className: "meta", text: meta }));
    const trace = el("a", { className: "trace-link", text: "Download trace",
      attrs: { href: `/runs/${encodeURIComponent(result.run_id)}/trace`, download: `trace-${result.run_id}.jsonl` } });
    root.appendChild(el("p", {}, [trace]));
    return root;
  }

  // ---------------------------------------------------------------- agents at work (live trace)
  // The run's trace (GET /runs/{id}/trace, served while the run is going) read as hand-offs between
  // the agents. readTrace() is pure: events in, a summary out; renderLive() turns it into elements.
  const TEAM = ["Orchestrator", "Planner", "Investigator", "Data", "World Model", "Critic", "Reporter"];
  const AGENT_NAMES = { planner: "Planner", investigator: "Investigator", critic: "Critic", reporter: "Reporter",
                        DataLayer: "Data", WorldModel: "World Model" };
  const VERDICT_MARK = { supported: "✔ supported", refuted: "✘ refuted", insufficient: "? not enough evidence",
                         testing: "… testing", untested: "untested", tested: "tested" };
  const HYP_RE = /(H\d+)\s+([a-z_]+):\s*([^"…]*)/g;

  function agentName(raw) { return AGENT_NAMES[raw] || raw || ""; }

  function agentTag(name) {
    return el("span", { className: `ag ag-${String(name).toLowerCase().replace(/[^a-z]+/g, "-")}`, text: name });
  }

  function clip(text, n) {
    const s = String(text === null || text === undefined ? "" : text).replace(/\s+/g, " ").trim();
    return s.length > n ? `${s.slice(0, n - 1)}…` : s;
  }

  function duration(ms) {
    const s = Math.max(0, Math.round(Number(ms) / 1000));
    return s < 60 ? `${s} s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  function shortModel(routed) {
    const name = String(routed || "").split("/").pop();
    return name.replace(/-\d+b(-a\d+b)?$/, "") || "model";
  }

  function parseJson(text) {
    if (text && typeof text === "object") return text;
    try { return JSON.parse(text); } catch (_) { return null; }
  }

  function parseTrace(text) {
    const events = [];
    for (const line of String(text || "").split("\n")) {
      const e = line.trim() ? parseJson(line) : null;
      if (e && e.action) events.push(e);
    }
    return events;
  }

  function readTrace(events) {
    const steps = [];
    const hyps = new Map();
    const seen = new Set();
    let active = null;
    let lastAt = null;
    let finished = false;
    let calls = 0;
    let failedCalls = 0;
    let queries = 0;
    const hyp = (id, family, statement) => {
      const h = hyps.get(id) || { id, family, statement: "", state: "untested" };
      if (family) h.family = family;
      if (statement && statement.length > h.statement.length) h.statement = statement;
      hyps.set(id, h);
      return h;
    };
    const step = (from, to, text, extra) => {
      steps.push({ from, to, text, tone: "info", ...extra });
      if (from) seen.add(from);
      if (to) seen.add(to);
    };

    for (const e of events) {
      const at = Date.parse(e.timestamp);
      if (!Number.isNaN(at)) lastAt = at;
      const who = agentName(e.agent);
      const to = agentName(e.target_agent);
      const out = e.output_summary;
      const failed = !["ok", "success", "retried"].includes(e.status);
      switch (e.action) {
        case "start":
          step("Orchestrator", "Planner", `Question: ${clip(e.input_summary, 160)}`);
          active = "Planner";
          break;
        case "model_call":
        case "model_repair_call": {
          calls += 1;
          const recorded = e.provider === "cache" ? " · recorded reply" : "";
          const took = !recorded && e.duration_ms !== undefined && e.duration_ms !== null ? ` · ${duration(e.duration_ms)}` : "";
          if (failed) {
            failedCalls += 1;
            step(who, null, `model call ${e.status}${took}${e.error ? `: ${clip(e.error, 80)}` : ""}`,
                 { kind: "model", tone: "bad" });
          } else {
            const tokens = e.tokens && e.tokens.total_tokens ? ` · ${e.tokens.total_tokens} tokens` : "";
            step(who, null, `${e.action === "model_repair_call" ? "fixed its reply with" : "asked"} ${shortModel(e.model_routed)}${took}${tokens}${recorded}`,
                 { kind: "model" });
          }
          active = who;
          break;
        }
        case "plan": {
          for (const m of String(out || "").matchAll(HYP_RE)) hyp(m[1], m[2], m[3].trim());
          const metric = /"metric":\s*"([^"]*)/.exec(String(out || ""));
          step("Planner", "Investigator", `Plan ready${metric ? `: ${clip(metric[1], 120)}` : ""}`, { kind: "handoff" });
          active = "Investigator";
          break;
        }
        case "delegate": {
          const m = /^(H\d+)\s+([a-z_]+):\s*(.*)$/.exec(String(e.input_summary || ""));
          if (m) {
            const h = hyp(m[1], m[2], m[3]);
            h.state = "testing";
            step(who, to, `Test ${h.id} ${h.family}: ${clip(h.statement, 140)}`, { kind: "handoff" });
          } else if (e.input_summary === "change_check") {
            step(who, to, "First check that the change is real (window against baseline)", { kind: "handoff" });
          } else {
            step(who, to, `Write the answer from ${clip(e.input_summary, 60)}`, { kind: "handoff" });
          }
          active = to;
          break;
        }
        case "write_sql":
          if (failed) step("Investigator", null, `could not write SQL: ${clip(out, 120)}`, { tone: "bad" });
          else step("Investigator", "Data", "Wrote a query", { kind: "sql", code: String(out || "") });
          active = failed ? "Investigator" : "Data";
          break;
        case "repair_sql":
          step("Investigator", "Data", failed ? "could not fix the query" : `Fixed the query after: ${clip(e.previous_error, 100)}`,
               { kind: "sql", code: failed ? "" : String(out || ""), tone: failed ? "bad" : "warn" });
          active = failed ? "Investigator" : "Data";
          break;
        case "run_query":
          queries += 1;
          step("Data", "Investigator", failed ? `query failed: ${clip(String(out || "").replace(/^failed:\s*/, ""), 120)}`
            : `${String(out || "").replace(/^1 rows/, "1 row")} back${e.query_id ? ` (${e.query_id})` : ""}`,
               { tone: failed ? "bad" : "info" });
          active = "Investigator";
          break;
        case "observe":
          step("Investigator", "World Model", failed ? `no finding: ${clip(out, 120)}` : clip(out, 220),
               { kind: "observation", tone: failed ? "bad" : "info" });
          active = "World Model";
          break;
        case "ingest":
          step("World Model", "Critic", `Stored: ${clip(out, 80)}`);
          active = "Critic";
          break;
        case "critique": {
          const verdict = e.verdict || (parseJson(out) || {}).verdict || "insufficient";
          const reason = (parseJson(out) || {}).reason || "";
          if (e.hypothesis_id) hyp(e.hypothesis_id, e.family).state = verdict;
          step("Critic", "Orchestrator", `${e.hypothesis_id || ""} ${VERDICT_MARK[verdict] || verdict}${reason ? `: ${clip(reason, 200)}` : ""}`,
               { kind: "verdict", tone: verdict === "supported" ? "good" : verdict === "refuted" ? "bad" : "warn" });
          active = "Orchestrator";
          break;
        }
        case "request_revision":
          step("Critic", "Investigator", `Not convinced yet: test ${e.hypothesis_id || "it"} again`, { kind: "handoff", tone: "warn" });
          active = "Investigator";
          break;
        case "request_follow_up":
          step("Reporter", "Investigator", "Needs more evidence before answering", { kind: "handoff", tone: "warn" });
          active = "Investigator";
          break;
        case "chunk":
          step(null, null, `Step ${e.chunk}/${e.max_chunks}${e.rounds_left !== undefined ? ` · ${e.rounds_left} ${Number(e.rounds_left) === 1 ? "round" : "rounds"} left` : ""}`,
               { kind: "divider" });
          active = to || active;
          break;
        case "branch":
          if (e.branch !== "promotion") step("Orchestrator", null, clip(e.why || out, 160)); // promotion repeats the verdict
          break;
        case "report": {
          const text = String(out || "");
          const causes = [...text.matchAll(/"\d+\.\s*([a-z_]+)/g)].map((m) => m[1]);
          const ruled = /"ruled_out":\s*\[([^\]]*)/.exec(text);
          const ruledOut = ruled ? [...ruled[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]) : [];
          // Without the Critic (simple loop) the answer is what settles each hypothesis.
          for (const h of hyps.values()) {
            if (h.state !== "testing" && h.state !== "untested") continue;
            if (causes.includes(h.family)) h.state = "supported";
            else if (ruledOut.includes(h.family)) h.state = "refuted";
          }
          step("Reporter", "Orchestrator", failed ? `could not write the answer: ${clip(out, 120)}`
            : /"determinable":\s*false/.test(text) ? "Answer: cannot be determined from the data"
              : `Answer drafted${causes.length ? `: ${causes.join(", ")}` : ""}`,
               { kind: "handoff", tone: failed ? "bad" : "good" });
          active = "Orchestrator";
          break;
        }
        case "finish":
          finished = true;
          for (const h of hyps.values()) if (h.state === "testing") h.state = "tested";
          active = null;
          step("Orchestrator", null, `Finished (${e.stop_reason || e.status})`, { kind: "divider" });
          break;
        default:
          step(who, to || null, `${e.action.replace(/_/g, " ")}${out ? `: ${clip(out, 120)}` : ""}`);
      }
    }
    if (active) seen.add(active);
    return { steps, hypotheses: [...hyps.values()], active, seen, lastAt, finished, calls, failedCalls, queries };
  }

  function renderLive(view, opts) {
    const o = opts || {};
    const team = el("div", { className: "team" });
    TEAM.forEach((name, i) => {
      if (i) team.appendChild(el("span", { className: "team-arrow", text: "→" }));
      const state = view.active === name ? " active" : view.seen.has(name) ? " seen" : "";
      team.appendChild(el("span", { className: `agent ag-${name.toLowerCase().replace(/[^a-z]+/g, "-")}${state}`, text: name }));
    });
    const root = el("div", { className: "live-body" }, [team]);
    if (view.active && !view.finished) {
      const since = o.now && view.lastAt ? ` ${duration(o.now - view.lastAt)}` : "";
      root.appendChild(el("p", { className: `thinking ag-${view.active.toLowerCase().replace(/[^a-z]+/g, "-")}` }, [
        el("span", { className: "dot" }),
        el("span", { text: `${view.active} is working…` }),
        el("span", { className: "clock", text: since }),
      ]));
    }
    if (view.hypotheses.length) {
      root.appendChild(el("ul", { className: "hyps" }, view.hypotheses.map((h) => el("li", {
        className: `hyp ${h.state}`, attrs: { title: h.statement } }, [
        el("span", { className: "hyp-id", text: h.id }),
        el("span", { className: "hyp-family", text: h.family || "" }),
        el("span", { className: "hyp-state", text: VERDICT_MARK[h.state] || h.state }),
      ]))));
    }
    const fresh = Number.isInteger(o.fresh) ? o.fresh : 0; // steps from this index on are new: they slide in
    const feed = el("ol", { className: "feed" }, view.steps.map((s, i) => {
      const who = s.kind === "divider" || !s.from ? null
        : el("span", { className: "who" }, s.to ? [agentTag(s.from), el("span", { className: "to", text: " → " }), agentTag(s.to)]
          : [agentTag(s.from)]);
      const item = el("li", { className: `step ${s.kind || "note"} ${s.tone}${i >= fresh ? " new" : ""}` }, [
        who,
        el("span", { className: "what", text: s.text }),
      ]);
      if (s.code) item.appendChild(el("details", {}, [el("summary", { text: "SQL" }), el("pre", { text: s.code })]));
      return item;
    }));
    root.appendChild(feed);
    root.appendChild(el("p", { className: "live-stats",
      text: `${view.calls} model calls${view.failedCalls ? ` (${view.failedCalls} failed and retried)` : ""} · ${view.queries} queries` }));
    return root;
  }

  // ---------------------------------------------------------------- errors
  function errorMessage(status, body) {
    const err = body && body.error;
    if (err && err.code === "cache_miss") return `${CACHE_MISS_TEXT} (cache_miss).`;
    if (err && err.code === "busy") return "Another run is in progress; try again when it has finished (busy).";
    if (err && typeof err.message === "string") return `${err.message} (${err.code}).`;
    return `The server answered HTTP ${status} without a readable message.`;
  }

  async function requestJson(url, init, timeoutMs, asText) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { ...init, signal: controller.signal });
      let body = null;
      try { body = asText ? await response.text() : await response.json(); } catch (_) { body = null; }
      return { ok: response.ok, status: response.status, body };
    } catch (exc) {
      const text = exc && exc.name === "AbortError"
        ? `No answer within ${Math.round(timeoutMs / 1000)} s; the run may still finish on the server.`
        : "The server could not be reached.";
      return { ok: false, status: 0, body: null, text };
    } finally {
      clearTimeout(timer);
    }
  }

  // ---------------------------------------------------------------- page
  function init() {
    const $ = (id) => document.getElementById(id);
    const meta = document.querySelector('meta[name="run-timeout-seconds"]');
    const runTimeoutMs = Math.max(1, Number(meta && meta.content) || 600) * 1000;
    let running = false;
    let ticker = null;
    let replaying = null;
    const LIVE_POLL_MS = 2000;
    const REPLAY_STEP_MS = 450;

    function showMessage(text, kind) {
      const box = $("message");
      box.textContent = text || "";
      box.className = kind || "";
      box.hidden = !text;
    }

    function setProgress(text) {
      const started = Date.now();
      $("progress-text").textContent = text;
      $("elapsed").textContent = "0 s";
      $("progress").hidden = false;
      ticker = setInterval(() => { $("elapsed").textContent = `${Math.round((Date.now() - started) / 1000)} s`; }, 1000);
    }

    function clearProgress() {
      clearInterval(ticker);
      ticker = null;
      $("progress").hidden = true;
    }

    function setRunning(on) {
      running = on;
      for (const b of document.querySelectorAll("button.explain, #ask, button.replay")) b.disabled = on;
    }

    // The live view: redrawn when the trace grows; the "working" clock ticks on its own so an open
    // SQL box is not closed every second.
    let drawnSteps = 0;
    function drawLive(events, done) {
      const view = readTrace(events);
      const fresh = view.steps.length >= drawnSteps ? drawnSteps : 0;
      drawnSteps = view.steps.length;
      const children = [el("h2", { text: done ? "How the agents worked it out" : "Agents at work" }),
        renderLive(view, { now: done ? null : Date.now(), fresh: done ? view.steps.length : fresh })];
      if (done && events.length) {
        const replay = el("button", { className: "replay", text: "Replay step by step", attrs: { type: "button" } });
        replay.addEventListener("click", () => replayTrace(events));
        children.push(replay);
      }
      $("live").replaceChildren(...children);
      $("live").hidden = false;
      const feed = $("live").querySelector(".feed");
      if (feed) feed.scrollTop = feed.scrollHeight;
      return view;
    }

    function replayTrace(events) {
      clearInterval(replaying);
      let shown = 0;
      drawnSteps = 0;
      replaying = setInterval(() => {
        shown += 1;
        if (shown >= events.length) { clearInterval(replaying); replaying = null; drawLive(events, true); return; }
        if (!running) drawLive(events.slice(0, shown), false);
      }, REPLAY_STEP_MS);
    }

    async function followTrace(runId, state) {
      const url = `/runs/${encodeURIComponent(runId)}/trace`;
      let size = -1;
      while (!state.done) {
        const t = await requestJson(url, {}, 10000, true);
        if (state.done) break;
        if (t.ok && typeof t.body === "string" && t.body.length !== size) {
          size = t.body.length;
          state.events = parseTrace(t.body);
          state.view = drawLive(state.events, false);
        }
        await new Promise((resolve) => setTimeout(resolve, LIVE_POLL_MS));
      }
    }

    function tickLive(state) {
      const clock = $("live").querySelector(".thinking .clock");
      if (clock && state.view && state.view.lastAt) clock.textContent = ` ${duration(Date.now() - state.view.lastAt)}`;
    }

    function newRunId() {
      return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    }

    async function startRun(payload, label) {
      if (running) return;
      setRunning(true);
      clearInterval(replaying);
      showMessage("");
      $("result").hidden = true;
      $("live").hidden = true;
      setProgress(label);
      const runId = newRunId();
      const state = { done: false, events: [], view: null };
      drawnSteps = 0;
      followTrace(runId, state);
      const clock = setInterval(() => tickLive(state), 1000);
      const r = await requestJson("/run", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, run_id: runId }),
      }, runTimeoutMs);
      state.done = true;
      clearInterval(clock);
      const t = await requestJson(`/runs/${encodeURIComponent(runId)}/trace`, {}, 10000, true);
      if (t.ok && typeof t.body === "string") state.events = parseTrace(t.body);
      if (state.events.length) drawLive(state.events, true);
      clearProgress();
      setRunning(false);
      if (r.ok && r.body) {
        $("result").replaceChildren(renderResult(r.body));
        $("result").hidden = false;
        $("result").scrollIntoView({ block: "start" });
      } else {
        showMessage(r.text || errorMessage(r.status, r.body), "error");
      }
    }

    const explain = (card) => startRun({ anomaly_id: card.id }, `Explaining: ${card.question}`);

    async function showMore(board, list, button) {
      button.disabled = true;
      const url = `/anomalies?metric=${encodeURIComponent(board.metric)}&limit=${METRIC_LIMIT}`;
      const r = await requestJson(url, {}, BOARD_TIMEOUT_MS);
      if (r.ok && r.body) {
        list.replaceChildren(...r.body.cards.map((c) => renderCard(c, explain)));
        if (running) for (const b of list.querySelectorAll("button.explain")) b.disabled = true;
        button.remove();
      } else {
        button.disabled = false;
        showMessage(r.text || errorMessage(r.status, r.body), "error");
      }
    }

    async function loadBoard() {
      $("top-cards").replaceChildren(el("p", { className: "loading",
        text: "Scanning the data for flagged movements (about 30 s on first load)\u2026" }));
      let r = null;
      for (let attempt = 0; attempt <= BOARD_BUSY_RETRIES; attempt += 1) {
        r = await requestJson("/anomalies", {}, BOARD_TIMEOUT_MS);
        if (r.status !== 429) break;
        await new Promise((resolve) => setTimeout(resolve, BOARD_BUSY_DELAY_MS));
      }
      if (!(r && r.ok && r.body)) {
        $("top-cards").replaceChildren();
        showMessage(r.text || errorMessage(r.status, r.body), "error");
        return;
      }
      $("top-cards").replaceChildren(...r.body.cards.map((c) => renderCard(c, explain)));
      $("tiles").replaceChildren(...r.body.by_metric.map((b) => renderTile(b, explain, showMore)));
      if (r.body.timed_out) showMessage("The scan stopped at its time cap; the cards are partial.", "warning");
    }

    $("ask").addEventListener("click", () => {
      const query = $("question").value.trim();
      if (!query) { showMessage("Type a question first.", "error"); return; }
      startRun({ input: { query } }, "Investigating your question");
    });
    $("question").addEventListener("keydown", (e) => { if (e.key === "Enter") $("ask").click(); });

    requestJson("/health", {}, 10000).then((h) => {
      if (h.ok && h.body) {
        $("mode").textContent = h.body.sample_mode ? "sample mode" : "live model";
        $("mode").hidden = false;
      }
    });
    loadBoard();
  }

  return { readTrace, parseTrace, renderLive, renderCard, renderTile, renderResult, errorMessage, changeText, periodText, fmt, init,
           CACHE_MISS_TEXT, UNDETERMINABLE_TEXT };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = EW;
} else {
  window.EW = EW;
  document.addEventListener("DOMContentLoaded", EW.init);
}
