"""NSM Knowledge Base — storage + embeddings + hybrid search.

One SQLite database, one docs table. Every connector emits rows with the
same shape (source, source_id, ts, title, content, metadata) and anything
in the table is immediately searchable through the same interface.
"""
import json
import math
import os
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

DB_PATH = Path(__file__).parent / "nsm_kb.sqlite"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMS = 1536

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    ts TEXT,
    title TEXT,
    content TEXT,
    metadata TEXT,
    embedding BLOB,
    UNIQUE(source, source_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    title, content, content='docs', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
    INSERT INTO docs_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
END;
CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON docs BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
    INSERT INTO docs_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
"""


def connect():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.row_factory = sqlite3.Row
    return db


def upsert(db, source, source_id, ts, title, content, metadata=None):
    """Insert or replace a doc. Clears the embedding when content changes."""
    row = db.execute(
        "SELECT id, content FROM docs WHERE source=? AND source_id=?",
        (source, source_id),
    ).fetchone()
    meta = json.dumps(metadata or {})
    if row is None:
        db.execute(
            "INSERT INTO docs (source, source_id, ts, title, content, metadata) VALUES (?,?,?,?,?,?)",
            (source, source_id, ts, title, content, meta),
        )
        return True
    if row["content"] != content:
        db.execute(
            "UPDATE docs SET ts=?, title=?, content=?, metadata=?, embedding=NULL WHERE id=?",
            (ts, title, content, meta, row["id"]),
        )
        return True
    return False


def embed_missing(db, batch_size=100):
    """Embed every doc that doesn't have a vector yet."""
    from openai import OpenAI

    client = OpenAI()
    rows = db.execute("SELECT id, title, content FROM docs WHERE embedding IS NULL").fetchall()
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        texts = [((r["title"] or "") + "\n" + (r["content"] or ""))[:24000] for r in batch]
        resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
        for r, item in zip(batch, resp.data):
            vec = np.asarray(item.embedding, dtype=np.float32)
            db.execute("UPDATE docs SET embedding=? WHERE id=?", (vec.tobytes(), r["id"]))
        db.commit()
        print(f"  embedded {min(i + batch_size, len(rows))}/{len(rows)}")
    return len(rows)


def _fts_query(query):
    # Quote each term so punctuation in user queries doesn't break FTS5 syntax.
    terms = [t.replace('"', "") for t in query.split() if t.strip('"')]
    return " OR ".join(f'"{t}"' for t in terms)


def _age_factor(ts, now):
    """Mild recency boost: newer docs win ties, old-but-relevant still surfaces."""
    if not ts:
        return 0.85
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - dt).total_seconds() / 86400)
    except ValueError:
        return 0.85
    return 0.7 + 0.3 * math.exp(-age_days / 180)


def search(db, query, limit=10, source=None, rrf_k=60):
    """Hybrid retrieval: FTS5 BM25 + vector cosine, fused with RRF + age decay."""
    where = " AND docs.source=?" if source else ""
    args = [_fts_query(query)] + ([source] if source else [])
    lexical = db.execute(
        f"""SELECT docs.id FROM docs_fts JOIN docs ON docs.id = docs_fts.rowid
            WHERE docs_fts MATCH ?{where} ORDER BY docs_fts.rank LIMIT 50""",
        args,
    ).fetchall()
    lex_rank = {r["id"]: i for i, r in enumerate(lexical)}

    from openai import OpenAI

    qvec = np.asarray(
        OpenAI().embeddings.create(model=EMBED_MODEL, input=[query]).data[0].embedding,
        dtype=np.float32,
    )
    vec_where = " WHERE embedding IS NOT NULL" + (" AND source=?" if source else "")
    vrows = db.execute(f"SELECT id, embedding FROM docs{vec_where}", [source] if source else []).fetchall()
    sims = []
    for r in vrows:
        v = np.frombuffer(r["embedding"], dtype=np.float32)
        sims.append((r["id"], float(np.dot(qvec, v) / (np.linalg.norm(qvec) * np.linalg.norm(v) + 1e-9))))
    sims.sort(key=lambda x: -x[1])
    vec_rank = {doc_id: i for i, (doc_id, _) in enumerate(sims[:50])}

    now = datetime.now(timezone.utc)
    fused = []
    for doc_id in set(lex_rank) | set(vec_rank):
        score = 0.0
        if doc_id in lex_rank:
            score += 1.0 / (rrf_k + lex_rank[doc_id])
        if doc_id in vec_rank:
            score += 1.0 / (rrf_k + vec_rank[doc_id])
        row = db.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
        fused.append((score * _age_factor(row["ts"], now), row))
    fused.sort(key=lambda x: -x[0])
    return fused[:limit]


def stats(db):
    return db.execute(
        "SELECT source, COUNT(*) AS n, SUM(embedding IS NOT NULL) AS embedded, MAX(ts) AS newest FROM docs GROUP BY source"
    ).fetchall()
