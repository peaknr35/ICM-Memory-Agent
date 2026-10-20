"""kb_retriever: read-only access to the personal knowledge base (kb/kb.sqlite).

The KB is an evidence source, never a memory source. Invariant: KB rows never
reach memory_writer. Three fences keep it that way:
- the connection is opened with SQLite `mode=ro`, so this process cannot write the KB;
- every hit carries `origin="kb"` and an id in its own namespace, `kb:<source>:<source_id>`
  (item-level, so it survives re-ingests that rebuild row ids);
- memory_writer refuses any observation whose id is in that namespace.

Ranking reuses kb/kb.py `search()` (FTS5 bm25 over summaries + raw chunks, RRF,
recency bonus), so there is exactly one KB ranking implementation. That function
only runs SELECTs, which is why it works on a read-only connection.

The KB has no notion of ICM scope: whoever passes a KBRetriever to a Runner is
granting that scope access to everything in the KB. Use `sources=` to narrow it.
"""
import importlib.util, json, sqlite3, sys
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent / "kb"
KB_PREFIX = "kb:"

def is_kb_id(i):
    return isinstance(i, str) and i.startswith(KB_PREFIX)

def _load_kb_search(kb_dir):
    """Import kb/kb.py under a private name (the folder is also called `kb`, so a plain import is ambiguous)."""
    if str(kb_dir) not in sys.path: sys.path.insert(0, str(kb_dir))   # kb.py does `import kbcore`
    spec = importlib.util.spec_from_file_location("_icm_kb_search", kb_dir / "kb.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

class KBRetriever:
    def __init__(self, db_path=None, kb_dir=KB_DIR, sources=None, max_chars=1200):
        kb_dir = Path(kb_dir); db_path = Path(db_path or kb_dir / "kb.sqlite")
        if not db_path.exists():
            raise FileNotFoundError(f"knowledge base not found: {db_path} (run kb/ingest_all.py first)")
        self.db = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._kb = _load_kb_search(kb_dir)
        self.cfg = json.loads((kb_dir / "_config" / "config.json").read_text(encoding="utf-8"))
        self.sources = tuple(sources) if sources else None
        self.max_chars = max_chars

    def search(self, cue, k=5):
        """Top-k KB items as evidence dicts, shaped like Store.search hits plus origin/pointer."""
        hits = []
        for s in self.sources or (None,):
            hits += self._kb.search(self.db, cue, source=s, limit=k, cfg=self.cfg)
        hits.sort(key=lambda e: -e["score"])
        out = []
        for e in hits[:k]:
            r = e["row"]
            content = self.db.execute("SELECT content FROM docs WHERE id=?", (r["id"],)).fetchone()[0] or ""
            meta = json.loads(r["metadata"] or "{}")
            out.append(dict(id=f"{KB_PREFIX}{r['source']}:{r['source_id']}", origin="kb", kind=r["kind"],
                            ts=r["ts"], text=f"{r['title'] or ''}\n{content[:self.max_chars]}".strip(),
                            outcome="", source=f"kb:{r['source']}", score=e["score"],
                            pointer=meta.get("url") or meta.get("path") or "", superseded=bool(r["superseded_by"])))
        return out

    def exists(self, kb_id):
        """True if a `kb:<source>:<source_id>` pointer still resolves to a row (for evidence checks)."""
        if not is_kb_id(kb_id): return False
        src, _, sid = kb_id[len(KB_PREFIX):].partition(":")
        return self.db.execute("SELECT 1 FROM docs WHERE source=? AND source_id=? LIMIT 1", (src, sid)).fetchone() is not None

    def close(self):
        self.db.close()

def rrf(lists, k=60, limit=None):
    """Reciprocal rank fusion over ranked lists of dicts keyed by `id`. Fuses ranks, never copies rows."""
    score, item = {}, {}
    for lst in lists:
        for rank, e in enumerate(lst, start=1):
            score[e["id"]] = score.get(e["id"], 0.0) + 1.0 / (k + rank)
            item.setdefault(e["id"], e)
    order = sorted(score, key=lambda i: -score[i])   # stable: ties keep first-list (episode) order
    return [item[i] for i in order[:limit]]
