// Rendering rules of web/app.js, checked in node with a minimal DOM shim (no browser, no network).
// Run by tests/test_web_page.py: `node tests/web/render_check.js`; prints one PASS line per check
// and exits non-zero on the first failure. The shim has no innerHTML / insertAdjacentHTML /
// outerHTML: using any of them throws, so the render code can only insert data as text.
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

class TextNode {
  constructor(text) { this.nodeType = 3; this.data = String(text); }
  get textContent() { return this.data; }
}

class Element {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this.hidden = false;
    this.disabled = false;
  }
  appendChild(child) {
    if (!(child instanceof Element || child instanceof TextNode)) throw new TypeError("appendChild needs a node");
    this.childNodes.push(child);
    return child;
  }
  replaceChildren(...nodes) { this.childNodes = []; nodes.forEach((n) => this.appendChild(n)); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  click() { (this.listeners.click || []).forEach((fn) => fn({ target: this })); }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(""); }
  set textContent(value) { this.childNodes = [new TextNode(value)]; }
}
for (const name of ["innerHTML", "outerHTML"]) {
  Object.defineProperty(Element.prototype, name, {
    get() { throw new Error(`${name} used`); },
    set() { throw new Error(`${name} used`); },
  });
}
Element.prototype.insertAdjacentHTML = () => { throw new Error("insertAdjacentHTML used"); };

global.document = {
  createElement: (tag) => new Element(tag),
  createTextNode: (text) => new TextNode(text),
  write: () => { throw new Error("document.write used"); },
};

const EW = require(path.resolve(__dirname, "../../web/app.js"));

function all(node, out = []) {
  if (node instanceof Element) { out.push(node); node.childNodes.forEach((c) => all(c, out)); }
  return out;
}
const byClass = (root, cls) => all(root).filter((n) => n.className.split(" ").includes(cls));
const byTag = (root, tag) => all(root).filter((n) => n.tagName === tag.toUpperCase());

function check(name, fn) {
  fn();
  console.log(`PASS ${name}`);
}

const XSS = '<img src=x onerror="window.pwned=1">';
const base = {
  run_id: "stub-1", status: "success", question: "Why did reviews fall?", trace_id: "stub-1",
  log_file: "logs/trace-stub-1.jsonl", execution_time_seconds: 1.5, sample_mode: true,
  change: { metric: "avg review score", segment: "relogios_presentes", window: "2018-01-15 to 2018-02-05",
            baseline: 3.94, observed: 2.04, significant: true },
  ruled_out: [{ type: "logistics_delay", why: "delivery times were normal", evidence: ["q003"] }],
  limitations: ["sample data only"],
};
const cause = {
  rank: 1, type: "product_quality", summary: "One watch model drew bad reviews.", confidence: 0.8,
  evidence: [{ observation_id: "obs-1", source: "reviews", query_id: "q002", finding: "1-star share rose to 40%." }],
  next_checks: ["Check the seller's returns."],
};

check("undeterminable result says so and shows no cause", () => {
  // A cause in the payload is not shown even though the API would never send one (schema rule).
  const root = EW.renderResult({ ...base, determinable: false, causes: [cause] });
  const text = root.textContent;
  assert.ok(text.includes("Cannot be determined from the data"), text);
  assert.equal(byClass(root, "cause").length, 0);
  assert.equal(byClass(root, "causes").length, 0);
  assert.ok(!text.includes(cause.summary));
  assert.ok(!text.includes("Ranked causes"));
  assert.ok(text.includes("sample data only"), "limitations are shown");
  assert.ok(text.includes("delivery times were normal"), "ruled-out list is shown");
});

check("determinable result shows ranked causes with expandable evidence and a trace link", () => {
  const root = EW.renderResult({ ...base, determinable: true, causes: [cause] });
  assert.ok(!root.textContent.includes("Cannot be determined"));
  assert.equal(byClass(root, "cause").length, 1);
  const details = byTag(root, "details");
  assert.equal(details.length, 1);
  assert.ok(details[0].textContent.includes("reviews") && details[0].textContent.includes("q002"));
  assert.ok(details[0].textContent.includes("1-star share rose to 40%."));
  assert.ok(root.textContent.includes("confidence 80%"));
  assert.ok(root.textContent.includes("Cause 1: Check the seller's returns."));
  const link = byClass(root, "trace-link")[0];
  assert.equal(link.getAttribute("href"), "/runs/stub-1/trace");
  assert.equal(link.textContent, "Download trace");
});

