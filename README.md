# ICM Memory Agent

A working skeleton for an agent that gets better at a job **by managing its own memory**, not by being retrained every time — built as an Interpretable Context Methodology (ICM) workspace where the folder tree *is* the architecture. Agent folders define behavior; `runtime/` enforces it.

## Purpose

Most "learning" agents jump straight to fine-tuning. This project takes the opposite default: the cheap, reversible move — **write the experience down and recall it later** — comes first, and expensive, irreversible **parameter learning** (training an adapter) is the gated exception. The central question it answers is *how should an agent decide to learn?*

- **Working context** — throwaway, session-only state.
- **Persistent memory** — the default for durable facts, authorized preferences, observed outcomes, and validated procedures.
- **Parameter learning** — only on a *repeated capability gap*, and only after safety prerequisites are met (baselines tested, validated examples, authorized data, a held-out eval, a rollback target). Runs in the background; deployment needs approval.

Two safety ideas run throughout: retrieved memory is treated as **evidence, never instructions** (the prompt says so, and a simple phrase filter drops the most obvious injected commands — a mitigation, not a guarantee), and everything is **scoped** to a user/project/session and **deletable** — removing an episode also removes any derived claim that cited it.

## How it works

Every turn runs one online loop (`runtime/runner.py`): `observe → retrieve → reason_and_act → evaluate → store`.

1. **observe** — normalize the input into an Observation record (what was said, by whom, in which session) that satisfies `contracts/observation.schema.json`.
2. **retrieve** — pull candidate memories, scoped to this user/project/session, as evidence.
3. **reason_and_act** — a model (stub / Ollama / Claude / Gemini) picks the next action from goal + observation + *safe* evidence.
4. **evaluate** — score the outcome.
5. **store** — hand the observation to `memory_writer`, the single write gate. Facts are appended to the episodic store; questions, exact repeats within a session, temporary items and invalid observations are not. Nothing goes to training by default.

Retrieved items are marked untrusted, and any that contain a short list of known injection phrases are dropped before reaching the model. The trace records the evidence used and what was dropped. The phrase list is easy to reword around, so treat it as a first line of defence only.

## Layout — what's in it

| Path | Purpose |
|------|---------|
| `agents/` | **11 agents** — 5 online (`observe`, `retrieve`, `reason_and_act`, `evaluate`, `memory_writer`), 6 background (`replay_selector`, `consolidation`, `contradiction_review`, `learning_proposer`, `learning_validator`, `release_manager`). Each is a folder with `identity.md`, `rules.md`, `examples.md`, `handoff.md`. |
| `orchestrator/` | `routing.yaml` sets stage order; `adaptation_policy.yaml` makes persistent memory the default and gates parameter learning. |
| `contracts/` | 7 JSON schemas for the objects passed between stages. `observation` and `memory_proposal` are full schemas enforced at the write gate; the other five are still stubs. |
| `policies/` | 7 policies: evidence, trust boundaries, memory revision, consolidation, training eligibility, release & rollback, retention & deletion. |
| `releases/` | `active.json` points at the active memory release; `manifests/` holds versioned releases. |
| `runtime/` | The Python enforcement layer (below). |

## Runtime (v0.1)

- **`runtime/storage.py`** — SQLite episodic store with scoped, bounded retrieval (vector/embedding by default, keyword fallback); deleting an episode cascades to derived claims that cite it.
- **`runtime/router.py`** — temporary items → working context, everything else → persistent memory; a training candidate only when repeated capability gap + working retrieval + authorized data all hold.
- **`runtime/runner.py`** — runs the loop, builds the observation, filters untrusted evidence, records the evidence trail.
- **`runtime/memory_writer.py`** — the single write gate for the episodic store: validates the observation, decides append or skip, and writes idempotently (the episode id is the observation id).
- **`runtime/contracts.py`** — validates records against `contracts/*.schema.json`; the schema files are the source of truth.
- **`runtime/check.py`**, **`runtime/env.py`** — `python -m runtime.check` reports which backends are ready; `env.py` loads a local `.env`.
- **`runtime/models.py`** — pluggable reasoning backends behind one `llm(goal, obs, evidence)` interface.
- **`runtime/embeddings.py`** — pluggable embedding backends behind one `embed(text) -> list[float]` interface.
- **`runtime/background.py`** — the Stage-3 background pipeline: consolidation, contradiction review, revisions/lineage, and versioned releases (store-only, no weights).
- **`runtime/learning.py`** — the Stage-4 adapter-training pipeline: the gated path to *weight* changes (diagnosis → proposal → train → validate → approval-gated deploy → rollback).

## Model backends

Default is the dependency-free `stub` (used by the tests — no network, no keys). Backends resolve their key/client on first call, so selecting one never fails at construction. Select via `MEMORY_LLM_BACKEND` (or `Runner(backend=...)`, or inject `Runner(llm=make_llm(...))`):

