Input:
An evaluated observation from the user: "the project release label is cedar-rt42x9"
(session s1, interaction 0), outcome "ok".

Expected:
One MemoryProposal with decision `append`, target `episodic`, reason
`new_observation`; one immutable episode is written whose id is the observation
id, tagged with the session and source kind `user`. Replaying the same
observation writes nothing new.

Not expected:
- Storing the user's question "what release label did i give you?" as a memory
  (decision `skip`, reason `query_not_fact`).
- Storing the same sentence twice in one session (`duplicate_in_session`).
- Storing an observation that fails the contract (`invalid_observation`).
- Relabeling an agent-generated assertion as user evidence.
- Writing a semantic claim directly — that is consolidation's job.
