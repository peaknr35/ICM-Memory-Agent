"""Shared core for the knowledge base: paths, config, database, safety filters.

Everything else (connectors, summarizer, search CLI) imports from here, so the
database schema and the masking rules live in exactly one place.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "kb.sqlite"
CONFIG_PATH = ROOT / "_config" / "config.json"
ENV_PATH = ROOT / ".env"
SECRETS = ROOT / "secrets"
LOG_DIR = ROOT / "logs"
STAGES = ROOT / "stages"

# Windows consoles default to cp1252; never crash on an emoji in an email subject.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ---------------------------------------------------------------- config / env
def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def load_env() -> None:
    """Read KEY=VALUE lines from .env into os.environ. Values are never printed."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        if v and k.strip() not in os.environ:
            os.environ[k.strip()] = v


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_iso(value) -> str:
    """Accept epoch seconds/ms, datetime, or ISO string; return UTC ISO string."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# -------------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,      -- email | session | note | segment | atom | raw
    source        TEXT NOT NULL,      -- gmail | claude_code | notes ...
    source_id     TEXT NOT NULL,      -- id of the ORIGINAL item (thread id, session id, file path)
    ts            TEXT NOT NULL,      -- ISO-8601 UTC date of the item
    title         TEXT,
    content       TEXT,
    metadata      TEXT,               -- JSON; always has "url" or "path" pointing at the original
    superseded_by INTEGER REFERENCES docs(id)
);
CREATE INDEX IF NOT EXISTS docs_item ON docs(source, source_id);
CREATE INDEX IF NOT EXISTS docs_ts   ON docs(ts);
CREATE INDEX IF NOT EXISTS docs_kind ON docs(kind);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    title, content, content='docs', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
    INSERT INTO docs_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
END;
CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE OF title, content ON docs BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
    INSERT INTO docs_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;

CREATE TABLE IF NOT EXISTS ingest_state (
    source    TEXT NOT NULL,
    key       TEXT NOT NULL,
    watermark TEXT,
    PRIMARY KEY (source, key)
);
"""

SUMMARY_KINDS = ("segment", "atom")