```
MEMORY_LLM_BACKEND=ollama   # local; set OLLAMA_MODEL (default llama3.2), OLLAMA_HOST
MEMORY_LLM_BACKEND=claude   # pip install anthropic; set ANTHROPIC_API_KEY (model claude-opus-5-5)
MEMORY_LLM_BACKEND=gemini   # set GEMINI_API_KEY (model gemini-3.8-flash)
```

The Claude backend opts into Anthropic's server-side refusal fallback by default (a request declined by a safety classifier is re-run on the recommended fallback model); set `ANTHROPIC_FALLBACKS=off` to disable it. A refusal or an empty reply raises an error instead of returning an empty action.

## Embedding backends (retrieval)

Retrieval ranks memories by embedding cosine similarity. Default is the dependency-free **`hash`** embedder (pure Python, offline, deterministic). Select via `MEMORY_EMBED_BACKEND` (or `Runner(embed_backend=...)`, or `Store(embedder=make_embedder(...))`):

```
MEMORY_EMBED_BACKEND=hash     # default; no deps, offline, deterministic
MEMORY_EMBED_BACKEND=keyword  # legacy whole-word overlap scorer (no vectors)
MEMORY_EMBED_BACKEND=ollama   # local; set OLLAMA_EMBED_MODEL (default nomic-embed-text)
MEMORY_EMBED_BACKEND=gemini   # set GEMINI_API_KEY (model gemini-embedding-001)
MEMORY_EMBED_BACKEND=voyage   # set VOYAGE_API_KEY (model voyage-4)
MEMORY_EMBED_BACKEND=sentence-transformers  # pip install sentence-transformers
```

The `hash` default is **structural** — it matches on shared surface tokens (like keyword, but as vectors), so it's a deterministic offline stand-in that exercises the full vector-retrieval path. **Semantic / paraphrase recall** (matching a cue to a fact with no shared words) needs a real backend above. There is no `claude` embedder: Anthropic has no embeddings API, so `voyage` is the Anthropic-ecosystem choice.

## Setting up real backends

1. Copy `.env.example` to `.env` and fill in the keys you use, or set them as environment variables. `.env` is gitignored; real environment variables win over it.
2. Install `anthropic` if you use Claude. Gemini, Voyage and Ollama need no extra packages.
3. Run `python -m runtime.check` to see what is ready. Add `--live` to make one tiny real call per ready backend. Key values are never printed.

Cloud backends send the goal, the observation and the recalled memories to the provider. Use Ollama if the data has to stay on the machine.

## Quick start

```
pip install pytest
pytest
```

To install the package from a clone: `pip install -e .` (or `pip install -e ".[claude]"` to include the Claude SDK). The package is not published on PyPI.

**59 tests, all passing, all offline.** They cover the online loop (delayed recall, temporary items *not* stored, injection filtering, scope isolation, complete deletion with derived-claim cascade), the write gate and its contracts, the llm/embedder backends (cloud backends against stand-ins, not the real services), the readiness check, the delayed-recall + pattern-separation evals below, the background pipeline (consolidation ≥2 sources, repeat-safety, snapshot- and provenance-gated approval, contradiction preservation, revision lineage, release publish + rollback), and the Stage-4 training gate (eligibility, validation, approval-gated deploy, rollback, retire-on-delete).

## Evaluations

`evals/delayed_recall/` holds the first milestone: **traceable recall across a context reset**. Run by `pytest` (`tests/test_delayed_recall_eval.py`), offline on the `hash` embedder.

- **Delayed recall** — store a randomized `cedar-<suffix>` fact, run unrelated turns, then reset to a fresh agent context keeping only the persistent store, and ask for the label. It passes only if retrieval returns the fact within the evidence budget, the exact label is reproduced, the answer's evidence reference resolves back to the originating episode, deleting that episode yields `"unknown"` (not a guess), and no semantic/weight update occurs merely because the fact was retrieved.
- **Pattern separation** — two near-duplicate labels; the cue must retrieve the *right* one.

## Background pipeline

`runtime/background.py` runs the background stages asynchronously over a snapshot of the store — it only changes the store, never model weights. Call `run_background(store, scope, releases=Releases(dir))`. Stages, in `routing.yaml` order:

1. **replay_selector** — cluster episodes worth revisiting by token overlap.
2. **consolidation** — turn each cluster of **≥2 independent episodes** into a *candidate* semantic claim that cites its sources (per `policies/consolidation.md`). Raw episodes stay immutable; claims are a separate layer. It is repeat-safe: a cluster that already has a claim is skipped, and a cluster that has grown becomes a new revision that supersedes the old claim.
3. **contradiction_review** — flag pairs of claims that share a subject but each assert something the other does not; **both are preserved** (status `contradicted`), never silently overwritten. A claim that only adds detail, and a correction paired with the claim it replaces, are not flagged. The check is lexical, so conflicts worded differently are missed.
4. **evaluation gate** (`approve_claim`) — a candidate becomes `approved` only if it isn't contradicted, every source id resolves to a live episode, **and** the episodic snapshot still matches the one it was built against (a changed store forces revalidation). `revise_claim` records corrections as new revisions that `supersede` the old one, which is kept (`policies/memory_revision.md`).
5. **release_manager** (`Releases`) — pin the approved claims + lineage into an immutable, versioned manifest (`manifests/release_NNNN.json`) and publish it atomically via `active.json`; `rollback()` repoints to the previous release. Publishing when nothing has changed returns the current release instead of minting a copy. Manifests pin workspace/policy/memory/model/adapter/retrieval/permissions — `adapter` is always `null` here (weights are Stage 4).

