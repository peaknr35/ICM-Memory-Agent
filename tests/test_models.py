import pytest
from runtime.models import make_llm, _prompt
def test_default_backend_is_stub(): assert make_llm()("g","hello",[])=="ACT:hello"
def test_unknown_backend_rejected():
    with pytest.raises(ValueError): make_llm("bogus")
def test_prompt_includes_safe_evidence():
    p=_prompt("g","o",[{"text":"uv not pip","outcome":"ok"}]); assert "uv not pip" in p and "Action:" in p
