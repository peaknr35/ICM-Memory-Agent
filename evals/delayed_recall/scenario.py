"""Delayed-recall evaluation (Stage 1).

Proves traceable recall across a context reset, using the default offline hash
embedder. A thin eval-only "answerer" (`extract_label`) reproduces the label
from the TOP retrieved evidence, isolating memory retrieval from LLM generation
— with a real backend the model would answer instead. Grounding: indexing
theory (evidence pointers resolve to content), CLS (bounded fast recall),
pattern separation (the near-duplicate variant).
"""
import re
from runtime.runner import Runner

_LABEL = re.compile(r"cedar-\S+")

def extract_label(goal, obs, evidence):
    """Eval llm: return the label found in the top retrieved evidence, else 'unknown'."""
    for e in evidence:
        m = _LABEL.search(e["text"])
        if m:
            return m.group(0)
    return "unknown"

def delayed_recall(label="cedar-rt42x9", budget=3, embed_backend=None):
    """Store a fact, run unrelated turns, reset context, recall across the reset."""
    r = Runner(embed_backend=embed_backend, budget=budget)
    ep1 = r.store.append(r.scope, "experience", f"the project release label is {label}", "ok")  # interaction 1
    r.step("chitchat", "the weather today is mild")       # interaction 2
    r.step("chitchat", "lunch was a cheese sandwich")     # interaction 3
    # context reset: fresh agent context, same persistent store, retain only the query
    r2 = Runner(store=r.store, embed_backend=embed_backend, budget=budget)
    r2.llm = extract_label
    answer = r2.step("recall", "what release label did i give you?")  # interaction 4
    trace = r2.trace[-1]
    resolved = [r2.store.db.execute("SELECT id FROM episodes WHERE id=?", (eid,)).fetchone()
                for eid in trace["evidence_ids"]]
    return {"ep1": ep1, "answer": answer, "evidence_ids": trace["evidence_ids"],
            "route": trace["route"], "resolved": resolved, "store": r2.store}

def pattern_separation(budget=3, embed_backend=None):
    """Two near-duplicate labels; the cue must retrieve the RIGHT one (paper 7)."""
    r = Runner(embed_backend=embed_backend, budget=budget)
    r.store.append(r.scope, "experience", "the staging release label is cedar-aaa111", "ok")
    b = r.store.append(r.scope, "experience", "the production release label is cedar-bbb222", "ok")
    r2 = Runner(store=r.store, embed_backend=embed_backend, budget=budget)
    r2.llm = extract_label
    answer = r2.step("recall", "what is the production release label?")
    return {"b": b, "answer": answer, "evidence_ids": r2.trace[-1]["evidence_ids"]}
