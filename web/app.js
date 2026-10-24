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
    return el("li", { className: "cause" }, [
      el("div", { className: "cause-head" }, [
        el("span", { className: "cause-type", text: cause.type }),
        el("span", { className: "confidence", text: `confidence ${Math.round(Number(cause.confidence) * 100)}%` }),
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
      root.appendChild(section("The change", "change", [
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
        ? el("ul", {}, ruled.map((r) => el("li", {}, [
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

  // ---------------------------------------------------------------- errors
  function errorMessage(status, body) {
    const err = body && body.error;
    if (err && err.code === "cache_miss") return `${CACHE_MISS_TEXT} (cache_miss).`;
    if (err && err.code === "busy") return "Another run is in progress; try again when it has finished (busy).";
    if (err && typeof err.message === "string") return `${err.message} (${err.code}).`;
    return `The server answered HTTP ${status} without a readable message.`;
  }

  async function requestJson(url, init, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { ...init, signal: controller.signal });
      let body = null;
      try { body = await response.json(); } catch (_) { body = null; }
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
      for (const b of document.querySelectorAll("button.explain, #ask")) b.disabled = on;
    }

    async function startRun(payload, label) {
      if (running) return;
      setRunning(true);
      showMessage("");
      $("result").hidden = true;
      setProgress(label);
      const r = await requestJson("/run", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      }, runTimeoutMs);
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

  return { renderCard, renderTile, renderResult, errorMessage, changeText, periodText, fmt, init,
           CACHE_MISS_TEXT, UNDETERMINABLE_TEXT };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = EW;
} else {
  window.EW = EW;
  document.addEventListener("DOMContentLoaded", EW.init);
}
