import uuid
from datetime import datetime, timezone
from .storage import Store
from .router import route
from .models import make_llm
from .embeddings import make_embedder
from . import memory_writer
INJECTION=("ignore previous","disregard instructions","system prompt")
class Runner:
    def __init__(self, store=None, llm=None, backend=None, embed_backend=None, scope="default", budget=3, session_id=None):
        self.store=store or Store(embedder=make_embedder(embed_backend) if embed_backend else None)  # default hash embeddings
        self.scope=scope; self.budget=budget
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
        ev=self.store.search(self.scope, f"{goal} {obs}", self.budget)                # retrieve
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
