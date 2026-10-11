"""Background consolidation pipeline (Stage 3): episodes -> semantic claims -> versioned releases.

Store-only — no model weights are touched (that is Stage 4, gated). Runs the
background stages from orchestrator/routing.yaml (replay_selector, consolidation,
contradiction_review, release_manager); learning_proposer / learning_validator
are Stage 4 and are NOT executed here.

Invariants (policies/):
- A semantic claim needs >= 2 independent source episodes (consolidation.md).
- Raw episodes are immutable; claims are separate and cite sources (evidence.md).
- Proposals are candidates until approved; approval revalidates the snapshot the
  proposal was built against, so a changed store is never silently overwritten.
- Contradictions preserve BOTH claims and their sources, flagged not deleted.
- Corrections are new revisions that supersede; the old revision is kept
  (memory_revision.md).
- Releases are versioned and published atomically via active.json; rollback
  repoints to the previous release (preserve_prior_versions).
"""
import os, re, json, time

_TOK = re.compile(r"[a-z0-9]+")
def _toks(s):
    return {w for w in _TOK.findall(s.lower()) if len(w) >= 3}

def _jaccard(a, b):
    return len(a & b) / len(a | b) if (a or b) else 0.0

# --- replay_selector: pick episodes worth revisiting, cluster near-duplicates ---
def replay_selector(store, scope, sim=0.4):
    """Cluster episodes by token overlap. Only clusters of >= 2 are consolidatable."""
    eps = store.episodes(scope)
    clusters, used = [], set()
    for i, e in enumerate(eps):
        if e["id"] in used:
            continue
        group, ti = [e], _toks(e["text"]); used.add(e["id"])
        for f in eps[i + 1:]:
            if f["id"] in used:
                continue
            if _jaccard(ti, _toks(f["text"])) >= sim:
                group.append(f); used.add(f["id"])
        if len(group) >= 2:
            clusters.append(group)
    return clusters

# --- consolidation: clusters -> semantic claim proposals (candidate) ---
def _summarize(group):
    shared = set.intersection(*[_toks(e["text"]) for e in group])
    rep = max(group, key=lambda e: len(e["text"]))["text"]
    theme = " ".join(sorted(shared)) or "episodes"
    return f"[{len(group)} episodes: {theme}] {rep}"

def consolidate(store, scope, summarize=_summarize):
    """Propose one candidate claim per cluster of >= 2 independent episodes."""
    snap = store.snapshot(scope); made = []
    for group in replay_selector(store, scope):
        sids = sorted({e["id"] for e in group})
        if len(sids) < 2:                     # policy: >= 2 independent sources
            continue
        made.append(store.propose_claim(scope, summarize(group), sids, snapshot=snap))
    return made

# --- contradiction_review: flag highly-similar-but-differing claims; preserve both ---
def contradiction_review(store, scope, sim=0.6):
    """Flag pairs of claims that share a subject but assert different specifics."""
    cs = store.claims(scope); flagged = set()
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            a, b = _toks(cs[i]["claim"]), _toks(cs[j]["claim"])
            if a != b and _jaccard(a, b) >= sim:       # same subject, differing value
                flagged.add(cs[i]["id"]); flagged.add(cs[j]["id"])
    for cid in flagged:
        store.set_claim(cid, status="contradicted")    # kept, not deleted
    return sorted(flagged)

# --- evaluation gate: approve a candidate only if still valid against its snapshot ---
def approve_claim(store, scope, claim_id):
    """Stand-in for the evaluation stage: approve iff not contradicted and the
    episodic snapshot still matches the one the proposal was built against."""
    c = next((c for c in store.claims(scope) if c["id"] == claim_id), None)
    if c is None or c["status"] == "contradicted":
        return False
    if c["snapshot"] and c["snapshot"] != store.snapshot(scope):   # store changed -> revalidate, don't overwrite
        return False
    store.set_claim(claim_id, status="approved")
    return True

# --- memory_revision: a correction supersedes an old claim as a new revision ---
def revise_claim(store, scope, old_claim_id, new_text, source_ids):
    old = next(c for c in store.claims(scope) if c["id"] == old_claim_id)
    nid = store.propose_claim(scope, new_text, source_ids, snapshot=store.snapshot(scope),
                              supersedes=old_claim_id, revision=old["revision"] + 1)
    store.set_claim(old_claim_id, status="superseded")   # old revision kept, marked
    return nid

# --- release_manager: assemble a versioned manifest of approved claims; publish via active.json ---
class Releases:
    def __init__(self, root):
        self.root = root
        self.manifests = os.path.join(root, "manifests")
        self.active = os.path.join(root, "active.json")
        os.makedirs(self.manifests, exist_ok=True)
    def _read_active(self):
        try:
            with open(self.active) as f:
                return json.load(f)
        except FileNotFoundError:
            return {"release_id": None, "previous_release": None}
    def _publish_pointer(self, rid, prev):
        tmp = self.active + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"release_id": rid, "previous_release": prev}, f)
        os.replace(tmp, self.active)              # atomic pointer swap
    def publish(self, store, scope, model=None, embed=None):
        """Pin approved claims + lineage into a new, immutable manifest and publish it."""
        prev = self._read_active().get("release_id")
        rid = "release_%04d" % sum(1 for f in os.listdir(self.manifests) if f.endswith(".json"))
        approved = store.claims(scope, status="approved")
        manifest = {
            "id": rid, "ts": time.time(), "previous_release": prev,
            "pins": {"workspace": scope, "policy": "v0.1", "model": model,
                     "adapter": None, "retrieval": embed, "permissions": "default"},
            "memory": [{"claim_id": c["id"], "claim": c["claim"], "revision": c["revision"],
                        "supersedes": c["supersedes"], "source_ids": c["source_ids"]} for c in approved],
            "source_ids": sorted({s for c in approved for s in c["source_ids"]}),
        }
        path = os.path.join(self.manifests, rid + ".json"); tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp, path)                     # atomic manifest write
        self._publish_pointer(rid, prev)
        return rid
    def rollback(self):
        """Repoint active.json to the previous release; manifests are preserved."""
        prev = self._read_active().get("previous_release")
        if not prev:
            return None
        with open(os.path.join(self.manifests, prev + ".json")) as f:
            pm = json.load(f)
        self._publish_pointer(prev, pm.get("previous_release"))
        return prev
    def active_manifest(self):
        rid = self._read_active().get("release_id")
        if not rid:
            return None
        with open(os.path.join(self.manifests, rid + ".json")) as f:
            return json.load(f)

# --- orchestration (routing.yaml background order, minus Stage-4 learning_*) ---
def run_background(store, scope, releases=None, approve=True, model=None, embed_backend=None):
    made = consolidate(store, scope)                              # replay_selector + consolidation
    contradicted = set(contradiction_review(store, scope))
    approved = [cid for cid in made
                if cid not in contradicted and approve_claim(store, scope, cid)] if approve else []
    release = releases.publish(store, scope, model=model, embed=embed_backend) if releases is not None else None
    return {"claims": made, "contradicted": sorted(contradicted), "approved": approved, "release": release}
