from runtime import check

def test_status_reports_readiness_without_leaking_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test-DO-NOT-PRINT")
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    rows = {(k, n): (ok, d) for k, n, ok, d in check.status(ollama=False)}
    assert rows[("llm", "stub")][0] and rows[("embed", "hash")][0]
    assert rows[("llm", "gemini")][0] is True and rows[("embed", "voyage")][0] is False
    assert "DO-NOT-PRINT" not in repr(rows)

def test_main_never_prints_key_values(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-DO-NOT-PRINT")
    monkeypatch.setattr(check, "_ollama_models", lambda host: None)
    assert check.main([]) == 0
    out = capsys.readouterr().out
    assert "ANTHROPIC_API_KEY set" in out and "DO-NOT-PRINT" not in out

def test_live_scrubs_keys_from_error_messages(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "sk-test-DO-NOT-PRINT")
    def broken(name):
        def embed(text):
            raise RuntimeError("rejected key sk-test-DO-NOT-PRINT")
        return embed
    monkeypatch.setattr(check, "make_embedder", broken)
    res = check.live([("embed", "voyage", True, "")])
    assert res[0][2] is False and "DO-NOT-PRINT" not in res[0][3] and "***" in res[0][3]

def test_live_skips_offline_and_unready_backends():
    assert check.live([("llm", "stub", True, ""), ("embed", "hash", True, ""), ("llm", "gemini", False, "")]) == []
