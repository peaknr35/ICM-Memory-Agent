"""Connectors: one function per source. Stage 01 of the pipeline.

Every connector:
  * pulls only what is new since its watermark in `ingest_state`
  * stamps every row with a date (`ts`)
  * is idempotent: it calls replace_rows(), which deletes an item's old rows first
  * keeps a pointer to the original in metadata ("url" or "path")

A connector returns a small dict report: {"items": n_written, "skipped": n, ...}.
To add a source, write one more `ingest_<name>(db, cfg)` function and register
it in CONNECTORS at the bottom. Nothing else needs to change.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import kbcore
from kbcore import get_state, item_rows, replace_rows, set_state, to_iso

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


# =============================================================== Gmail (read-only)
def _gmail_service(account: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token = kbcore.SECRETS / f"gmail_token_{account}.json"
    if not token.exists():
        raise RuntimeError(f"no Gmail login for '{account}'. Run: python gmail_auth.py {account}")
    creds = Credentials.from_authorized_user_file(str(token), GMAIL_SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip()


def _mail_body(payload: dict) -> str:
    """Prefer text/plain; fall back to stripped text/html."""
    plain, htm = [], []

    def walk(p):
        mt = p.get("mimeType", "")
        data = (p.get("body") or {}).get("data")
        if data and not (p.get("filename")):
            txt = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
            (plain if mt == "text/plain" else htm if mt == "text/html" else []).append(txt)
        for c in p.get("parts") or []:
            walk(c)

    walk(payload)
    return "\n".join(plain) if plain else _strip_html("\n".join(htm))


def _strip_quoted(body: str) -> str:
    """Drop the quoted history ("On ... wrote:" + '>' lines) — it repeats earlier messages."""
    out = []
    for line in body.splitlines():
        if re.match(r"^\s*On .{5,200}wrote:\s*$", line) or line.startswith("-----Original Message"):
            break
        if not line.startswith(">"):
            out.append(line)
    return "\n".join(out).strip()


def thread_to_item(thread: dict, account: str) -> dict | None:
    """Convert one Gmail API thread (format=full) into an item dict, or None if it must be skipped."""
    msgs = thread.get("messages") or []
    if not msgs:
        return None
    parts, subject, last_ms, people = [], "", 0, set()
    for m in msgs:
        h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
        subject = subject or h.get("subject", "")
        body = _strip_quoted(_mail_body(m.get("payload", {})) or m.get("snippet", ""))
        if kbcore.is_sensitive_email(h.get("subject", ""), body):
            return {"skip": "sensitive"}
        last_ms = max(last_ms, int(m.get("internalDate", 0)))
        people.add(h.get("from", ""))
        parts.append(f"From: {h.get('from','')}\nTo: {h.get('to','')}\nDate: {h.get('date','')}\n"
                     f"Subject: {h.get('subject','')}\n\n{body}")
    tid = thread["id"]
    return dict(
        source_id=f"{account}:{tid}",
        ts=to_iso(last_ms) if last_ms else kbcore.now_iso(),
        title=subject or "(no subject)",
        content="\n\n---\n\n".join(parts),
        metadata={
            "url": f"https://mail.google.com/mail/u/0/#all/{tid}",
            "account": account, "thread_id": tid, "messages": len(msgs),
            "from": sorted(p for p in people if p)[:5],
        },
    )


def ingest_gmail(db, cfg: dict) -> dict:
    scfg = cfg["sources"]["gmail"]
    chunk = cfg["chunking"]
    report = {"items": 0, "skipped_sensitive": 0, "unchanged": 0, "accounts": {}}
    for account in scfg.get("accounts", []):
        svc = _gmail_service(account)
        last = get_state(db, "gmail", f"{account}:last_run")
        if last:  # re-runs: only the last few days
            since = datetime.fromisoformat(last) - timedelta(days=scfg.get("rerun_overlap_days", 3))
        else:     # first run: the last 12 months
            since = datetime.now(timezone.utc) - timedelta(days=scfg.get("first_run_days", 365))
        q = f"after:{int(since.timestamp())} {scfg.get('query_extra', '')}".strip()
        started = kbcore.now_iso()
        cap = scfg.get("max_threads_per_run") or 0
        n, page = 0, None
        while True:
            resp = svc.users().threads().list(userId="me", q=q, maxResults=500, pageToken=page).execute()
            for ref in resp.get("threads", []):
                # Gmail's historyId changes whenever a thread changes: cheap "is it new?" check.
                key = f"{account}:{ref['id']}"
                if get_state(db, "gmail", f"h:{key}") == ref.get("historyId"):
                    report["unchanged"] += 1
                    continue
                thread = svc.users().threads().get(userId="me", id=ref["id"], format="full").execute()
                item = thread_to_item(thread, account)
                if item is None:
                    continue
                if item.get("skip"):
                    report["skipped_sensitive"] += 1
                    replace_rows(db, "gmail", key, [])  # make sure nothing older survives
                else:
                    rows = item_rows("email", item["ts"], item["title"], item["content"], item["metadata"],
                                     chunk["long_threshold_chars"], chunk["raw_chunk_chars"])
                    replace_rows(db, "gmail", item["source_id"], rows)
                    report["items"] += 1
                set_state(db, "gmail", f"h:{key}", ref.get("historyId"))
                n += 1
                if n % 50 == 0:
                    db.commit()
                if cap and n >= cap:
                    break
            page = resp.get("nextPageToken")
            if not page or (cap and n >= cap):
                break
        set_state(db, "gmail", f"{account}:last_run", started)
        db.commit()
        report["accounts"][account] = {"since": since.date().isoformat(), "threads_seen": n}
    return report


# ====================================================== Claude Code session transcripts
_HARNESS = re.compile(r"(?s)<(system-reminder|local-command-stdout|local-command-caveat)>.*?</\1>")


def _clean(text: str) -> str:
    """Remove harness-injected blocks (system reminders etc.) that aren't the conversation."""
    return _HARNESS.sub("", text or "").strip()


