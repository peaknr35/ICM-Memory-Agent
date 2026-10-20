import sqlite3, time, uuid, json, re, hashlib
from .embeddings import make_embedder, cosine
_norm=lambda s:" ".join(s.casefold().split())
class Store:
    def __init__(self, path=":memory:", embedder=None):
        self.db=sqlite3.connect(path)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY, ts REAL, scope TEXT, kind TEXT, text TEXT, outcome TEXT, source_ids TEXT, emb TEXT, deleted INT DEFAULT 0, session TEXT, source_kind TEXT);
        CREATE TABLE IF NOT EXISTS derived(id TEXT PRIMARY KEY, ts REAL, scope TEXT, claim TEXT, source_ids TEXT, status TEXT, revision INT, snapshot TEXT, supersedes TEXT, kb_refs TEXT);
        """)
        self._migrate("episodes",{"emb":"TEXT","session":"TEXT","source_kind":"TEXT"})  # old DBs predate these
        self._migrate("derived",{"snapshot":"TEXT","supersedes":"TEXT","kb_refs":"TEXT"}) # ...the claim lifecycle, KB pointers
        self.embed=embedder if embedder is not None else make_embedder()  # callable=vector, "keyword"=legacy
    def _migrate(self, table, cols):
        have=[r[1] for r in self.db.execute(f"PRAGMA table_info({table})")]
        for c,t in cols.items():
            if c not in have: self.db.execute(f"ALTER TABLE {table} ADD COLUMN {c} {t}")
        self.db.commit()
    # --- episodic store (immutable observations) ---
    def append(self, scope, kind, text, outcome="", source_ids=(), id=None, session=None, source_kind=None):
        """Append one immutable episode. Re-appending an existing `id` is a no-op (idempotent writes)."""
        if id and self.db.execute("SELECT 1 FROM episodes WHERE id=?",(id,)).fetchone(): return id
        i=id or str(uuid.uuid4()); emb=json.dumps(self.embed(text)) if callable(self.embed) else None
        self.db.execute("INSERT INTO episodes(id,ts,scope,kind,text,outcome,source_ids,emb,deleted,session,source_kind) VALUES(?,?,?,?,?,?,?,?,0,?,?)",
            (i,time.time(),scope,kind,text,outcome,json.dumps(list(source_ids)),emb,session,source_kind)); self.db.commit(); return i
    def search(self, scope, cue, k=5):
        return self._search_vector(scope,cue,k) if callable(self.embed) else self._search_keyword(scope,cue,k)
    def _search_keyword(self, scope, cue, k=5):
        tok=lambda s:{w for w in re.findall(r"[a-z0-9]+",s.lower()) if len(w)>=2}
        words=tok(cue)
        rows=self.db.execute("SELECT id,ts,kind,text,outcome,source_kind FROM episodes WHERE scope=? AND deleted=0",(scope,)).fetchall()
        sc=[(len(words & tok(r[3])),r) for r in rows]
        return [dict(id=r[0],ts=r[1],kind=r[2],text=r[3],outcome=r[4],source=r[5],score=s) for s,r in sorted(sc,key=lambda x:(-x[0],-x[1][1])) if s>0][:k]
    def _search_vector(self, scope, cue, k=5):
        q=self.embed(cue)
        rows=self.db.execute("SELECT id,ts,kind,text,outcome,source_kind,emb FROM episodes WHERE scope=? AND deleted=0 AND emb IS NOT NULL",(scope,)).fetchall()
        sc=[(cosine(q,json.loads(r[6])),r) for r in rows]
        return [dict(id=r[0],ts=r[1],kind=r[2],text=r[3],outcome=r[4],source=r[5],score=s) for s,r in sorted(sc,key=lambda x:(-x[0],-x[1][1])) if s>0][:k]
    def episodes(self, scope):
        return [dict(id=r[0],text=r[1],outcome=r[2],source_ids=json.loads(r[3]),session=r[4],source=r[5])
                for r in self.db.execute("SELECT id,text,outcome,source_ids,session,source_kind FROM episodes WHERE scope=? AND deleted=0 ORDER BY ts",(scope,))]
    def find_in_session(self, scope, session, text):
        """Id of an episode with the same (normalized) text already stored in this session, else None."""
        n=_norm(text)
        for i,t in self.db.execute("SELECT id,text FROM episodes WHERE scope=? AND session=? AND deleted=0",(scope,session)):
            if _norm(t)==n: return i
        return None
    def resolves(self, scope, ids):
        """True if every id is a live episode in this scope (the provenance check for derived records)."""
        ids=set(ids)
        if not ids: return False
        q=",".join("?"*len(ids))
        return self.db.execute(f"SELECT COUNT(*) FROM episodes WHERE scope=? AND deleted=0 AND id IN ({q})",(scope,*ids)).fetchone()[0]==len(ids)
    def snapshot(self, scope):
        """Fingerprint of the live episodic state; changes when episodes are added/deleted."""
        ids="".join(r[0] for r in self.db.execute("SELECT id FROM episodes WHERE scope=? AND deleted=0 ORDER BY id",(scope,)))
        return hashlib.md5(ids.encode()).hexdigest()[:12]
    def delete(self, ep_id):
        self.db.execute("DELETE FROM episodes WHERE id=?",(ep_id,))
        for (i,src) in self.db.execute("SELECT id,source_ids FROM derived").fetchall():
            if ep_id in json.loads(src): self.db.execute("DELETE FROM derived WHERE id=?",(i,))
        self.db.commit()
    # --- derived semantic claims (separate from raw episodes; cite sources) ---
    def propose_claim(self, scope, claim, source_ids, snapshot=None, supersedes=None, status="candidate", revision=1, kb_refs=()):
        """source_ids are episodes (cascade on delete); kb_refs are read-only KB pointers (never cascade)."""
        i=str(uuid.uuid4())
        self.db.execute("INSERT INTO derived(id,ts,scope,claim,source_ids,status,revision,snapshot,supersedes,kb_refs) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (i,time.time(),scope,claim,json.dumps(list(source_ids)),status,revision,snapshot,supersedes,json.dumps(sorted(set(kb_refs))))); self.db.commit(); return i
    def claims(self, scope, status=None):
        q="SELECT id,claim,source_ids,status,revision,snapshot,supersedes,kb_refs FROM derived WHERE scope=?"; a=[scope]
        if status: q+=" AND status=?"; a.append(status)
        return [dict(id=r[0],claim=r[1],source_ids=json.loads(r[2]),status=r[3],revision=r[4],snapshot=r[5],supersedes=r[6],kb_refs=json.loads(r[7] or "[]"))
                for r in self.db.execute(q+" ORDER BY ts",a)]
    def set_claim(self, claim_id, **fields):
        if not fields: return
        self.db.execute(f"UPDATE derived SET {','.join(k+'=?' for k in fields)} WHERE id=?",(*fields.values(),claim_id)); self.db.commit()
