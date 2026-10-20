"""Background consolidation pipeline (Stage 3): episodes -> semantic claims -> versioned releases.

Store-only — no model weights are touched (that is Stage 4, gated). Runs the
background stages from orchestrator/routing.yaml (replay_selector, consolidation,
contradiction_review, release_manager); learning_proposer / learning_validator
are Stage 4 and are NOT executed here.

Invariants (policies/):
- A semantic claim needs >= 2 independent source episodes (consolidation.md).
- Raw episodes are immutable; claims are separate and cite sources (evidence.md).
- Proposals are candidates until approved; approval requires provenance that
  resolves to live episodes and revalidates the snapshot the proposal was built
  against, so a changed store is never silently overwritten.
- KB evidence is cited by pointer (`kb_refs`, e.g. "kb:gmail:<thread>"), never copied.
  A claim's `source_ids` stay episodes only, so the >= 2 episodes rule and the delete
  cascade are unchanged. A claim citing KB rows is approved only if every pointer
  still resolves; a missing one blocks approval but never deletes the claim —
  that is a human decision (evidence_report shows what is missing).
- Contradictions preserve BOTH claims and their sources, flagged not deleted.
- Corrections are new revisions that supersede; the old revision is kept
  (memory_revision.md).
- Releases are versioned and published atomically via active.json; rollback
  repoints to the previous release (preserve_prior_versions).
- The pipeline is repeat-safe: re-running it on an unchanged store proposes
  nothing new and publishes nothing new.
"""
import os, re, json, time
from .kb_retriever import is_kb_id

_TOK = re.compile(r"[a-z0-9]+")
_STOP = frozenset("the and for with that this are was were has have had not but you your our its "
                  "from into about than then".split())
def _toks(s):
    return {w for w in _TOK.findall(s.lower()) if len(w) >= 3 and w not in _STOP}

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
    """Propose one candidate claim per cluster of >= 2 independent episodes.

    Repeat-safe: a cluster that already has a live claim is skipped, and a cluster
    that has grown since its claim was made is proposed as a new revision that
    supersedes the old one (memory_revision.md) instead of a duplicate."""
    snap = store.snapshot(scope); made = []
    live = [c for c in store.claims(scope) if c["status"] != "superseded"]
    for group in replay_selector(store, scope):
        sids = {e["id"] for e in group}
        if len(sids) < 2:                                          # policy: >= 2 independent sources
            continue
        if any(set(c["source_ids"]) == sids for c in live):        # already claimed
            continue
        grown = [c for c in live if set(c["source_ids"]) < sids]   # same cluster, more evidence now
        old = max(grown, key=lambda c: c["revision"]) if grown else None
        kb_refs = {r for e in group for r in e["source_ids"] if is_kb_id(r)}   # KB rows the episodes cited
        made.append(store.propose_claim(scope, summarize(group), sorted(sids), snapshot=snap,
                                        supersedes=old["id"] if old else None,
                                        revision=old["revision"] + 1 if old else 1,
                                        kb_refs=kb_refs | set(old["kb_refs"] if old else ())))
        for c in grown:
            store.set_claim(c["id"], status="superseded")          # kept, marked
    return made

# --- contradiction_review: flag similar claims that each assert something different; preserve both ---
def contradiction_review(store, scope, sim=0.6):
    """Flag pairs of live claims that share a subject but EACH assert something the
    other does not. Not contradictions: a claim that only adds detail to another, a
    superseded revision, and a correction paired with the claim it supersedes.

    Lexical only — it cannot see conflicts that are worded differently
    ("the api is stable" vs "the api keeps crashing"); that needs a model."""
    cs = [c for c in store.claims(scope) if c["status"] != "superseded"]
    flagged = set()
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            x, y = cs[i], cs[j]
            if x["supersedes"] == y["id"] or y["supersedes"] == x["id"]:
                continue
            a, b = _toks(x["claim"]), _toks(y["claim"])
            if (a - b) and (b - a) and _jaccard(a, b) >= sim:      # same subject, two-sided difference
                flagged.add(x["id"]); flagged.add(y["id"])
    for cid in flagged:
        store.set_claim(cid, status="contradicted")                # kept, not deleted
    return sorted(flagged)

