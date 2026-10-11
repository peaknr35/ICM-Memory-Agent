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

**10 tests, all passing.** They check delayed recall, temporary items *not* being stored, injection filtering, scope isolation, complete deletion (with derived-claim cascade), the default llm/embedder backends, unknown-backend rejection, prompt construction, and the delayed-recall + pattern-separation evals below.

## Evaluations

`evals/delayed_recall/` holds the first milestone: **traceable recall across a context reset**. Run by `pytest` (`tests/test_delayed_recall_eval.py`), offline on the `hash` embedder.

- **Delayed recall** — store a randomized `cedar-<suffix>` fact, run unrelated turns, then reset to a fresh agent context keeping only the persistent store, and ask for the label. It passes only if retrieval returns the fact within the evidence budget, the exact label is reproduced, the answer's evidence reference resolves back to the originating episode, deleting that episode yields `"unknown"` (not a guess), and no semantic/weight update occurs merely because the fact was retrieved.
- **Pattern separation** — two near-duplicate labels; the cue must retrieve the *right* one.

## Roadmap / build order

1. Online loop — **done** (v0.1: SQLite episodic store, injection filter).
2. Real reasoning backends — **done** (stub/ollama/claude/gemini); retrieval embeddings — **done** (hash/keyword/ollama/gemini/voyage/sentence-transformers in `runtime/embeddings.py`).
3. Background pipeline — consolidation + lineage + versioned memory releases.
4. Adapter training pipeline — gated by `policies/training_eligibility.md`.

## Status & limits

- The default `llm` is a stub; the Ollama/Claude/Gemini backends are wired but not exercised by the tests.
- The default embedder (`hash`) is structural, not semantic: it matches shared tokens, so paraphrase/synonym recall needs a real embedding backend (ollama/gemini/voyage/sentence-transformers).
- The background agents, consolidation, lineage, and training pipeline exist as folders and policies but aren't executed by the runner yet.
- `memory_writer` is specified as an agent, but the runner currently appends episodes directly.
- Placeholders still to fill: each agent's `examples.md`, the real fields in the `contracts/` schemas, and `project/identity.md`.
