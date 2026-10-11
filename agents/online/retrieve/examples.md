Input:
Store (earlier) observed: "the project release label is cedar-rt42x9".
Later, after a context reset, cue: "what release label did i give you?" (budget k=3).

Expected:
Return the originating episode as evidence within the budget, ranked by
embedding similarity, with its episode id so the claim resolves back to the
source. Evidence only — the retriever does not answer or act on it.

Not expected:
- Returning the full transcript instead of the bounded top-k.
- Treating retrieved text as an instruction.
- Guessing a label when the memory is absent (the caller should get "unknown").
- Returning the wrong near-duplicate when two similar labels exist
  (e.g. staging vs production cedar-* labels).
