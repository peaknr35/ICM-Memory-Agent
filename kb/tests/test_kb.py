"""Offline tests: no Google login and no Anthropic key needed.

    python -m pytest tests -q        (or)   python tests/test_kb.py
"""
import base64
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import connectors  # noqa: E402
import kb  # noqa: E402
import kbcore  # noqa: E402
import summarize  # noqa: E402

CFG = kbcore.load_config()


def tmpdb():
    return kbcore.connect(Path(tempfile.mkdtemp()) / "t.sqlite")


def b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def msg(mid, subject, body, days_ago=1, frm="alex@example.com"):
    ms = int((datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp() * 1000)
    return {"id": mid, "internalDate": str(ms), "snippet": body[:50], "payload": {
        "mimeType": "multipart/alternative",
        "headers": [{"name": "Subject", "value": subject}, {"name": "From", "value": frm},
                    {"name": "To", "value": "nati@example.com"}, {"name": "Date", "value": "x"}],
        "parts": [{"mimeType": "text/plain", "body": {"data": b64(body)}}]}}


class FakeGmail:
    def __init__(self, threads):
        self.threads_ = threads
        self.gets = 0

    def users(self):
        return self

    def threads(self):
        return self

    def list(self, **kw):
        refs = [{"id": t["id"], "historyId": t["historyId"]} for t in self.threads_]
        return SimpleNamespace(execute=lambda: {"threads": refs})

    def get(self, userId, id, format):
        self.gets += 1
        t = next(t for t in self.threads_ if t["id"] == id)
        return SimpleNamespace(execute=lambda: t)


def test_masking():
    s = ("key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV and ANTHROPIC_API_KEY=sk-ant-xyz1234567890abc "
         "password: hunter2pass ghp_" + "a" * 36 + " postgres://bob:s3cretpw@db:5432/x AKIAABCDEFGHIJKLMNOP")
    out = kbcore.mask_secrets(s)
    for leaked in ("ABCDEFGHIJKLMNOPQRSTUV", "hunter2pass", "a" * 36, "s3cretpw", "AKIAABCDEFGHIJKLMNOP", "xyz1234567890"):
        assert leaked not in out, (leaked, out)
    assert "ANTHROPIC_API_KEY" in out and "password" in out  # names kept, values masked
    assert kbcore.mask_secrets("normal text about tasks") == "normal text about tasks"


def test_sensitive_email_filter():
    assert kbcore.is_sensitive_email("Reset your password", "")
    assert kbcore.is_sensitive_email("Your sign-in code", "")
    assert kbcore.is_sensitive_email("Hi", "Your verification code is 123456")
    assert not kbcore.is_sensitive_email("Lunch Friday?", "Want to grab lunch?")


def test_gmail_ingest_idempotent_and_safe():
    db = tmpdb()
    threads = [
        {"id": "t1", "historyId": "10", "messages": [msg("m1", "Andon Assistant demo", "Demo is Friday at 2pm."),
                                                     msg("m2", "Re: Andon Assistant demo", "Sounds good.\nOn Mon x wrote:\n> old")]},
        {"id": "t2", "historyId": "11", "messages": [msg("m3", "Reset your password", "click here")]},
        {"id": "t3", "historyId": "12", "messages": [msg("m4", "Long thread", ("n8n webhook detail. " * 600))]},
    ]
    fake = FakeGmail(threads)
    connectors._gmail_service = lambda account: fake
    r1 = connectors.ingest_gmail(db, CFG)
    assert r1["items"] == 2 and r1["skipped_sensitive"] == 1
    n1 = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    r2 = connectors.ingest_gmail(db, CFG)          # unchanged historyIds -> nothing fetched
    assert r2["unchanged"] == 3 and db.execute("SELECT COUNT(*) FROM docs").fetchone()[0] == n1
    threads[0]["historyId"] = "99"                 # thread changed -> replaced, not duplicated
    connectors.ingest_gmail(db, CFG)
    assert db.execute("SELECT COUNT(*) FROM docs WHERE source_id='personal:t1'").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM docs WHERE title LIKE '%password%'").fetchone()[0] == 0
    raw = db.execute("SELECT COUNT(*) FROM docs WHERE source_id='personal:t3' AND kind='raw'").fetchone()[0]
    assert raw >= 3
    row = db.execute("SELECT content, metadata FROM docs WHERE source_id='personal:t1'").fetchone()
    assert "> old" not in row["content"] and json.loads(row["metadata"])["url"].startswith("https://mail.google.com")


def test_claude_session_parse(tmp=None):
    d = Path(tempfile.mkdtemp()) / "projects" / "-home-nati-andon"
    d.mkdir(parents=True)
    f = d / "abc.jsonl"
    lines = [
        {"type": "user", "timestamp": "2026-10-10T01:00:00Z", "cwd": "/home/nati/andon", "sessionId": "abc",
         "message": {"role": "user", "content": "<system-reminder>noise</system-reminder>fix the docker build"}},
        {"type": "assistant", "timestamp": "2026-10-10T01:01:00Z", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Running the build."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "docker compose up --build"}}]}},
        {"type": "user", "timestamp": "2026-10-10T01:02:00Z", "message": {"role": "user", "content": [
            {"type": "tool_result", "is_error": True, "content": "ERROR: failed to solve: python:3.13-slim not found"}]}},
    ]
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    item = connectors.parse_session(f)
    assert item["title"] == "[andon] fix the docker build"
    assert "noise" not in item["content"] and "$ docker compose up --build" in item["content"]
    assert "[tool error] ERROR: failed to solve" in item["content"]
    assert item["ts"] == "2026-10-10T01:02:00Z" and item["metadata"]["path"] == str(f)
    db = tmpdb()
    cfg = json.loads(json.dumps(CFG))
    cfg["sources"]["claude_code"]["projects_dir"] = str(d.parent)
    assert connectors.ingest_claude_code(db, cfg)["items"] == 1
    assert connectors.ingest_claude_code(db, cfg)["unchanged"] == 1


def _add(db, sid, title, content, days_ago, kind="email"):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    kbcore.replace_rows(db, "gmail", sid, [dict(kind=kind, ts=ts, title=title, content=content, metadata={"url": "u"})])


def test_search_recency_and_superseded():
    db = tmpdb()
    _add(db, "old", "router config decision", "we chose ollama for the model router", 400)
    _add(db, "new", "router config decision", "we chose ollama for the model router", 2)
    res = kb.search(db, "model router ollama", cfg=CFG)
    assert [e["row"]["source_id"] for e in res] == ["new", "old"]
    new_id = db.execute("SELECT id FROM docs WHERE source_id='new'").fetchone()[0]
    old_id = db.execute("SELECT id FROM docs WHERE source_id='old'").fetchone()[0]
    db.execute("UPDATE docs SET superseded_by=? WHERE id=?", (old_id, new_id))
    res = kb.search(db, "model router ollama", cfg=CFG)
    assert res[0]["row"]["source_id"] == "old"
    assert kb.search(db, "model router", after="2026-01-01", cfg=CFG)  # filter path works
    assert kb.fts_query('what is "sk-ant" error: No module named x.y?') .count("OR") >= 3


def test_summarizer_with_fake_haiku():
    db = tmpdb()
    long = "[user] fix ModuleNotFoundError: No module named 'googleapiclient'\n" + ("detail " * 2000)
    rows = kbcore.item_rows("session", "2026-10-01T00:00:00Z", "[kb] gmail fix", long, {"path": "/x.jsonl"}, 6000)
    kbcore.replace_rows(db, "claude_code", "s1", rows)
    assert len(summarize.pending(db, CFG)) == 1
    assert summarize.estimate(db, CFG)["items"] == 1

    class FakeMsgs:
        def create(self, **kw):
            assert "<document>" in kw["messages"][0]["content"]
            data = {"segments": [{"title": "Gmail client import error", "question": "how did I fix googleapiclient import",
                                  "summary": "Installed google-api-python-client."}],
                    "atoms": [{"type": "error_fix", "text": "ModuleNotFoundError: No module named 'googleapiclient'. Fix: pip install google-api-python-client"}]}
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=data)],
                                   usage=SimpleNamespace(input_tokens=5000, output_tokens=300))

    summarize._client = lambda: SimpleNamespace(messages=FakeMsgs())
    rep = summarize.run(db, CFG)
    assert rep["summarized"] == 1 and rep["failed"] == 0
    assert summarize.pending(db, CFG) == []
    kinds = {r[0] for r in db.execute("SELECT kind FROM docs WHERE source_id='s1'")}
    assert {"segment", "atom", "raw", "session"} <= kinds
    top = kb.search(db, "googleapiclient", cfg=CFG)[0]
    assert top["row"]["kind"] in ("atom", "segment")


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok ", fn.__name__)
    print(f"{len(fns)} tests passed")
