# Sprint 10b — Critic failure path and plan check labels

Issue #31. These are fixes from the PR #28 review: two should_fix items and two nits. No new feature.
Only the failure path changes. In sample mode the success path gives the same results as before,
so every recorded cache under `data/sample/` stays valid. Prompts, `app/llm/`, `eval/` and `web/`
are not touched.

## What was built

### 1. A failed Critic no longer costs a revision chunk

Before this sprint, during a provider outage each hypothesis cost two chunks and four Critic model
calls. The Critic's fallback verdict (`insufficient`, no follow-up tests) started a revision chunk,
but the chunk had no test to run. The second critique then failed in the same way. The result
blamed the data: "Unconfirmed: H1 … Data that would decide it: more records for this segment".

- `Verdict` gains one optional field, `critic_error` (default `None`). `app/agents/critic.py` sets
  it to the error code (`provider_error`, `timeout`, `invalid_reply`, …) when the call fails or the
  reply is still invalid after the retry. Verdicts without it still validate. `Verdict` is never a
  reply schema sent to a model, so no prompt or cache key changes.
- Orchestrator (`_round`, `_judged`): an `insufficient` verdict with no follow-up tests, and no
  small-sample flag, cannot be revised (`_unrevisable`). It is demoted at once, with no revision
  chunk. The leader is promoted as for any demotion. A `skip_revision` trace line says why. The
  small-sample verdict is left out of this rule because it ends the run through its own branch, as
  before.
- `_conclude` words a Critic failure as a Critic failure:
  - limitation: `Critic failure: the Critic could not judge H1 (logistics_delay) (provider_error); it
    is unconfirmed because the critique failed, not because data is missing.`;
  - why and summary, when nothing is supported: `the Critic could not judge H1 (provider_error), H2
    (provider_error), …`. If only some failed, `; the other tested explanations were refuted or left
    unconfirmed` is added.

  This check comes before the `max_chunks` / `max_tool_calls` wording. The "Data that would decide
  it" line is no longer written for these hypotheses.
- Each Critic trace line now has `critic_error` and `model_calls`.

### 2. Supported, but not reported

When the Critic supported a hypothesis, `_conclude` now sets an explicit why in two cases: no cause
in the report is one the Critic supported, or the Reporter called the answer not determinable. The
why is `the Reporter did not report the supported explanation (H1)`. The `cannot_be_determined`
branch line and `Result.summary` both use it. Before, the second case wrote `cannot_be_determined`
with "the Critic supported the leading explanation". The summary said "no tested explanation is
supported by the data". The first case said "no cause in the report is one the Critic supported",
which did not name the hypothesis.

### 3. The Critic cap counts critiques (documented, not changed)

The choice was between counting model calls and documenting the current unit. I chose to document
it. `max_chunks` caps **Critic calls, one per critique**. The real Critic retries an invalid reply
once (`MAX_REPLY_ATTEMPTS = 2`), so one critique is up to 2 model calls, and a run makes at most
`max_chunks` × 2 Critic model calls. Counting model calls would change which critiques run when a
retry happens, which is more than a fix sprint should change. The rule is in the module docstring,
the `_critique` docstring, the cap note (`… Critic calls (MARKOVIAN_MAX_CHUNKS; each up to 2 model
calls) were made.`) and the trace (`model_calls` per line, next to `critic_call` and
`max_critic_calls`).

Every orchestrated chunk holds at most one critique, and the plan chunk holds none. So the Critic
cap only binds if that changes. The test therefore checks both: the counting in a full run, and the
cap itself on `_Run._critique`.

### 4. Plan check N

