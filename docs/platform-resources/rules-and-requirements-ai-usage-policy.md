# AI Usage Policy

Folder: Rules and Requirements · updated 2026-09-30

# AI Usage Policy

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**

This policy covers how you may use AI tools during the hackathon and what your submitted project must be honest about.

The short version: build with AI as heavily as you like, then submit something real. Everything below follows from that.

> Where this policy and the Official Rules on the event page disagree, the Official Rules apply.

---

## 1. Policy Summary

**Allowed, and encouraged:**

- Any model provider, including closed-source models and paid APIs
- Any agent framework
- AI-assisted coding, vibe coding, debugging, testing and documentation
- Partner technologies from Zetaris, NVIDIA, Cursor and Meterless

**Not allowed:**

- Hardcoded outputs presented as agent results
- Fabricated logs or traces
- Plagiarised code, content, data or another team's work
- Committed API keys or secrets
- A README that claims more than the system does
- A single agent or a fixed chain presented as something it is not

---

## 2. Model and Framework Choice Is Open

There is no mandated model provider. Use what fits the problem.

| You may use | Examples |
|---|---|
| **Closed-source models** | Any commercial model API |
| **Open-weight models** | Hosted or run locally |
| **Paid APIs** | Any, at your own cost |
| **Any agent framework** | LangGraph, CrewAI, AutoGen, the OpenAI Agent SDK, LangChain, LlamaIndex, a custom stack |
| **Partner technologies** | Zetaris, NVIDIA, Cursor, Meterless |

The framework itself is not scored. Agent behaviour, technical implementation, product quality and impact are.

**Sponsor Tech is worth 10 points**, so document where each partner technology fits. Use the layers that genuinely help rather than bolting one on at the end.

[TBC: any provider restrictions set by section 5 of the Official Rules, "What you can use".]

---

## 3. What Is Allowed

### 3.1 AI inside your agent

Use AI models for whatever your solution needs: reasoning, planning, task decomposition, summarisation, classification, retrieval-augmented generation, embeddings, transcription, report generation, evaluation and critique agents, planner ↔ executor ↔ evaluator loops, multi-agent review and escalation.

### 3.2 AI-assisted coding

Cursor, Copilot, Claude Code, chat assistants, IDE autocomplete, AI debugging and test generation are all fine. Use them to scaffold the repository, generate boilerplate, design APIs, debug, refactor, write tests, create Dockerfiles, draft the README.

**You remain responsible for all submitted code.** Generated code must be reviewed, tested and understood by your team. Judges may ask how something works, and "the AI wrote it" is not an answer.

### 3.3 Vibe coding

Encouraged as a prototyping workflow. Move from idea to working prototype as fast as you can.

It does not excuse non-compliance. The submission still needs to run from a clean setup, show how the agent worked, and include the required components.

### 3.4 AI-assisted documentation

Draft your README, architecture notes, agent descriptions, setup instructions, demo script, comments and limitations with AI if you want.

Documentation may be AI-assisted, but it must be accurate. Do not claim capabilities your system does not have.

### 3.5 AI-assisted prompt engineering

System prompts, role prompts, evaluation prompts, critique prompts, routing prompts, retry and fallback prompts, retrieval query prompts. All fine.

### 3.6 AI-assisted testing

Test cases, synthetic inputs, edge cases, expected outputs, evaluation rubrics, failure-mode checklists. Synthetic examples are allowed, but label them where they appear in documentation or examples.

---

## 4. What Is Not Allowed

### 4.1 Hardcoded outputs

A hardcoded output is anything pre-written to look like an agent result without being produced by real execution.

**Prohibited:**

- Returning the same answer regardless of input
- Matching a known sample input and returning a pre-written output
- Storing final answers in files and presenting them as generated
- Writing logs that simulate collaboration that never happened
- Detecting a judge's input and behaving differently
- Faking model calls and returning static text
- Hardcoding an "agent debate" transcript

**Allowed:**

- Small static configuration files
- Prompt templates
- Example input and output files for documentation
- Cached sample data for reproducibility
- A documented `SAMPLE_MODE=true` for offline testing

The default mode of your submission must run real agent logic.

### 4.2 Fabricated logs

Logs are how judges verify your agent did the work. They must reflect actual execution.

Do not hand-write traces, generate a plausible-looking trace file, or edit real logs to look better than the run was. A trace that does not match the code is worse than no trace.

### 4.3 Plagiarism

Do not submit another participant's work, another team's repository, code from private sources without permission, proprietary code you are not authorised to use, open-source code in breach of its licence, or documentation and diagrams copied without attribution.

Open-source libraries and public examples are fine. Comply with their licences and attribute where required.

### 4.4 Misrepresentation

Do not overclaim. Prohibited examples:

- Claiming real-time data when only static samples are used
- Claiming agents collaborate when they run in a fixed chain
- Claiming a model was fine-tuned when only a prompt was used
- Claiming an API is integrated when the output is mocked
- Claiming production readiness without disclosing limitations

Be honest about limits. An accurate limitations section reads as confidence. Judges check, and overclaiming costs more than the gap it hides.

### 4.5 Secrets

Never commit an API key, token, password or credential.

**Required:**

- Environment variables for everything sensitive
- `.env.example` with placeholders only
- `.env` in `.gitignore`
- No secrets printed in logs
- No secrets visible in screenshots or the demo video

If a real key ever reached a commit, rotate it rather than deleting the commit.

