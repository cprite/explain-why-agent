# Product tour: what the software looks like

A plain description of the product as designed on 19 Oct 2026, before the build window. The design
itself is in `architecture.md`; the numbers in the sketches below are illustrations, not results.

The agent is a data detective for a business analyst. It notices when a business number moves
unusually, works out why, and shows its evidence. It is one web page with three views; behind it are
four databases joined through Zetaris and four AI agents.

## 1. The board

```
┌──────────────────────────────────────────────────────────────┐
│  Explain-Why · Olist shop            sources: 4 ● connected  │
├──────────────┬──────────────┬──────────────┬─────────────────┤
│ Orders       │ Review score │ Delivery cost│ Payment mix     │
│ 1,176 /day   │ 4.1 ★        │ R$ 22        │ card 74%        │
│ ~~~~/\~~~    │ ~~~~~\__~~   │ ~~~~~~/~~    │ ~~~~~~~~~       │
├──────────────┴──────────────┴──────────────┴─────────────────┤
│ ⚠ Flagged by the scanner                                     │
│  ● Watches · review score −38% · Jan 2018      [ Explain ]   │
│  ● Rio de Janeiro · delivery cost +41% · Aug   [ Explain ]   │
│  ● Minas Gerais · boleto share −60% · Mar      [ Explain ]   │
│                                                              │
│  Or ask your own: [ Why did ... ?                    ] [Go]  │
└──────────────────────────────────────────────────────────────┘
```

Metric tiles with small trend lines. The anomaly scanner has already flagged unusual moves as cards,
each with an "Explain" button. The user can also type their own question.

## 2. The live investigation

After "Explain", the agents' work appears step by step:

```
 Planner       5 possible causes: late deliveries, one bad seller,
               price change, product mix, review spam
 Investigator  Query → orders × reviews (via Zetaris)  0.8 s, 412 rows
               Late deliveries for watches: 9% → 31%  ✔ supports
 Investigator  Query → payments × orders               ✘ no change
 Critic        "Seller cause not proven, only 40 orders" → re-check
 Investigator  Seller 7c3a: 62% of watch orders, rating 1.6  ✔
 Reporter      writing the answer…
```

Each query shows which databases it joined and how long it took. When the Critic rejects something,
that is visible too.

## 3. The answer

```
 Why did watch review scores fall in January 2018?

 1. Late deliveries (high confidence)               [evidence ▾]
    31% of watch orders late vs 9% normally; late orders rate 1.9★
 2. One seller (medium confidence)                  [evidence ▾]
    Seller 7c3a shipped 62% of watch orders; its rating fell to 1.6

 Ruled out:  price change · payment problems · marketing campaign
 Can't tell: whether the seller's courier changed (no courier data)
 Check next: contact seller 7c3a; delivery times by carrier
 measured = numbers from queries · inferred = agent's reasoning
```

"Evidence" opens the exact query, the numbers and the normal baseline. Every statement is marked as
measured or inferred.

## Under the hood

```
 Browser page ──► our app (Python service)
                    ├─ Anomaly scanner (fixed calculations, no AI)
                    ├─ 4 agents: Planner → Investigator ⇄ Critic → Reporter
                    │      └─ model: NVIDIA Nemotron, with Meterless's engine methods
                    └─ Data access ──► Zetaris (on AWS) ──► 4 databases:
                                                   orders · payments · reviews · marketing
```

Two ways to run it:

- **Full mode:** Zetaris on AWS and the live model.
- **Sample mode:** any laptop, no accounts. A local copy of the data and recorded model answers.
  This is how judges and testers run it.

An evaluation report in the repository shows how many of the ten planted incidents the agent finds
on its own, and how many the scanner flags. That number leads the video and the slides.
