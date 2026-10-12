from runtime.runner import Runner
from runtime.storage import Store
from runtime import background as bg

def _seed(store, scope="default"):
    # two independent episodes about the same thing -> consolidatable (>=2 sources)
    store.append(scope, "experience", "deploy uses the staging config and token rotation", "ok")
    store.append(scope, "experience", "staging config requires token rotation before deploy", "ok")
    store.append(scope, "experience", "lunch was a cheese sandwich", "ok")  # unrelated singleton

def test_consolidation_needs_two_sources_and_stays_candidate():
    s = Store(); _seed(s)
    made = bg.consolidate(s, "default")
    assert made, "a >=2-episode cluster should consolidate"
    c = next(c for c in s.claims("default") if c["id"] in made)
    assert c["status"] == "candidate"                       # proposal, not yet approved
    assert len(c["source_ids"]) >= 2                         # policy: >= 2 independent sources
    assert all(s.db.execute("select 1 from episodes where id=?", (sid,)).fetchone()
               for sid in c["source_ids"])                  # lineage resolves to real episodes

def test_no_claim_from_single_episode():
    s = Store(); s.append("default", "experience", "a lone unique fact zzz", "ok")
    assert bg.consolidate(s, "default") == []

def test_approval_is_snapshot_gated():
    s = Store(); _seed(s)
    cid = bg.consolidate(s, "default")[0]
    s.append("default", "experience", "a new later observation appears", "ok")  # store changed
    assert bg.approve_claim(s, "default", cid) is False      # must revalidate, not overwrite
    assert next(c for c in s.claims("default") if c["id"] == cid)["status"] == "candidate"

def test_contradiction_preserves_both():
    s = Store()
    a = s.propose_claim("default", "the production release label is cedar aaa111", ["x1", "x2"])
    b = s.propose_claim("default", "the production release label is cedar bbb222", ["y1", "y2"])
    flagged = bg.contradiction_review(s, "default")
    assert a in flagged and b in flagged
    byid = {c["id"]: c for c in s.claims("default")}
    assert byid[a]["status"] == "contradicted" and byid[b]["status"] == "contradicted"  # both kept + flagged

def test_contradicted_claim_cannot_be_approved():
    s = Store()
    a = s.propose_claim("default", "the production release label is cedar aaa111", ["x1", "x2"])
    s.propose_claim("default", "the production release label is cedar bbb222", ["y1", "y2"])
    bg.contradiction_review(s, "default")
    assert bg.approve_claim(s, "default", a) is False

def test_revision_supersedes_and_keeps_old():
    s = Store(); _seed(s)
    old = bg.consolidate(s, "default")[0]
    new = bg.revise_claim(s, "default", old, "corrected claim about staging deploy", ["x1", "x2"])
    byid = {c["id"]: c for c in s.claims("default")}
    assert byid[old]["status"] == "superseded"               # old revision kept, marked
    assert byid[new]["supersedes"] == old
    assert byid[new]["revision"] == byid[old]["revision"] + 1

def test_release_publish_and_rollback(tmp_path):
    s = Store(); _seed(s)
    rel = bg.Releases(str(tmp_path))
    r = bg.run_background(s, "default", releases=rel, model="stub", embed_backend="hash")
    assert r["approved"] and r["release"] == "release_0000"
    m = rel.active_manifest()
    assert m["id"] == "release_0000" and m["memory"]
    assert m["pins"]["adapter"] is None and m["pins"]["model"] == "stub"   # no weights; store-only
    rel.publish(s, "default")                                 # release_0001
    assert rel.active_manifest()["id"] == "release_0001"
    assert rel.rollback() == "release_0000"                   # repoint to previous
    assert rel.active_manifest()["id"] == "release_0000"

def test_online_loop_unaffected_by_background():
    r = Runner(); r.step("setup", "the project release label is cedar-rt42")
    bg.run_background(r.store, "default")                      # store-only; no weights to change
    assert r.store.search("default", "what release label did i give you?", 3)  # still recalls

def test_pipeline_is_repeat_safe(tmp_path):
    s = Store(); _seed(s); rel = bg.Releases(str(tmp_path))
    first = bg.run_background(s, "default", releases=rel)
    for _ in range(3):                                        # unchanged store: nothing new proposed or published
        again = bg.run_background(s, "default", releases=rel)
        assert again["claims"] == [] and again["release"] == first["release"]
    assert len(s.claims("default")) == 1 and len(list((tmp_path / "manifests").iterdir())) == 1

def test_grown_cluster_supersedes_instead_of_duplicating():
    s = Store(); _seed(s)
    first = bg.run_background(s, "default")["claims"][0]
    s.append("default", "experience", "deploy needs the staging config and token rotation", "ok")
    second = bg.run_background(s, "default")["claims"][0]
    byid = {c["id"]: c for c in s.claims("default")}
    assert byid[first]["status"] == "superseded"              # old revision kept, marked
    assert byid[second]["status"] == "approved" and byid[second]["supersedes"] == first
    assert byid[second]["revision"] == 2 and len(byid[second]["source_ids"]) == 3

def test_correction_survives_contradiction_review():
    s = Store(); _seed(s)
    old = bg.consolidate(s, "default")[0]; bg.approve_claim(s, "default", old)
    c = next(c for c in s.claims("default") if c["id"] == old)
    new = bg.revise_claim(s, "default", old, c["claim"].replace("before", "after"), c["source_ids"])
    assert bg.contradiction_review(s, "default") == []         # a correction is not a contradiction of what it replaces
    assert bg.approve_claim(s, "default", new) is True
    byid = {c["id"]: c for c in s.claims("default")}
    assert byid[old]["status"] == "superseded" and byid[new]["status"] == "approved"

def test_claim_that_only_adds_detail_is_not_a_contradiction():
    s = Store()
    s.propose_claim("default", "the production release label is cedar bbb222", ["x1", "x2"])
    s.propose_claim("default", "production release label is cedar bbb222 confirmed", ["y1", "y2"])
    assert bg.contradiction_review(s, "default") == []

def test_unresolvable_provenance_cannot_be_approved():
    s = Store()
    cid = s.propose_claim("default", "the moon is made of cheese", ["no-such-episode-1", "no-such-episode-2"])
    assert bg.approve_claim(s, "default", cid) is False