---

## 5. Cost and Access

You choose your providers, so you carry the cost of any paid API you use, unless a partner provides credits for the event.

Two practical consequences:

- **Judges may not have your keys.** Ship a documented sample mode so someone can see the system work without your credentials.
- **Rate limits and outages happen mid-judging.** Handle failure gracefully rather than crashing.

[TBC: any credits or free access provided by partners are published in their resource areas on HackOS.]

---

## 6. Disclosure

You do not need to log every prompt you typed into a coding assistant.

Your README should disclose:

1. Model providers and models used
2. Agent frameworks used
3. Partner technologies used, and where
4. External tools and libraries
5. Data sources, and whether any data is sample or synthetic
6. Any open-source code or templates materially adapted
7. Known limitations
8. Fallback or sample-mode behaviour

Recommended section:

```markdown
## AI and Model Usage

Models:
- [provider/model] for agent reasoning and summarisation
- [provider/model] for evaluator-agent reasoning
- [provider/model] for retrieval embeddings

Partner technology:
- Zetaris — [what it does in this build]
- NVIDIA — [what it does in this build]
- Cursor — [what it does in this build]
- Meterless — [what it does in this build]

Development tools:
- AI-assisted coding tools were used for scaffolding, debugging and documentation.
- All generated code was reviewed and tested by the team.

Sample mode:
- SAMPLE_MODE=true runs on cached sample data with no external calls.
```

---

## 7. Configuration

Use environment variables, never hardcoded credentials.

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ.get("OPENAI_BASE_URL")
)
```

And ship a `.env.example`:

```bash
# Model provider
OPENAI_API_KEY=your-api-key-here
OPENAI_BASE_URL=https://api.your-provider.example/v1
MODEL_NAME=your-default-model
EMBEDDING_MODEL=your-embedding-model

# Partner services
ZETARIS_API_KEY=your-key-here
NVIDIA_API_KEY=your-key-here
METERLESS_API_KEY=your-key-here

# Runtime
SAMPLE_MODE=false
LOG_LEVEL=INFO
```

---

## 8. Logs as Evidence

Your logs should show:

- Which agent acted, and in what role
- What it received and what it produced
- Which agent got the handoff
- Critique, validation, retry, escalation or refinement
- Whether model calls succeeded or failed
- Any fallback or sample-mode behaviour

Recommended fields:

```json
{
  "timestamp": "2026-10-18T18:42:00Z",
  "agent_name": "EvaluatorAgent",
  "action": "critique_output",
  "input_summary": "Reviewed the reconciliation across three supplier sources.",
  "output_summary": "Flagged an unsupported resolution for Supplier C and requested a re-check.",
  "target_agent": "ReconcilerAgent",
  "model": "[provider/model]",
  "status": "success",
  "retry_count": 0
}
```

---

## 9. Open Source and Third-Party Code

**You may use:** open-source libraries, public framework examples, starter templates, public documentation snippets, public datasets under appropriate licences.

**You must:** respect licences, keep copyright notices, attribute material code you copied or adapted, avoid private or proprietary code without permission, and make sure your team's own contribution is substantial.

Recommended section:

```markdown
## Third-Party Code and Licences

- FastAPI — MIT
- LangGraph — MIT
- [library] — [licence]

Substantially adapted code is noted in comments or documentation.
```

---

## 10. Data Integrity

AI assistance does not override data rules.

- Data sources must be public or properly licensed
- Data loading should be automated
- No private or sensitive data
- No personally identifiable information
- Synthetic data labelled as such
- Public datasets cited

Do not use AI tools to invent citations, fabricate data provenance or create benchmark results that were never run.

---

## 11. How Compliance Is Checked

Reviewers may check during repository inspection, execution, log review, demo review, technical evaluation and judge Q&A.

They may look for: hardcoded outputs, static or fabricated logs, suspiciously identical outputs across different inputs, committed secrets, missing or misleading disclosures, plagiarised code or documentation, missing attribution, and a gap between what the README claims and what the code does.

---

## 12. Disqualification Triggers

A submission may be disqualified if:

- Outputs are hardcoded or fake
- Logs are fabricated
- Code, content or documentation is plagiarised
- API keys or secrets are committed
- The README materially misrepresents what the system does
- The team cannot explain how their own solution works
- Unauthorised private, personal or restricted data is included

[TBC: the full disqualification conditions are in the Official Rules.]

---

## 13. Checklist

- [ ] No real API keys or secrets are committed
- [ ] `.env.example` is included, with placeholders only
- [ ] Outputs are generated by real agent logic, not hardcoded
- [ ] Logs reflect actual execution
- [ ] Agent roles are distinct and they interact more than once
- [ ] AI-assisted code has been reviewed and tested by the team
- [ ] Every team member can explain how the system works
- [ ] Open-source code and datasets are attributed
- [ ] The README accurately describes models, tools, data and limitations
- [ ] Sample mode, if included, is documented and works
- [ ] The project runs from a clean setup

---

## 14. The Principle

Use AI to move faster, think better, test more thoroughly and document more clearly.

The submission itself must be:

- **Yours** — you can explain and defend it
- **Executable** — it runs from a clean setup
- **Honest** — the README matches the code
- **Transparent** — the traces match the run
- **Reproducible** — someone else gets the same result
- **Secure** — no secrets, no unauthorised data

Build with AI. Submit with integrity.