# --- evaluation gate: approve a candidate only if still valid against its snapshot ---
def approve_claim(store, scope, claim_id, kb=None):
    """Stand-in for the evaluation stage: approve iff the claim is not contradicted,
    every source id resolves to a live episode, every KB pointer resolves in `kb`
    (no kb to check against -> not approved), and the episodic snapshot still
    matches the one the proposal was built against."""
    c = next((c for c in store.claims(scope) if c["id"] == claim_id), None)
    if c is None or c["status"] == "contradicted":
        return False
    if not store.resolves(scope, c["source_ids"]):                 # derived records need resolvable provenance
        return False
    if c["kb_refs"] and (kb is None or not all(kb.exists(r) for r in c["kb_refs"])):
        return False                                               # KB evidence missing/unverifiable: stays a candidate
    if c["snapshot"] and c["snapshot"] != store.snapshot(scope):   # store changed -> revalidate, don't overwrite
        return False
    store.set_claim(claim_id, status="approved")
    return True

def evidence_report(store, scope, claim_id, kb=None):
    """What a reviewer sees: which cited episodes / KB rows no longer resolve.
    `kb_unverified` is True when the claim cites KB rows but no kb was given to check."""
    c = next(c for c in store.claims(scope) if c["id"] == claim_id)
    live = {e["id"] for e in store.episodes(scope)}
    return {"claim_id": claim_id, "status": c["status"],
            "missing_episodes": [i for i in c["source_ids"] if i not in live],
            "missing_kb": [r for r in c["kb_refs"] if kb is not None and not kb.exists(r)],
            "kb_unverified": bool(c["kb_refs"]) and kb is None}

# --- memory_revision: a correction supersedes an old claim as a new revision ---
def revise_claim(store, scope, old_claim_id, new_text, source_ids, kb_refs=None):
    """kb_refs=None carries the old revision's KB pointers forward; pass [] to drop them."""
    old = next(c for c in store.claims(scope) if c["id"] == old_claim_id)
    nid = store.propose_claim(scope, new_text, source_ids, snapshot=store.snapshot(scope),
                              supersedes=old_claim_id, revision=old["revision"] + 1,
                              kb_refs=old["kb_refs"] if kb_refs is None else kb_refs)
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
    def publish(self, store, scope, model=None, embed=None, adapter=None):
        """Pin approved claims + lineage into a new, immutable manifest and publish it.
        `adapter` is the deployed adapter id (Stage 4) or None for a store-only release.
        If nothing changed since the active release, that release is returned as-is."""
        approved = store.claims(scope, status="approved")
        pins = {"workspace": scope, "policy": "v0.1", "model": model,
                "adapter": adapter, "retrieval": embed, "permissions": "default"}
        memory = [{"claim_id": c["id"], "claim": c["claim"], "revision": c["revision"],
                   "supersedes": c["supersedes"], "source_ids": c["source_ids"],
                   **({"kb_refs": c["kb_refs"]} if c["kb_refs"] else {})} for c in approved]  # key only when used: old manifests still compare equal
        cur = self.active_manifest()
        if cur and cur["memory"] == memory and cur["pins"] == pins:
            return cur["id"]                      # identical content: don't mint a duplicate release
        prev = self._read_active().get("release_id")
        rid = "release_%04d" % sum(1 for f in os.listdir(self.manifests) if f.endswith(".json"))
        manifest = {"id": rid, "ts": time.time(), "previous_release": prev, "pins": pins, "memory": memory,
                    "source_ids": sorted({s for c in approved for s in c["source_ids"]})}
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
def run_background(store, scope, releases=None, approve=True, model=None, embed_backend=None, kb=None):
    made = consolidate(store, scope)                              # replay_selector + consolidation
    contradicted = set(contradiction_review(store, scope))
    approved = [cid for cid in made
                if cid not in contradicted and approve_claim(store, scope, cid, kb)] if approve else []
    release = releases.publish(store, scope, model=model, embed=embed_backend) if releases is not None else None
    return {"claims": made, "contradicted": sorted(contradicted), "approved": approved, "release": release}
