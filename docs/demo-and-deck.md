# Demo video script and slide deck outline

Written 6 October 2026, before the build. The build should produce exactly what this demo shows.
Numbers in square brackets are filled in from real runs; nothing in the video is staged.

## Demo video — keep it under 3 minutes

The organisers' documents disagree on length: the newer participant documents say 1–4 minutes, the
support FAQ and the draft rules say 2–3 minutes. A video under 3 minutes satisfies both. The timings
below run to 3:20 and must be tightened by about 25 seconds when recording, by shortening the trace
section.

The organisers ask the video to show the main workflow, how the agent solves the challenge, its key
features, and how Zetaris and Meterless are integrated.

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:20 | The workspace board: metric tiles, four source systems named, one card flagged in red, "Watches review score −38% in January" | "An analyst's data lives in four systems that do not talk to each other: orders, payments, reviews, marketing. Our agent watches the key numbers across all of them and flags what moved. Here, review scores for watches fell sharply in January." |
| 0:20–0:35 | Click "Explain" on the card | "Finding out why usually takes an analyst days. One click starts an investigation instead. Nothing about this case is pre-programmed: the card came from the scanner." |
| 0:35–1:20 | Live trace: Planner confirms the drop and lists hypotheses; Investigator runs queries through Zetaris across reviews and orders; evidence appears | "The planner checks the change is real and proposes explanations. The investigator tests each one, querying the separate sources through Zetaris. Every finding is stored with the query and the source it came from." |
| 1:20–1:55 | The Critic step highlighted: it challenges "late deliveries", requests the delivery data for the same orders, and refutes it | "Late delivery is the obvious explanation, and a second agent's only job is to try to break the leading answer. It checks delivery times for these exact orders, finds them normal, and rules that explanation out." |
| 1:55–2:20 | Final answer: ranked causes, expandable evidence, the ruled-out list, confidence | "The result is a ranked list of causes, each with the numbers behind it, and a list of what was ruled out and why." |
| 2:20–2:45 | Second question, "Why has average order value been declining since August 2017?"; the answer "cannot be determined from this data", with the hypotheses tested | "Just as important is when it does not know. Here every explanation it can test comes back flat, so it says the cause is not in this data instead of inventing one." |
| 2:45–3:10 | Split view: World Model evidence records; the Markovian token report; the evaluation score | "Underneath are two Meterless engines: a world model that keeps every fact with its source, and a Markovian loop that keeps a long investigation within a fixed context, using [N]% fewer tokens. Reasoning runs on an NVIDIA Nemotron model. On ten planted incidents it finds [N]." |
| 3:10–3:20 | The run command in a terminal, then the repository page | "It runs from one command, with a full trace of every step. Built with Cursor." |

Recording notes:

- Record real runs; if a run is slow, cut the waiting but never the steps.
- Keep the trace readable: large font, one agent step per line.
- No keys, tokens or internal addresses on screen.
- Record the first question last, after the evaluation score is final.

## Slide deck — 9 slides

The organisers list: problem and target users, the solution, the agent workflow or architecture, the
technical stack, how Zetaris and Meterless were used, what was unique about the use of the sponsor
technologies, product visuals, and future enhancements.

1. **Title.** Product name, one line: "An agent that explains why a business number changed, and
   proves it." Track 02, team name.
2. **Problem and users.** A metric moves; the evidence is spread across separate systems; an analyst
   spends days joining them and still may anchor on the first plausible story. User: operations or
   commercial analyst at a marketplace.
3. **Solution.** Ask the question; get ranked causes with evidence, what was ruled out, and an honest
   "cannot be determined" when the data does not hold the answer. One screenshot of an answer.
4. **How the agents work.** Diagram: Planner, Investigator, Critic, Reporter around the shared
   evidence record, with the revision loop and the three branches (no real change, promote next
   hypothesis, cannot be determined).
5. **Technical stack.** Data layer, model layer, engines, API and page, Docker; one line each.
6. **Zetaris and Meterless in the build.** Zetaris: the four sources queried and joined in place.
   Meterless: World Model as the evidence record, Markovian as the investigation loop. One real log
   excerpt for each.
7. **What is distinctive.** The critic's refutation is visible in the trace; provenance on every
   claim; measured token saving of [N]%; the system is scored against planted incidents, [N] of 10,
   including cases where the right answer is "unknown".
8. **Product visuals.** Two or three screenshots: the live trace, an expanded evidence item, the
   "cannot be determined" answer.
9. **Limits and next steps.** What it does not do yet (limits stated plainly), then: more hypothesis
   families, scheduled monitoring that raises the question itself, write-back of findings to the
   team's tools.

## What the build must deliver for this demo

- The web page with a live trace, or the demo falls back to a terminal recording.
- The critic's refutation on the review-dip question, visible as its own step.
- The "cannot be determined" branch on the order-value question.
- The token report and the evaluation score as real numbers.
