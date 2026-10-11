# ICM Memory Agent

A working skeleton for an agent that gets better at a job **by managing its own memory**, not by being retrained every time — built as an Interpretable Context Methodology (ICM) workspace where the folder tree *is* the architecture. Agent folders define behavior; `runtime/` enforces it.

## Purpose

Most "learning" agents jump straight to fine-tuning. This project takes the opposite default: the cheap, reversible move — **write the experience down and recall it later** — comes first, and expensive, irreversible **parameter learning** (training an adapter) is the gated exception. The central question it answers is *how should an agent decide to learn?*

- **Working context** — throwaway, session-only state.
- **Persistent memory** — the default for durable facts, authorized preferences, observed outcomes, and validated procedures.
- **Parameter learning** — only on a *repeated capability gap*, and only after safety prerequisites are met (baselines tested, validated examples, authorized data, a held-out eval, a rollback target). Runs in the background; deployment needs approval.

Two safety ideas run throughout: retrieved memory is **evidence, never instructions** (a poisoned memory can't hijack the agent), and everything is **scoped** to a user/project/session and **deletable** — removing an episode also removes any derived claim that cited it.

## How it works

Every turn runs one online loop (`runtime/runner.py`): `observe → retrieve → reason_and_act → evaluate → store`.

1. **observe** — capture goal + observation into working context.
2. **retrieve** — pull candidate memories, scoped to this user/project/session, as evidence.
3. **reason_and_act** — a model (stub / Ollama / Claude / Gemini) picks the next action from goal + observation + *safe* evidence.
4. **evaluate** — score the outcome.
5. **store** — route it: temporary → working context; durable → persistent memory; nothing to training by default.

Retrieved items are marked untrusted; any that match known prompt-injection cues are filtered out before reaching the model. Each step records which evidence it used.

## Layout — what's in it

| Path | Purpose |
|------|---------|
| `agents/` | **11 agents** — 5 online (`observe`, `retrieve`, `reason_and_act`, `evaluate`, `memory_writer`), 6 background (`replay_selector`, `consolidation`, `contradiction_review`, `learning_proposer`, `learning_validator`, `release_manager`). Each is a folder with `identity.md`, `rules.md`, `examples.md`, `handoff.md`. |
| `orchestrator/` | `routing.yaml` sets stage order; `adaptation_policy.yaml` makes persistent memory the default and gates parameter learning. |
| `contracts/` | 7 JSON schemas for the objects passed between stages. |
| `policies/` | 7 policies: evidence, trust boundaries, memory revision, consolidation, training eligibility, release & rollback, retention & deletion. |
| `releases/` | `active.json` points at the active memory release; `manifests/` holds versioned releases. |
| `runtime/` | The Python enforcement layer (below). |

## Runtime (v0.1)

- **`runtime/storage.py`** — SQLite episodic store with scoped, bounded retrieval (vector/embedding by default, keyword fallback); deleting an episode cascades to derived claims that cite it.
- **`runtime/router.py`** — temporary items → working context, everything else → persistent memory; a training candidate only when repeated capability gap + working retrieval + authorized data all hold.
- **`runtime/runner.py`** — runs the loop, filters untrusted evidence, records the evidence trail.
- **`runtime/models.py`** — pluggable reasoning backends behind one `llm(goal, obs, evidence)` interface.
- **`runtime/embeddings.py`** — pluggable embedding backends behind one `embed(text) -> list[float]` interface.
- **`runtime/background.py`** — the Stage-3 background pipeline: consolidation, contradiction review, revisions/lineage, and versioned releases (store-only, no weights).
- **`runtime/learning.py`** — the Stage-4 adapter-training pipeline: the gated path to *weight* changes (diagnosis → proposal → train → validate → approval-gated deploy → rollback).

## Model backends

Default is the dependency-free `stub` (used by the tests — no network, no keys). Backends resolve their key/client on first call, so selecting one never fails at construction. Select via `MEMORY_LLM_BACKEND` (or `Runner(backend=...)`, or inject `Runner(llm=make_llm(...))`):

```
MEMORY_LLM_BACKEND=ollama   # local; set OLLAMA_MODEL (default llama3.2), OLLAMA_HOST
MEMORY_LLM_BACKEND=claude   # pip install 'icm-agent[claude]'; set ANTHROPIC_API_KEY (model claude-opus-5-5)
MEMORY_LLM_BACKEND=gemini   # set GEMINI_API_KEY (model gemini-2.0-flash)
```

## Embedding backends (retrieval)

Retrieval ranks memories by embedding cosine similarity. Default is the dependency-free **`hash`** embedder (pure Python, offline, deterministic). Select via `MEMORY_EMBED_BACKEND` (or `Runner(embed_backend=...)`, or `Store(embedder=make_embedder(...))`):

```
MEMORY_EMBED_BACKEND=hash     # default; no deps, offline, deterministic
MEMORY_EMBED_BACKEND=keyword  # legacy whole-word overlap scorer (no vectors)
MEMORY_EMBED_BACKEND=ollama   # local; set OLLAMA_EMBED_MODEL (default nomic-embed-text)
MEMORY_EMBED_BACKEND=gemini   # set GEMINI_API_KEY (model text-embedding-004)
MEMORY_EMBED_BACKEND=voyage   # set VOYAGE_API_KEY (model voyage-3)
MEMORY_EMBED_BACKEND=sentence-transformers  # pip install 'icm-agent[embeddings]'
```

The `hash` default is **structural** — it matches on shared surface tokens (like keyword, but as vectors), so it's a deterministic offline stand-in that exercises the full vector-retrieval path. **Semantic / paraphrase recall** (matching a cue to a fact with no shared words) needs a real backend above. There is no `claude` embedder: Anthropic has no embeddings API, so `voyage` is the Anthropic-ecosystem choice.

## Quick start

```
pip install pytest
pytest
```

**25 tests, all passing.** They cover the online loop (delayed recall, temporary items *not* stored, injection filtering, scope isolation, complete deletion with derived-claim cascade), the llm/embedder backends and prompt construction, the delayed-recall + pattern-separation evals below, the background pipeline (consolidation ≥2 sources, snapshot-gated approval, contradiction preservation, revision lineage, release publish + rollback), and the Stage-4 training gate (eligibility, validation, approval-gated deploy, rollback, retire-on-delete).

## Evaluations

`evals/delayed_recall/` holds the first milestone: **traceable recall across a context reset**. Run by `pytest` (`tests/test_delayed_recall_eval.py`), offline on the `hash` embedder.

- **Delayed recall** — store a randomized `cedar-<suffix>` fact, run unrelated turns, then reset to a fresh agent context keeping only the persistent store, and ask for the label. It passes only if retrieval returns the fact within the evidence budget, the exact label is reproduced, the answer's evidence reference resolves back to the originating episode, deleting that episode yields `"unknown"` (not a guess), and no semantic/weight update occurs merely because the fact was retrieved.
- **Pattern separation** — two near-duplicate labels; the cue must retrieve the *right* one.

## Background pipeline

`runtime/background.py` runs the background stages asynchronously over a snapshot of the store — it only changes the store, never model weights. Call `run_background(store, scope, releases=Releases(dir))`. Stages, in `routing.yaml` order:

1. **replay_selector** — cluster episodes worth revisiting by token overlap.
2. **consolidation** — turn each cluster of **≥2 independent episodes** into a *candidate* semantic claim that cites its sources (per `policies/consolidation.md`). Raw episodes stay immutable; claims are a separate layer.
3. **contradiction_review** — flag pairs of claims that share a subject but assert different specifics; **both are preserved** (status `contradicted`), never silently overwritten.
4. **evaluation gate** (`approve_claim`) — a candidate becomes `approved` only if it isn't contradicted **and** the episodic snapshot still matches the one it was built against (a changed store forces revalidation). `revise_claim` records corrections as new revisions that `supersede` the old one, which is kept (`policies/memory_revision.md`).
5. **release_manager** (`Releases`) — pin the approved claims + lineage into an immutable, versioned manifest (`manifests/release_NNNN.json`) and publish it atomically via `active.json`; `rollback()` repoints to the previous release. Manifests pin workspace/policy/memory/model/adapter/retrieval/permissions — `adapter` is always `null` here (weights are Stage 4).

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

## Status & limits

- The default `llm` is a stub; the Ollama/Claude/Gemini backends are wired but not exercised by the tests.
- The default embedder (`hash`) is structural, not semantic: it matches shared tokens, so paraphrase/synonym recall needs a real embedding backend (ollama/gemini/voyage/sentence-transformers).
- The background pipeline (`runtime/background.py`) is implemented but runs **on demand** (`run_background`), not auto-triggered by the online loop. Consolidation summaries are deterministic (token theme + representative episode), not model-written; approval is a stand-in for the evaluation stage (accept valid, non-contradicted candidates).
- Approved semantic claims and published releases are not yet wired back into online retrieval — the online loop still retrieves from the episodic store only.
- The Stage-4 pipeline implements the training **governance** (gate, proposal, validation, approval-gated deploy, rollback, retire-on-delete), but the trainer is a stub — no real adapter weights are produced. A real LoRA/PEFT trainer would be a pluggable `MEMORY_TRAIN_BACKEND`.
- `memory_writer` is specified as an agent, but the runner currently appends episodes directly.
- Placeholders still to fill: each agent's `examples.md`, the real fields in the `contracts/` schemas, and `project/identity.md`.