`learning_proposer` / `learning_validator` (adapter training) are Stage 4, below.

## Adapter training (Stage 4 — the gated path to weight changes)

`runtime/learning.py` is the **only** path that changes model weights, and it is heavily gated. This stage implements the *governance*; the actual training is a pluggable stub (`stub_trainer` emits an adapter manifest with `weights: null` — no real LoRA/PEFT run in this skeleton).

1. **diagnosis** (`diagnose`) — the 5-question gate from `policies/training_eligibility.md` / `adaptation_policy.yaml`: a true repeated capability gap, context+retrieval **baselines tried first** (memory before weights), validated examples, authorized data, a held-out eval, and a rollback target. All must pass.
2. **learning_proposer** (`propose_training`) — writes a candidate `TrainingProposal` with data lineage **only if** the diagnosis passes; otherwise it refuses and returns the failed prerequisites.
3. **train_adapter** — background-only; produces an adapter manifest (fingerprint + `source_ids` lineage, `weights: null`).
4. **learning_validator** (`validate_adapter`) — runs a held-out eval with a **separate** evaluator (the trainer never grades its own work); `validated` only if it improves without regressions, else `rejected`.
5. **deploy_adapter** — **approval-required**: refuses unless the adapter is validated *and* `approved=True`, then publishes a new release pinning the adapter (the previous release is the rollback target). `Releases.rollback()` reverts the adapter pin.
6. **retire_adapters_for** — `policies/retention_and_deletion.md`: deleting training data retires any adapter trained on it (needs retrain).

## Roadmap / build order

1. Online loop — **done** (v0.1: SQLite episodic store, injection filter).
2. Real reasoning backends — **done** (stub/ollama/claude/gemini); retrieval embeddings — **done** (hash/keyword/ollama/gemini/voyage/sentence-transformers in `runtime/embeddings.py`).
3. Background pipeline — **done** (consolidation, contradiction review, revisions + lineage, versioned releases + rollback in `runtime/background.py`; store-only).
4. Adapter training pipeline — **done** as governance (`runtime/learning.py`: eligibility gate, proposal, validation, approval-gated deploy, rollback, retire-on-delete); the trainer itself is a stub (no real weights trained).

5. Next — a minimum-similarity cutoff and per-vector embedder tagging for real embedders; approved claims and releases wired into online retrieval; a cadence trigger for the background pipeline.

## Status & limits

**Backends**
- The default `llm` is a stub. Of the real backends, only Ollama embeddings (`nomic-embed-text`) have been run against the live service. Claude, Gemini, Voyage and the Ollama chat path are tested against stand-ins only.
- The default embedder (`hash`) is structural, not semantic: it matches shared tokens, and about 8% of texts with no words in common still score above zero.
- A real embedder scores almost every pair above zero (unrelated text measured 0.35–0.42 with `nomic-embed-text`, a true paraphrase 0.58), so retrieval returns a full evidence budget even when nothing relevant is stored. There is no minimum-similarity cutoff yet.
- Vectors are not tagged with the embedder that produced them. Switching embedders on an existing store silently returns nothing.

**Memory and safety**
- `memory_writer` treats only text ending in `?` as a question. Questions phrased without one are stored.
- The injection filter is a three-phrase list and is easy to reword around.
- Deleting an episode removes it and its derived claims from the store, but a release manifest published earlier still contains the derived text.
- Scope is a string parameter, not an access control. There is no encryption and no persistent audit log (the trace lives in memory).

**Pipelines**
- The background pipeline runs **on demand** (`run_background`), not triggered by the online loop. Consolidation summaries are deterministic (token theme + representative episode), not model-written; approval is a stand-in for the evaluation stage.
- Approved semantic claims and published releases are not yet wired back into online retrieval, so a rollback changes no behaviour.
- The Stage-4 pipeline implements the training **governance**, but the trainer is a stub and the eligibility gate checks flags the caller supplies, not the underlying data. A retired adapter stays pinned until a new release is published.
- `runtime/` enforces the `observation` and `memory_proposal` contracts, but it does not read `routing.yaml`, `adaptation_policy.yaml` or the agent markdown; stage order is written in Python.
- Placeholders still to fill: `examples.md` for `observe`, `reason_and_act` and `evaluate`, and the five stub schemas in `contracts/`.
