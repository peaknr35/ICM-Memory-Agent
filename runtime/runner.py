import uuid
from datetime import datetime, timezone
from .storage import Store
from .router import route
from .models import make_llm
from .embeddings import make_embedder
from . import memory_writer
from .kb_retriever import rrf
INJECTION=("ignore previous","disregard instructions","system prompt")
class Runner:
    def __init__(self, store=None, llm=None, backend=None, embed_backend=None, scope="default", budget=3, session_id=None, kb=None):
        self.store=store or Store(embedder=make_embedder(embed_backend) if embed_backend else None)  # default hash embeddings
        self.scope=scope; self.budget=budget
        self.kb=kb   # optional read-only KBRetriever: extra evidence, never written as episodes
        self.llm=llm or make_llm(backend)   # stub by default; backend= or MEMORY_LLM_BACKEND selects ollama/claude/gemini
        self.session_id=session_id or uuid.uuid4().hex; self.n=0   # one Runner = one session
        self.working={}; self.trace=[]
    def observe(self, content, source="user"):
        """Normalize raw input into an Observation record (contracts/observation.schema.json)."""
        o={"schema_version":"1.0","id":str(uuid.uuid4()),"session_id":self.session_id,"interaction_index":self.n,
           "observed_at":datetime.now(timezone.utc).isoformat(),
           "source":{"kind":source,"reference":f"{self.session_id}#{self.n}"},
           "content":content,"provenance":{"evidence_ids":[]}}
        self.n+=1; return o
    def step(self, goal, obs, evaluate=lambda a:"ok", ephemeral=False, source="user"):
        o=self.observe(obs,source); self.working={"goal":goal,"observation":o["id"]}  # observe
        cue=f"{goal} {obs}"
        ev=self.store.search(self.scope, cue, self.budget)                            # retrieve
        for e in ev: e.setdefault("origin","episode")
        if self.kb: ev=rrf([ev, self.kb.search(cue, self.budget)], limit=self.budget)  # fuse ranks, rows stay put
        for e in ev: e["untrusted"]=True; e["flagged"]=any(p in e["text"].lower() for p in INJECTION)
        safe=[e for e in ev if not e["flagged"]]
        act=self.llm(goal,obs,safe)                                                   # reason + act
        outcome=evaluate(act)                                                         # evaluate
        mp=memory_writer.write(self.store,self.scope,o,outcome,ephemeral)             # store, via the write gate
        self.trace.append({"route":route({"ephemeral":ephemeral}),"evidence_ids":[e["id"] for e in safe],
                           "flagged_ids":[e["id"] for e in ev if e["flagged"]],
                           "episode":mp["episode_id"] if mp["decision"]=="append" else None,
                           "memory":{"decision":mp["decision"],"reason":mp["reason"]}})
        return act
    def remember(self, conclusion, evidence_ids=()):
        """Store the agent's own distilled conclusion as an episode that cites its evidence by id.
        Only ids actually retrieved (and not flagged) earlier in this session may be cited, so a
        KB row is pointed at, never copied, and a conclusion cannot invent provenance."""
        seen={i for t in self.trace for i in t["evidence_ids"]}
        bad=[i for i in evidence_ids if i not in seen]
        if bad: raise ValueError(f"cannot cite evidence not retrieved in this session: {bad}")
        o=self.observe(conclusion,"agent"); o["provenance"]["evidence_ids"]=list(dict.fromkeys(evidence_ids))
        mp=memory_writer.write(self.store,self.scope,o)
        self.trace.append({"route":"persistent_memory","evidence_ids":[],"flagged_ids":[],
                           "episode":mp["episode_id"] if mp["decision"]=="append" else None,
                           "cites":o["provenance"]["evidence_ids"],
                           "memory":{"decision":mp["decision"],"reason":mp["reason"]}})
        return mp