def _block_text(block, max_tool: int) -> str:
    if isinstance(block, str):
        return _clean(block)
    t = block.get("type")
    if t == "text":
        return _clean(block.get("text", ""))
    if t == "tool_use":
        inp = block.get("input") or {}
        name = block.get("name", "tool")
        if name == "Bash":
            return f"[tool Bash] $ {inp.get('command','')}"
        if name in ("Write", "Edit", "Read", "MultiEdit", "NotebookEdit"):
            extra = ""
            if name == "Edit":
                extra = f"\n  - {str(inp.get('old_string',''))[:300]}\n  + {str(inp.get('new_string',''))[:300]}"
            return f"[tool {name}] {inp.get('file_path') or inp.get('notebook_path','')}{extra}"
        return f"[tool {name}] {json.dumps(inp, ensure_ascii=False)[:max_tool]}"
    if t == "tool_result":
        c = block.get("content")
        if isinstance(c, list):
            c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
        c = str(c or "")
        tag = "[tool error]" if block.get("is_error") else "[tool result]"
        if len(c) > max_tool:
            c = c[: max_tool * 2 // 3] + "\n…[trimmed]…\n" + c[-max_tool // 3:]
        return f"{tag} {c}"
    return ""  # thinking, images, etc.


def parse_session(path: Path, max_tool: int = 1500) -> dict | None:
    """Turn one ~/.claude/projects/**/<session>.jsonl file into an item dict."""
    lines, first_ts, last_ts, cwd, branch, sid, summary, first_user = [], None, None, "", "", path.stem, "", ""
    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                continue
            typ = d.get("type")
            if typ == "summary" and d.get("summary"):
                summary = d["summary"]
            if typ not in ("user", "assistant"):
                continue
            ts = d.get("timestamp")
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
            if d.get("isMeta"):
                continue
            cwd = cwd or d.get("cwd") or ""
            branch = d.get("gitBranch") or branch
            sid = d.get("sessionId") or sid
            msg = d.get("message") or {}
            content = msg.get("content")
            blocks = [content] if isinstance(content, str) else (content or [])
            text = "\n".join(t for t in (_block_text(b, max_tool) for b in blocks) if t and t.strip())
            if not text.strip():
                continue
            role = "user" if typ == "user" else "assistant"
            if role == "user" and not first_user and not text.startswith("[tool"):
                t = re.sub(r"<[^>]+>", " ", text)
                t = re.sub(r'@"?([^"\s]+[/\\])?([^"/\\\s]+)"?', r"@\2", t)  # @"/long/path/file.pdf" -> @file.pdf
                first_user = t.strip()
            lines.append(f"[{role}] {text}")
    if not lines:
        return None
    title = summary or re.sub(r"\s+", " ", first_user)[:100] or path.stem
    project = Path(cwd).name if cwd else path.parent.name
    stamp = last_ts or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return dict(
        source_id=sid,
        ts=stamp,
        title=f"[{project}] {title}",
        content="\n\n".join(lines),
        metadata={"path": str(path), "cwd": cwd, "project": project, "git_branch": branch,
                  "session_id": sid, "started": first_ts, "ended": last_ts, "turns": len(lines)},
    )


def ingest_claude_code(db, cfg: dict) -> dict:
    scfg = cfg["sources"]["claude_code"]
    chunk = cfg["chunking"]
    root = Path(scfg.get("projects_dir", "~/.claude/projects")).expanduser()
    if not root.exists():
        raise RuntimeError(f"{root} does not exist")
    report = {"items": 0, "unchanged": 0, "empty": 0}
    for path in sorted(root.rglob("*.jsonl")):
        st = path.stat()
        mark = f"{int(st.st_mtime)}:{st.st_size}"
        if get_state(db, "claude_code", str(path)) == mark:
            report["unchanged"] += 1
            continue
        item = parse_session(path, scfg.get("max_tool_result_chars", 1500))
        if item is None:
            report["empty"] += 1
        else:
            if "subagents" in path.parts or path.parent.name == "subagents":
                item["source_id"] = f"{item['source_id']}:{path.stem}"
            rows = item_rows("session", item["ts"], item["title"], item["content"], item["metadata"],
                             chunk["long_threshold_chars"], chunk["raw_chunk_chars"])
            replace_rows(db, "claude_code", item["source_id"], rows)
            report["items"] += 1
        set_state(db, "claude_code", str(path), mark)
        db.commit()
    return report


# ============================================================ Notes folder (optional)
def ingest_notes(db, cfg: dict) -> dict:
    scfg = cfg["sources"]["notes"]
    chunk = cfg["chunking"]
    exts = {e.lower() for e in scfg.get("extensions", [".md", ".txt"])}
    report = {"items": 0, "unchanged": 0}
    for folder in scfg.get("folders", []):
        base = Path(folder).expanduser()
        for path in sorted(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in exts):
            st = path.stat()
            mark = f"{int(st.st_mtime)}:{st.st_size}"
            if get_state(db, "notes", str(path)) == mark:
                report["unchanged"] += 1
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            first = next((l.lstrip("# ").strip() for l in text.splitlines() if l.strip()), path.stem)
            rows = item_rows("note", st.st_mtime, first[:120] or path.stem, text,
                             {"path": str(path)}, chunk["long_threshold_chars"], chunk["raw_chunk_chars"])
            replace_rows(db, "notes", str(path), rows)
            set_state(db, "notes", str(path), mark)
            report["items"] += 1
        db.commit()
    return report


CONNECTORS = {
    "gmail": ingest_gmail,
    "claude_code": ingest_claude_code,
    "notes": ingest_notes,
}
