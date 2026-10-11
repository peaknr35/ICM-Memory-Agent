import sqlite3, time, uuid, json, re
from .embeddings import make_embedder, cosine
class Store:
    def __init__(self, path=":memory:", embedder=None):
        self.db=sqlite3.connect(path)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY, ts REAL, scope TEXT, kind TEXT, text TEXT, outcome TEXT, source_ids TEXT, emb TEXT, deleted INT DEFAULT 0);
        CREATE TABLE IF NOT EXISTS derived(id TEXT PRIMARY KEY, ts REAL, scope TEXT, claim TEXT, source_ids TEXT, status TEXT, revision INT);
        """)
        if "emb" not in [r[1] for r in self.db.execute("PRAGMA table_info(episodes)")]:  # migrate old DBs
            self.db.execute("ALTER TABLE episodes ADD COLUMN emb TEXT"); self.db.commit()
        self.embed=embedder if embedder is not None else make_embedder()  # callable=vector, "keyword"=legacy
    def append(self, scope, kind, text, outcome="", source_ids=()):
        i=str(uuid.uuid4()); emb=json.dumps(self.embed(text)) if callable(self.embed) else None
        self.db.execute("INSERT INTO episodes(id,ts,scope,kind,text,outcome,source_ids,emb,deleted) VALUES(?,?,?,?,?,?,?,?,0)",
            (i,time.time(),scope,kind,text,outcome,json.dumps(list(source_ids)),emb)); self.db.commit(); return i
    def search(self, scope, cue, k=5):
        return self._search_vector(scope,cue,k) if callable(self.embed) else self._search_keyword(scope,cue,k)
    def _search_keyword(self, scope, cue, k=5):
        tok=lambda s:{w for w in re.findall(r"[a-z0-9]+",s.lower()) if len(w)>=2}
        words=tok(cue)
        rows=self.db.execute("SELECT id,ts,kind,text,outcome FROM episodes WHERE scope=? AND deleted=0",(scope,)).fetchall()
        sc=[(len(words & tok(r[3])),r) for r in rows]
        return [dict(id=r[0],ts=r[1],kind=r[2],text=r[3],outcome=r[4],score=s) for s,r in sorted(sc,key=lambda x:(-x[0],-x[1][1])) if s>0][:k]
    def _search_vector(self, scope, cue, k=5):
        q=self.embed(cue)
        rows=self.db.execute("SELECT id,ts,kind,text,outcome,emb FROM episodes WHERE scope=? AND deleted=0 AND emb IS NOT NULL",(scope,)).fetchall()
        sc=[(cosine(q,json.loads(r[5])),r) for r in rows]
        return [dict(id=r[0],ts=r[1],kind=r[2],text=r[3],outcome=r[4],score=s) for s,r in sorted(sc,key=lambda x:(-x[0],-x[1][1])) if s>0][:k]
    def delete(self, ep_id):
        self.db.execute("DELETE FROM episodes WHERE id=?",(ep_id,))
        for (i,src) in self.db.execute("SELECT id,source_ids FROM derived").fetchall():
            if ep_id in json.loads(src): self.db.execute("DELETE FROM derived WHERE id=?",(i,))
        self.db.commit()
    def propose_claim(self, scope, claim, source_ids):
        i=str(uuid.uuid4()); self.db.execute("INSERT INTO derived VALUES(?,?,?,?,?,?,1)",(i,time.time(),scope,claim,json.dumps(list(source_ids)),"candidate")); self.db.commit(); return i
