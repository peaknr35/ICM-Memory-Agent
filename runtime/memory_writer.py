"""memory_writer: the single write gate for the episodic store (agents/online/memory_writer).

Turns an evaluated Observation into a MemoryProposal and applies it. Authority per
the agent spec: append to the episodic store only. It never writes semantic claims
(consolidation proposes those) and never touches weights.

Decisions, in order:
- the observation fails contracts/observation.schema.json  -> skip (nothing stored)
- routed to working context (ephemeral)                    -> skip
- a question from the user or agent (a query, not a fact)  -> skip
- an exact repeat of text already stored in this session   -> skip (points at the existing episode)
- otherwise                                                -> append one immutable episode

Writes are idempotent: the episode id IS the observation id, so replaying an
observation changes nothing. The source kind is stored as given, so an
agent-generated assertion stays `agent` and cannot be relabeled as user evidence.
"""
import time, uuid
from .contracts import validate
from .router import route

def _is_query(obs):
    """Only the unambiguous case: ends with '?'. Statements like 'When deploying, rotate
    tokens' must be kept, so a leading wh-word alone does not count."""
    return obs["source"]["kind"] in ("user", "agent") and obs["content"].rstrip().endswith("?")

def propose(store, scope, obs, ephemeral=False):
    """Decide what to do with one observation. Returns a MemoryProposal; applies nothing."""
    p = {"schema_version": "1.0", "id": "mp_" + uuid.uuid4().hex[:12], "ts": time.time(),
         "observation_id": str((obs or {}).get("id") or "invalid") if isinstance(obs, dict) else "invalid",
         "scope": scope, "target": "none", "decision": "skip", "source_ids": []}
    errs = validate("observation", obs)
    if errs:
        return {**p, "reason": "invalid_observation", "errors": errs}
    p["source_ids"] = [obs["id"]]
    if route({"ephemeral": ephemeral}) == "working_context":
        return {**p, "target": "working", "reason": "ephemeral"}
    if _is_query(obs):
        return {**p, "reason": "query_not_fact"}
    dup = store.find_in_session(scope, obs["session_id"], obs["content"])
    if dup and dup != obs["id"]:
        return {**p, "reason": "duplicate_in_session", "episode_id": dup}
    return {**p, "target": "episodic", "decision": "append", "reason": "new_observation", "episode_id": obs["id"]}

def write(store, scope, obs, outcome="", ephemeral=False):
    """Propose, check the proposal against its own contract, then apply it. Returns the proposal."""
    p = propose(store, scope, obs, ephemeral)
    errs = validate("memory_proposal", p)
    if errs:
        raise ValueError(f"memory_writer produced an invalid proposal: {errs}")
    if p["decision"] == "append":
        store.append(scope, "experience", obs["content"], outcome,
                     source_ids=obs["provenance"]["evidence_ids"], id=obs["id"],
                     session=obs["session_id"], source_kind=obs["source"]["kind"])
    return p
