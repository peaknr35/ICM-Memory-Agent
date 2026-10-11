"""Adapter training pipeline (Stage 4): the GATED path to changing model weights.

This stage implements the *governance* of weight changes, which is what the
policies are about. The actual training is a pluggable, un-run stub here: the
trainer emits an adapter manifest (fingerprint + data lineage) with
`weights: null` — no real LoRA/PEFT run (no base model/GPU/key in this skeleton).

Flow (orchestrator/routing.yaml background stages, Stage 4 only):
  diagnose -> propose_training (learning_proposer) -> train_adapter (background)
  -> validate_adapter (learning_validator, SEPARATE evaluator) -> deploy_adapter
  (approval_required, publishes a release pinning the adapter) -> rollback.

Policy (policies/training_eligibility.md, orchestrator/adaptation_policy.yaml):
training is allowed only after the 5-question diagnosis passes — a true repeated
capability gap, context+retrieval baselines tried first, validated examples,
authorized data, a held-out eval, and a rollback target. Deployment needs human
approval. Deleting training data retires the adapter (policies/retention_and_deletion.md).
"""
import os, json, time, uuid, hashlib

MIN_EXAMPLES = 2

def diagnose(gap):
    """learning_proposer's 5-question diagnosis. Returns (eligible, failed_reasons)."""
    failed = []
    if not gap.get("repeated_capability_gap"):
        failed.append("no_repeated_capability_gap")          # memory-first: only a true, repeated gap
    if not gap.get("baselines_tested"):
        failed.append("baselines_tested")                    # context + retrieval must be tried first
    if len(gap.get("validated_examples") or []) < MIN_EXAMPLES:
        failed.append("validated_examples")
    if not gap.get("data_authorized"):
        failed.append("data_authorized")
    if not gap.get("heldout"):
        failed.append("heldout_eval")
    if not gap.get("rollback_target"):
        failed.append("rollback_target")
    return (not failed, failed)

class Learning:
    """On-disk registry for training proposals and adapter manifests (default learning/)."""
    def __init__(self, root):
        self.proposals = os.path.join(root, "proposals")
        self.adapters = os.path.join(root, "adapters")
        os.makedirs(self.proposals, exist_ok=True)
        os.makedirs(self.adapters, exist_ok=True)
    def _write(self, d, rec):
        path = os.path.join(d, rec["id"] + ".json"); tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(rec, f, indent=2)
        os.replace(tmp, path)
        return rec["id"]
    def _read(self, d, rid):
        with open(os.path.join(d, rid + ".json")) as f:
            return json.load(f)
    def _list(self, d):
        out = []
        for fn in os.listdir(d):
            if fn.endswith(".json"):
                with open(os.path.join(d, fn)) as f:
                    out.append(json.load(f))
        return out
    def save_proposal(self, rec): return self._write(self.proposals, rec)
    def save_adapter(self, rec): return self._write(self.adapters, rec)
    def get_proposal(self, pid): return self._read(self.proposals, pid)
    def get_adapter(self, aid): return self._read(self.adapters, aid)
    def adapters_list(self): return self._list(self.adapters)

def propose_training(learning, gap):
    """learning_proposer: propose training ONLY for a gap that passes the diagnosis."""
    eligible, failed = diagnose(gap)
    if not eligible:
        return {"ok": False, "failed": failed, "proposal": None}
    rec = {"id": "proposal_" + uuid.uuid4().hex[:8], "ts": time.time(), "status": "candidate",
           "capability_gap": gap["repeated_capability_gap"],
           "source_ids": sorted(gap["validated_examples"]),
           "recipe": gap.get("recipe", "lora_default"),
           "heldout": gap["heldout"], "rollback_target": gap["rollback_target"],
           "data_authorized": True}
    learning.save_proposal(rec)
    return {"ok": True, "failed": [], "proposal": rec["id"]}

def stub_trainer(proposal):
    """Deterministic stand-in: an adapter ARTIFACT (manifest), not real weights."""
    fp = hashlib.md5(("|".join(proposal["source_ids"]) + proposal["recipe"]).encode()).hexdigest()[:12]
    return {"fingerprint": fp, "weights": None}   # weights=None: no real training in this skeleton

def make_trainer(backend=None):
    backend = backend or os.getenv("MEMORY_TRAIN_BACKEND", "stub")
    if backend == "stub":
        return stub_trainer
    raise ValueError(f"unknown trainer {backend!r}; only 'stub' is implemented "
                     "(real LoRA/PEFT training is a pluggable backend, out of scope here)")

def train_adapter(learning, proposal_id, trainer=None):
    """background_only: produce an adapter from an eligible candidate proposal."""
    p = learning.get_proposal(proposal_id)
    if p["status"] != "candidate":
        return None
    art = (trainer or make_trainer())(p)
    rec = {"id": "adapter_" + uuid.uuid4().hex[:8], "ts": time.time(), "status": "trained",
           "proposal_id": proposal_id, "source_ids": p["source_ids"], "recipe": p["recipe"],
           "rollback_target": p["rollback_target"], "artifact": art}
    learning.save_adapter(rec)
    learning.save_proposal({**p, "status": "trained"})
    return rec["id"]

def validate_adapter(learning, adapter_id, evaluator):
    """learning_validator: held-out eval + regression check. The evaluator is SEPARATE
    from the trainer — the producer never grades its own work. `evaluator(adapter)`
    returns {"score", "baseline", "regressions"}. Validated iff it improves, no regression."""
    a = learning.get_adapter(adapter_id)
    res = evaluator(a)
    ok = (res["score"] > res["baseline"]) and not res.get("regressions")
    learning.save_adapter({**a, "status": "validated" if ok else "rejected", "eval": res})
    return ok

def deploy_adapter(learning, releases, store, scope, adapter_id, approved=False, model=None, embed=None):
    """Deployment is approval_required: refuse unless the adapter is validated AND approved.
    On deploy, publish a NEW release pinning the adapter; the previous release is the rollback target."""
    a = learning.get_adapter(adapter_id)
    if a["status"] not in ("validated", "deployed"):
        return {"ok": False, "reason": "not_validated"}
    if not approved:
        return {"ok": False, "reason": "approval_required"}
    rid = releases.publish(store, scope, model=model, embed=embed, adapter=adapter_id)
    learning.save_adapter({**a, "status": "deployed", "release": rid})
    return {"ok": True, "release": rid, "adapter": adapter_id}

def retire_adapters_for(learning, deleted_source_id):
    """retention_and_deletion: an adapter trained on deleted data is retired (needs retrain)."""
    retired = []
    for a in learning.adapters_list():
        if deleted_source_id in a.get("source_ids", []) and a["status"] != "retired":
            learning.save_adapter({**a, "status": "retired"})
            retired.append(a["id"])
    return retired
