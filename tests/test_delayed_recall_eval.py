from runtime.runner import Runner
from evals.delayed_recall.scenario import delayed_recall, pattern_separation, extract_label

def test_delayed_recall_across_reset():
    label="cedar-rt42x9"; res=delayed_recall(label=label)
    assert res["ep1"] in res["evidence_ids"]                                  # (1) retrieved within budget
    assert res["answer"]==label                                               # (2) exact label reproduced
    assert any(row and row[0]==res["ep1"] for row in res["resolved"])         # (3) evidence resolves to interaction 1
    assert res["route"]!="parameter_learning_candidate"                       # (5) no training triggered
    assert res["store"].db.execute("select count(*) from derived").fetchone()[0]==0  # (5) no semantic commit
    res["store"].delete(res["ep1"])                                           # (4) remove the memory...
    r=Runner(store=res["store"]); r.llm=extract_label
    assert r.step("recall","what release label did i give you?")=="unknown"   # ...and recall returns unknown, not a guess

def test_pattern_separation():
    res=pattern_separation()
    assert res["answer"]=="cedar-bbb222"        # right near-duplicate
    assert res["b"] in res["evidence_ids"]
