"""Knowledge base CLI.

    python kb.py init
    python kb.py stats
    python kb.py search "query" [--after YYYY-MM-DD] [--source NAME] [--limit N]
    python kb.py supersede OLD_ID NEW_ID      (optional: mark a row as replaced by a newer one)

Search is plain keyword search (SQLite FTS5 + bm25), run twice:
  1. over summaries: segments, atoms and short items
  2. over raw 4,000-character chunks
The two ranked lists are merged with reciprocal rank fusion (k=60, raw weighted
0.5), then newer items get a small recency bonus and superseded rows score half.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timezone

import kbcore

STOP = set("""a an and are as at be by did do does for from had has have how i in is it its me my of on or
our so that the their this to was we were what when where which who why with you your""".split())


def fts_query(q: str) -> str:
    """Turn free text into an OR of quoted words, so punctuation never breaks FTS5."""
    words = re.findall(r"[\w][\w.\-/:]*", q, flags=re.UNICODE)
    terms, seen = [], set()
    for w in words:
        w = w.strip(".-/:").lower()
        if len(w) < 2 or w in STOP or w in seen:
            continue
        seen.add(w)
        terms.append('"' + w.replace('"', "") + '"')
    if not terms:  # query was all stop words; use them anyway
        terms = ['"' + w.lower() + '"' for w in words if w]
    return " OR ".join(terms)


def _ranked(db, match: str, raw: bool, after, source, n: int):
    where = ["docs_fts MATCH ?", "d.kind = 'raw'" if raw else "d.kind != 'raw'"]
    args = [match]
    if after:
        where.append("d.ts >= ?")
        args.append(after)
    if source:
        where.append("d.source = ?")
        args.append(source)
    sql = f"""SELECT d.id, d.kind, d.source, d.source_id, d.ts, d.title, d.metadata, d.superseded_by,
                     snippet(docs_fts, 1, '[', ']', '…', 24) AS snip, bm25(docs_fts, 3.0, 1.0) AS score
              FROM docs_fts JOIN docs d ON d.id = docs_fts.rowid
              WHERE {' AND '.join(where)} ORDER BY score LIMIT ?"""
    return db.execute(sql, args + [n]).fetchall()


def search(db, query: str, after=None, source=None, limit=8, cfg=None):
    s = (cfg or kbcore.load_config())["search"]
    match = fts_query(query)
    if not match:
        return []
    n = s["candidates_per_list"]
    lists = [(_ranked(db, match, False, after, source, n), 1.0),
             (_ranked(db, match, True, after, source, n), s["raw_weight"])]
    now = datetime.now(timezone.utc)
    fused: dict[int, dict] = {}
    for rows, weight in lists:
        for rank, r in enumerate(rows, start=1):
            e = fused.setdefault(r["id"], {"row": r, "rrf": 0.0})
            e["rrf"] += weight / (s["rrf_k"] + rank)
    for e in fused.values():
        r = e["row"]
        try:
            age = max(0.0, (now - datetime.fromisoformat(r["ts"])).total_seconds() / 86400)
        except ValueError:
            age = 3650
        score = e["rrf"] * (1 + s["recency_weight"] * math.exp(-age / s["recency_halflife_days"]))
        if r["superseded_by"]:
            score *= s["superseded_factor"]
        e["score"] = score
    # One result per original item: keep its best row, count the other hits.
    best: dict[tuple, dict] = {}
    for e in sorted(fused.values(), key=lambda x: -x["score"]):
        key = (e["row"]["source"], e["row"]["source_id"])
        if key in best:
            best[key]["also"] += 1
        else:
            best[key] = {**e, "also": 0}
    return sorted(best.values(), key=lambda x: -x["score"])[:limit]


def header(db, cfg) -> str:
    total = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    items = db.execute("SELECT COUNT(*) FROM (SELECT DISTINCT source, source_id FROM docs)").fetchone()[0]
    last = kbcore.get_state(db, "_meta", "last_ingest")
    if last:
        hrs = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
        when = f"last ingest {last[:16].replace('T', ' ')} UTC ({hrs:.1f}h ago)"
        if hrs > cfg["search"]["stale_after_hours"]:
            when += "  ⚠ STALE: run python ingest_all.py"
    else:
        when = "last ingest: never  ⚠ run python ingest_all.py"
    return f"kb · {total:,} rows · {items:,} items · {when}"


def cmd_search(a, db, cfg):
    t0 = time.perf_counter()
    res = search(db, a.query, a.after, a.source, a.limit or cfg["search"]["default_limit"], cfg)
    ms = (time.perf_counter() - t0) * 1000
    print(header(db, cfg))
    print(f'query: {a.query!r} → {fts_query(a.query)}  ·  {len(res)} results in {ms:.0f} ms')
    filt = " ".join(x for x in [f"after {a.after}" if a.after else "", f"source {a.source}" if a.source else ""] if x)
    if filt:
        print(f"filters: {filt}")
    print("-" * 78)
    if not res:
        print("No matches. Try different, more distinctive words (names, error text, file names).")
    for i, e in enumerate(res, 1):
        r = e["row"]
        meta = json.loads(r["metadata"] or "{}")
        pointer = meta.get("url") or meta.get("path") or ""
        sup = "  (superseded)" if r["superseded_by"] else ""
        more = f"  +{e['also']} more hits in this item" if e["also"] else ""
        print(f"{i}. {r['ts'][:10]}  {r['source']}/{r['kind']}  #{r['id']}  score {e['score'] * 1000:.2f}{sup}{more}")
        print(f"   {r['title']}")
        if meta.get("parent_title") and meta["parent_title"] != r["title"]:
            print(f"   in: {meta['parent_title']}")
        snip = " ".join((r["snip"] or "").split())
        print(f"   {snip[:300]}")
        print(f"   → {pointer}")
        print()


def cmd_stats(a, db, cfg):
    st = kbcore.stats(db)
    print(header(db, cfg))
    print(f"{'source':<12} {'kind':<8} {'rows':>7}  {'oldest':<10}  {'newest':<10}")
    for r in st["rows"]:
        print(f"{r['source']:<12} {r['kind']:<8} {r['n']:>7}  {(r['oldest'] or '')[:10]:<10}  {(r['newest'] or '')[:10]:<10}")
    print("items per source: " + ", ".join(f"{k}={v}" for k, v in st["items"].items()))
    size = kbcore.DB_PATH.stat().st_size / 1e6 if kbcore.DB_PATH.exists() else 0
    print(f"database: {kbcore.DB_PATH} ({size:.1f} MB)")


def cmd_init(a, db, cfg):
    print(f"Database ready: {kbcore.DB_PATH}")
    print(header(db, cfg))


def cmd_supersede(a, db, cfg):
    db.execute("UPDATE docs SET superseded_by=? WHERE id=?", (a.new_id, a.old_id))
    db.commit()
    print(f"#{a.old_id} is now superseded by #{a.new_id}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Personal knowledge base")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("stats")
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--after", help="YYYY-MM-DD")
    s.add_argument("--source", help="gmail | claude_code | notes")
    s.add_argument("--limit", type=int)
    x = sub.add_parser("supersede")
    x.add_argument("old_id", type=int)
    x.add_argument("new_id", type=int)
    a = p.parse_args(argv)
    cfg = kbcore.load_config()
    db = kbcore.connect()
    {"init": cmd_init, "stats": cmd_stats, "search": cmd_search, "supersede": cmd_supersede}[a.cmd](a, db, cfg)


if __name__ == "__main__":
    sys.exit(main())
