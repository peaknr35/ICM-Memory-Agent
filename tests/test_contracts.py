import pytest
from runtime.contracts import validate, schema
from runtime.runner import Runner

def _good():
    return Runner().observe("the release label is cedar-1")

def test_runner_observations_satisfy_the_contract():
    assert validate("observation", _good()) == []

@pytest.mark.parametrize("mutate,needle", [
    (lambda o: o.pop("session_id"), "session_id: required"),
    (lambda o: o["source"].__setitem__("kind", "narrator"), "source.kind"),
    (lambda o: o.__setitem__("extra", 1), "extra: unexpected field"),
    (lambda o: o.__setitem__("observed_at", "yesterday"), "observed_at"),
    (lambda o: o.__setitem__("content", ""), "content"),
    (lambda o: o.__setitem__("interaction_index", -1), "interaction_index"),
    (lambda o: o["provenance"].__setitem__("evidence_ids", ["a", "a"]), "evidence_ids"),
    (lambda o: o.__setitem__("schema_version", "2.0"), "schema_version"),
])
def test_violations_are_reported(mutate, needle):
    o = _good(); mutate(o); errs = validate("observation", o)
    assert errs and any(needle in e for e in errs)

def test_agrees_with_the_jsonschema_package_when_installed():
    js = pytest.importorskip("jsonschema")
    if not hasattr(js, "Draft202012Validator"):
        pytest.skip("jsonschema too old for draft 2020-12")
    ref = js.Draft202012Validator(schema("observation"))
    cases = [_good()]
    for f in (lambda o: o.pop("id"), lambda o: o["source"].__setitem__("kind", "x"),
              lambda o: o.__setitem__("extra", 1), lambda o: o.__setitem__("content", ""),
              lambda o: o.__setitem__("interaction_index", "0"), lambda o: o.pop("provenance")):
        o = _good(); f(o); cases.append(o)
    for o in cases:
        assert (validate("observation", o) == []) == ref.is_valid(o)
