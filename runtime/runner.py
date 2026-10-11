from .storage import Store
from .router import route
from .models import make_llm
INJECTION=("ignore previous","disregard instructions","system prompt")
class Runner:
    def __init__(self, store=None, llm=None, backend=None, scope="default", budget=3):
        self.store=store or Store(); self.scope=scope; self.budget=budget
        self.llm=llm or make_llm(backend)   # stub by default; backend= or MEMORY_LLM_BACKEND selects ollama/claude/gemini
        self.working={}; self.trace=[]
    def step(self, goal, obs, evaluate=lambda a:"ok", ephemeral=False):
        self.working={"goal":goal}                                   # observe
        ev=self.store.search(self.scope, f"{goal} {obs}", self.budget) # retrieve
        for e in ev: e["untrusted"]=True; e["flagged"]=any(p in e["text"].lower() for p in INJECTION)
        safe=[e for e in ev if not e["flagged"]]
        act=self.llm(goal,obs,safe)                                   # reason + act
        outcome=evaluate(act)                                         # evaluate
        kind=route({"ephemeral":ephemeral})                           # store
        ep=None
        if kind=="persistent_memory": ep=self.store.append(self.scope,"experience",f"{goal}: {obs}",outcome)
        self.trace.append({"route":kind,"evidence_ids":[e["id"] for e in safe],"episode":ep})
        return act