def connect(path: Path | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(path or DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def get_state(db, source: str, key: str, default=None):
    row = db.execute("SELECT watermark FROM ingest_state WHERE source=? AND key=?", (source, key)).fetchone()
    return row["watermark"] if row else default


def set_state(db, source: str, key: str, watermark) -> None:
    db.execute(
        "INSERT INTO ingest_state(source, key, watermark) VALUES (?,?,?) "
        "ON CONFLICT(source, key) DO UPDATE SET watermark=excluded.watermark",
        (source, key, None if watermark is None else str(watermark)),
    )


def chunk_text(text: str, size: int = 4000, overlap: int = 200) -> list[str]:
    """Split into ~size-char chunks, preferring to break on a newline."""
    text = text or ""
    if len(text) <= size:
        return [text] if text.strip() else []
    out, i = [], 0
    while i < len(text):
        end = min(i + size, len(text))
        if end < len(text):
            nl = text.rfind("\n", i + size // 2, end)
            if nl > 0:
                end = nl
        out.append(text[i:end])
        if end >= len(text):
            break
        i = max(end - overlap, i + 1)
    return out


def replace_rows(db, source: str, source_id: str, rows: list[dict], kinds: tuple[str, ...] | None = None) -> int:
    """Delete an item's old rows, then insert the new ones. Running twice never duplicates.

    rows: dicts with kind, ts, title, content, metadata (dict).
    kinds: if given, only rows of these kinds are deleted (the summarizer uses this
           to replace segments/atoms without touching raw chunks). Default: all rows.
    """
    if kinds:
        q = ",".join("?" * len(kinds))
        db.execute(f"DELETE FROM docs WHERE source=? AND source_id=? AND kind IN ({q})", (source, source_id, *kinds))
    else:
        db.execute("DELETE FROM docs WHERE source=? AND source_id=?", (source, source_id))
    for r in rows:
        if not r.get("ts"):
            raise ValueError(f"row for {source}:{source_id} has no date")
        meta = r.get("metadata") or {}
        if not (meta.get("url") or meta.get("path")):
            raise ValueError(f"row for {source}:{source_id} has no pointer to the original")
        db.execute(
            "INSERT INTO docs(kind, source, source_id, ts, title, content, metadata) VALUES (?,?,?,?,?,?,?)",
            (r["kind"], source, source_id, to_iso(r["ts"]), mask_secrets(r.get("title") or ""),
             mask_secrets(r.get("content") or ""), json.dumps(meta, ensure_ascii=False)),
        )
    return len(rows)


def item_rows(kind: str, ts, title: str, content: str, metadata: dict, long_threshold: int, chunk_size: int = 4000):
    """Rows for one ingested item.

    Short item  -> one row of `kind` (searched with the summaries).
    Long item   -> one short header row of `kind` + `raw` chunks. The summarizer
                   (stage 02) later adds `segment` and `atom` rows that point back here.
    """
    content = mask_secrets(content or "")
    if len(content) <= long_threshold:
        return [dict(kind=kind, ts=ts, title=title, content=content, metadata=metadata)]
    head = content[:600].rstrip() + "\n…"
    rows = [dict(kind=kind, ts=ts, title=title, content=head, metadata={**metadata, "long": True, "chars": len(content)})]
    for n, chunk in enumerate(chunk_text(content, chunk_size)):
        rows.append(dict(kind="raw", ts=ts, title=f"{title} [part {n + 1}]", content=chunk,
                         metadata={**metadata, "chunk": n + 1}))
    return rows


# ---------------------------------------------------------------------- safety
# Masking runs on everything before it is stored (titles, content, summaries).
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{10,}"),                 # Anthropic
    re.compile(r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_\-]{20,}"),  # OpenAI / Stripe style
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),                 # AWS access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),                # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),              # Slack
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),                    # Google API key
    re.compile(r"\bya29\.[0-9A-Za-z_\-]{20,}"),                   # Google OAuth access token
    re.compile(r"\b1//[0-9A-Za-z_\-]{30,}"),                      # Google refresh token
    re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),                       # Hugging Face
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{20,}"),
]
# key = value / key: value assignments for secret-looking names; keep the name, mask the value.
_ASSIGN = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:api[_-]?key|secret|token|passw(?:or)?d|passwd|pwd|client[_-]?secret|access[_-]?key)[A-Z0-9_]*)"
    r"(\s*[:=]\s*|\s+is\s+)([\"']?)([^\s\"',;]{6,})\3"
)
_URL_CREDS = re.compile(r"(\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:)([^\s@/]{3,})(@)")


def mask_secrets(text: str) -> str:
    if not text:
        return text
    for pat in _SECRET_PATTERNS:
        text = pat.sub(lambda m: (m.group(1) + " " if m.lastindex else "") + "[MASKED]", text)
    text = _ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}[MASKED]", text)
    text = _URL_CREDS.sub(lambda m: f"{m.group(1)}[MASKED]{m.group(3)}", text)
    return text


_SENSITIVE_MAIL = re.compile(
    r"(?i)(password reset|reset (?:your|the) password|forgot (?:your )?password|change your password|"
    r"verification code|security code|confirmation code|sign[- ]?in code|log[- ]?in code|login code|"
    r"one[- ]time (?:pass(?:word|code)|code|pin)|\bOTP\b|passcode|two[- ]factor|2[- ]?step|\b2fa\b|\bmfa\b|"
    r"authentication code|verify your (?:identity|sign[- ]in|login)|magic link|your code is)"
)


def is_sensitive_email(subject: str, body: str) -> bool:
    """True for password-reset / 2FA / login-code mail. These are never stored."""
    return bool(_SENSITIVE_MAIL.search(subject or "") or _SENSITIVE_MAIL.search((body or "")[:1500]))


# ---------------------------------------------------------------------- stats
def stats(db) -> dict:
    total = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    by = db.execute(
        "SELECT source, kind, COUNT(*) n, MIN(ts) oldest, MAX(ts) newest FROM docs GROUP BY source, kind ORDER BY source, kind"
    ).fetchall()
    items = db.execute(
        "SELECT source, COUNT(DISTINCT source_id) n FROM docs GROUP BY source").fetchall()
    return {
        "total": total,
        "rows": [dict(r) for r in by],
        "items": {r["source"]: r["n"] for r in items},
        "last_ingest": get_state(db, "_meta", "last_ingest"),
    }
