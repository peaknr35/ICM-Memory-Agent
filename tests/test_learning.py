from runtime.storage import Store
from runtime import background as bg, learning as L

def _gap(**over):
    g = dict(repeated_capability_gap="users keep asking for X we can't do",
             baselines_tested=True, validated_examples=["ex1", "ex2", "ex3"],
             data_authorized=True, heldout="heldout_set_v1", rollback_target="release_0000",
             recipe="lora_default")
    g.update(over); return g

def test_eligibility_blocks_until_all_prereqs(tmp_path):
    lr = L.Learning(str(tmp_path))
    r = L.propose_training(lr, _gap(data_authorized=False))        # unauthorized data
    assert not r["ok"] and "data_authorized" in r["failed"] and r["proposal"] is None
    assert "heldout_eval" in L.propose_training(lr, _gap(heldout=None))["failed"]
    assert "validated_examples" in L.propose_training(lr, _gap(validated_examples=["ex1"]))["failed"]
    assert "rollback_target" in L.propose_training(lr, _gap(rollback_target=None))["failed"]
    assert "baselines_tested" in L.propose_training(lr, _gap(baselines_tested=False))["failed"]
    assert "no_repeated_capability_gap" in L.propose_training(lr, _gap(repeated_capability_gap=""))["failed"]

def test_proposal_when_all_prereqs_met(tmp_path):
    lr = L.Learning(str(tmp_path))
    r = L.propose_training(lr, _gap())
    assert r["ok"] and r["proposal"]
    p = lr.get_proposal(r["proposal"])
    assert p["status"] == "candidate" and len(p["source_ids"]) >= 2 and p["rollback_target"] == "release_0000"

def test_training_produces_adapter_with_lineage_no_weights(tmp_path):
    lr = L.Learning(str(tmp_path)); pid = L.propose_training(lr, _gap())["proposal"]
    aid = L.train_adapter(lr, pid); a = lr.get_adapter(aid)
    assert a["status"] == "trained" and a["source_ids"] == ["ex1", "ex2", "ex3"]
    assert a["artifact"]["weights"] is None                        # skeleton: no real weights trained

def test_validator_gates_on_heldout_and_is_separate(tmp_path):
    lr = L.Learning(str(tmp_path))
    aid = L.train_adapter(lr, L.propose_training(lr, _gap())["proposal"])
    assert L.validate_adapter(lr, aid, lambda a: {"score": 0.70, "baseline": 0.80, "regressions": True}) is False
    assert lr.get_adapter(aid)["status"] == "rejected"             # regression -> rejected
    aid2 = L.train_adapter(lr, L.propose_training(lr, _gap())["proposal"])
    assert L.validate_adapter(lr, aid2, lambda a: {"score": 0.90, "baseline": 0.80, "regressions": False}) is True
    assert lr.get_adapter(aid2)["status"] == "validated"           # improves, no regression -> validated

def test_deploy_requires_approval_and_validation(tmp_path):
    lr = L.Learning(str(tmp_path / "L")); rel = bg.Releases(str(tmp_path / "R")); s = Store()
    rel.publish(s, "default")                                      # release_0000 baseline, adapter None
    aid = L.train_adapter(lr, L.propose_training(lr, _gap())["proposal"])
    assert L.deploy_adapter(lr, rel, s, "default", aid, approved=True)["reason"] == "not_validated"
    L.validate_adapter(lr, aid, lambda a: {"score": 0.90, "baseline": 0.80, "regressions": False})
    assert L.deploy_adapter(lr, rel, s, "default", aid, approved=False)["reason"] == "approval_required"
    d = L.deploy_adapter(lr, rel, s, "default", aid, approved=True)
    assert d["ok"] and rel.active_manifest()["pins"]["adapter"] == aid

def test_rollback_reverts_adapter_pin(tmp_path):
    lr = L.Learning(str(tmp_path / "L")); rel = bg.Releases(str(tmp_path / "R")); s = Store()
    rel.publish(s, "default")                                      # release_0000: adapter None
    aid = L.train_adapter(lr, L.propose_training(lr, _gap())["proposal"])
    L.validate_adapter(lr, aid, lambda a: {"score": 0.90, "baseline": 0.80, "regressions": False})
    L.deploy_adapter(lr, rel, s, "default", aid, approved=True)    # release_0001: adapter=aid
    assert rel.active_manifest()["pins"]["adapter"] == aid
    rel.rollback()
    assert rel.active_manifest()["pins"]["adapter"] is None        # reverted to pre-adapter release

def test_delete_retires_adapter(tmp_path):
    lr = L.Learning(str(tmp_path))
    aid = L.train_adapter(lr, L.propose_training(lr, _gap(validated_examples=["epA", "epB"]))["proposal"])
    retired = L.retire_adapters_for(lr, "epA")
    assert aid in retired and lr.get_adapter(aid)["status"] == "retired"
