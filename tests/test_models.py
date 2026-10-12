import pytest
from runtime.models import make_llm, _prompt
def test_default_backend_is_stub(): assert make_llm()("g","hello",[])=="ACT:hello"
def test_unknown_backend_rejected():
    with pytest.raises(ValueError): make_llm("bogus")
def test_prompt_includes_safe_evidence():
    p=_prompt("g","o",[{"text":"uv not pip","outcome":"ok"}]); assert "uv not pip" in p and "Action:" in p

# --- cloud backends, exercised offline against stand-ins (no network, no keys) ---
import io, sys, types, urllib.error
from runtime import models

class _Messages:
    def __init__(self, log, resp): self.log, self.resp = log, resp
    def create(self, **kw): self.log.append(kw); return self.resp

def _fake_anthropic(monkeypatch, resp):
    log = {"beta": [], "plain": []}
    class Client:
        def __init__(self):
            self.messages = _Messages(log["plain"], resp)
            self.beta = types.SimpleNamespace(messages=_Messages(log["beta"], resp))
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Client))
    for var in ("ANTHROPIC_MODEL", "ANTHROPIC_EFFORT", "ANTHROPIC_FALLBACKS"):
        monkeypatch.delenv(var, raising=False)
    return log

def _resp(text="deploy", stop="end_turn", category=None):
    return types.SimpleNamespace(stop_reason=stop, stop_details=types.SimpleNamespace(category=category),
                                 content=[types.SimpleNamespace(type="thinking", thinking=""),
                                          types.SimpleNamespace(type="text", text=text)])

def test_claude_request_shape(monkeypatch):
    log = _fake_anthropic(monkeypatch, _resp())
    assert models.claude_llm()("g", "o", []) == "deploy"       # thinking blocks ignored, text returned
    kw = log["beta"][0]
    assert kw["model"] == "claude-opus-5-5" and kw["max_tokens"] >= 16000
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"] == {"effort": "medium"} and "thinking" not in kw and log["plain"] == []

def test_claude_fallbacks_can_be_switched_off(monkeypatch):
    log = _fake_anthropic(monkeypatch, _resp()); monkeypatch.setenv("ANTHROPIC_FALLBACKS", "off")
    models.claude_llm()("g", "o", [])
    assert log["beta"] == [] and "fallbacks" not in log["plain"][0]

def test_claude_refusal_and_empty_output_raise(monkeypatch):
    _fake_anthropic(monkeypatch, _resp(stop="refusal", category="cyber"))
    with pytest.raises(RuntimeError, match="declined.*cyber"): models.claude_llm()("g", "o", [])
    _fake_anthropic(monkeypatch, _resp(text="", stop="max_tokens"))
    with pytest.raises(RuntimeError, match="no text.*max_tokens"): models.claude_llm()("g", "o", [])

def test_http_errors_keep_the_provider_message(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error":"model gone"}'))
    monkeypatch.setattr(models.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="HTTP 404.*model gone"):
        models._post("http://localhost:11434/api/chat", {}, {})

def test_gemini_skips_thought_parts_and_reports_blocks(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(models, "_post", lambda *a, **k: {"candidates": [{"content": {"parts": [
        {"text": "hmm", "thought": True}, {"text": "deploy"}]}}]})
    assert models.gemini_llm()("g", "o", []) == "deploy"
    monkeypatch.setattr(models, "_post", lambda *a, **k: {"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(RuntimeError, match="no candidates"): models.gemini_llm()("g", "o", [])