`ci.yml` had two steps labelled "Plan check L": the eval step (PR #20) and the Critic step (PR #28).
Both PRs took L as the next free letter while the other was still open. The Critic step is now
**Plan check N** (M is taken by PR #30), and its run ids are `ci-plan-check-n-*`. The
`scripts/check_critic_run.py` docstring and the references in `docs/sprints/09-critic-and-branches.md`
say N too. The eval step is unchanged. `tests/test_ci_labels.py` fails if a plan check letter is used
twice. Plan check D is the only exception: two steps on purpose, task 7 and task 10 (Sprint 6b).

## How it was tested

- `tests/test_critic.py`, 8 new cases, no network:
  - **Critic always fails** (parametrised: `provider_error` from the model call, and `invalid_reply`
    for a reply that does not validate). The chunk list is exactly plan + 4 rounds, with no
    `request_revision`. There is one critique per hypothesis with `model_calls` 2: 8 Critic model
    calls, against 16 before. The other model calls are as many as in a run whose Critic answers
    once per hypothesis. Every hypothesis is `demoted`, `determinable: false`, and there are four
    `Critic failure:` limitations and no "Data that would decide it". The branch why and the summary
    name `the Critic could not judge H1 (code), …`.
  - one failure among refutations: no revision, promotion H1 → H2, the summary names H1's failure;
  - an insufficient verdict with a follow-up test still gets its revision chunk (`model_calls` 1,
    `critic_error` null);
  - **supported but not reported**: the Reporter is not determinable, or reports its cause under
    another hypothesis. A third case patches the Reporter outcome to keep the supported cause but be
    not determinable. In each, the branch why is the summary's why;
  - **cap**: with a first reply always invalid, `critic_call` goes 1, 2, 3 while the model sees 6
    calls, and each line has `model_calls` 2. At `critic_calls == max_chunks`, `_critique` does not
    call the hook and writes the note naming the unit.
- `tests/test_ci_labels.py` (2 tests): no reused plan check letter except D; L is the eval step and
  N is the Critic step.
- Whole suite: `pytest -q` gives 660 passed in 291 s under
  `systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0`. `ruff check .` is clean.
- **Same output as main.** Plan check J, the eval step and the Critic step (four runs) were run on
  `origin/main` (457cde2) and on this branch. The printed output was diffed, with the elapsed
  seconds and eval timestamps masked. So were the five result JSONs, without `run_id`, time and log
  paths. Both are identical. Plan check N on this branch (shortened; all four runs as in PR #28):

  ```
  [PASS] refuted:logistics_delay: determinable=True, 1 causes, 4 Critic calls, stop_reason=completed
  summary: Cannot be determined from the data: the Critic flagged the sample as too small (3 records in the window, minimum 30) (1 tested, 0 ruled out).
  [PASS] undeterminable: determinable=False, 0 causes, 1 Critic calls, stop_reason=completed
  summary: Cannot be determined from the data: every tested explanation was refuted or left unconfirmed by the Critic (4 tested, 3 ruled out).
  [PASS] undeterminable: determinable=False, 0 causes, 5 Critic calls, stop_reason=completed
  [PASS] no-change: determinable=True, 0 causes, 0 Critic calls, stop_reason=no_hypotheses
  ```

  Plan check J: `[PASS] 5/8 chunks, every chunk input within budget, stop_reason=completed`. Eval:
  `Score: 0/10 (answered 1, no_cache 9, errors 0)`, as on main.

## Left out

- **Counting Critic model calls in the cap** (see 3).
- **Ruled-out count in the summary.** It still includes the Reporter's own ruled-out entries, which
  come from the Investigator's readings. On an all-failed Critic run it reads "(4 tested, 3 ruled
  out)": the Reporter ruled them out from the measurements, not the Critic. This is unchanged from
  Sprint 9.
- **No retry across rounds.** A Critic that fails for H1 is not asked again later in the run, even
  if the provider recovers. The hypothesis stays demoted.

## Known limits

- A custom `CriticHook` that returns `insufficient` with no follow-up tests (and no `critic_error`)
  is now demoted at once too, because there is nothing to revise. Its limitation keeps the
  "Unconfirmed: … Data that would decide it: more records for this segment" wording, because there
  is no error code.
- The failure path is covered by tests with a scripted generator only. No recorded cache has a
  Critic failure in it.