check("markup in result fields is inserted as text", () => {
  const evil = { ...cause, summary: XSS, type: XSS,
                 evidence: [{ ...cause.evidence[0], finding: XSS, source: XSS, query_id: XSS }],
                 next_checks: [XSS] };
  const root = EW.renderResult({ ...base, question: XSS, determinable: true, causes: [evil],
                                 change: { ...base.change, metric: XSS },
                                 ruled_out: [{ type: XSS, why: XSS, evidence: [XSS] }], limitations: [XSS] });
  assert.equal(byTag(root, "img").length, 0);
  assert.equal(byClass(root, "cause-summary")[0].textContent, XSS);
  assert.equal(byClass(root, "question")[0].textContent, XSS);
  assert.equal(global.window, undefined);
});

check("trace link escapes the run id", () => {
  const root = EW.renderResult({ ...base, run_id: "a/../b?x", determinable: false });
  assert.equal(byClass(root, "trace-link")[0].getAttribute("href"), "/runs/a%2F..%2Fb%3Fx/trace");
});

const card = {
  id: "avg_review_score|category|relogios_presentes|2018-01-15", rank: 6, overall_rank: 37,
  metric: "avg_review_score", metric_label: "average review score",
  segment: { type: "category", value: "relogios_presentes", label: "category relogios_presentes" },
  period: { start: "2018-01-15", end: "2018-02-04", grain: "week", periods: 3 },
  baseline: 3.9412, observed: 2.0377, change: -1.9035, change_pct: -0.483, direction: "fall",
  z_score: -8.43, top_attribution: null, question: "Why did average review score fall?",
};

check("card shows metric, segment, period, baseline to observed and signed change", () => {
  let explained = null;
  const node = EW.renderCard(card, (c) => { explained = c; });
  const text = node.textContent;
  for (const part of ["average review score", "category relogios_presentes", "weeks 2018-01-15 to 2018-02-04",
                      "3.941", "2.038", "−1.903 (−48%)", "#37"]) {
    assert.ok(text.includes(part), `${part} missing in ${text}`);
  }
  assert.equal(node.getAttribute("data-card-id"), card.id);
  assert.equal(byClass(node, "attribution").length, 0, "no attribution line when there is none");
  byClass(node, "explain")[0].click();
  assert.equal(explained, card);
  const rise = EW.renderCard({ ...card, change: 12.5, change_pct: 0.25, direction: "rise",
                               top_attribution: "driven by state RJ: 72% of the change" });
  assert.ok(rise.textContent.includes("+12.5 (+25%)"));
  assert.ok(rise.textContent.includes("driven by state RJ: 72% of the change"));
});

check("markup in card fields is inserted as text", () => {
  const node = EW.renderCard({ ...card, metric_label: XSS, top_attribution: XSS,
                               segment: { ...card.segment, label: XSS } });
  assert.equal(byTag(node, "img").length, 0);
  assert.equal(byClass(node, "metric")[0].textContent, XSS);
  assert.equal(byClass(node, "attribution")[0].textContent, XSS);
});

check("tile shows the count, its cards and Show more only when there are more", () => {
  const board = { metric: "avg_review_score", metric_label: "average review score", episodes_found: 25,
                  cards: [card, card, card] };
  let asked = null;
  const tile = EW.renderTile(board, null, (b) => { asked = b; });
  assert.ok(tile.textContent.includes("25 flagged episodes"));
  assert.equal(byClass(tile, "card").length, 3);
  byClass(tile, "show-more")[0].click();
  assert.equal(asked, board);
  const full = EW.renderTile({ ...board, episodes_found: 3 }, null, () => {});
  assert.equal(byClass(full, "show-more").length, 0);
});

check("structured errors become readable messages", () => {
  const miss = EW.errorMessage(409, { error: { code: "cache_miss", message: "no cached reply for key abc", run_id: "r" } });
  assert.ok(miss.startsWith("No recorded answer for this question in sample mode"), miss);
  assert.ok(EW.errorMessage(429, { error: { code: "busy", message: "x", run_id: null } }).includes("in progress"));
  assert.equal(EW.errorMessage(404, { error: { code: "not_found", message: "no card", run_id: null } }),
               "no card (not_found).");
  assert.equal(EW.errorMessage(502, null), "The server answered HTTP 502 without a readable message.");
});

console.log("ALL RENDER CHECKS PASSED");
