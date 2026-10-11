Input:
A recurring capability gap, with context+retrieval baselines already tried,
≥2 validated examples, authorized data, a held-out eval, and a rollback target.

Expected:
Run the 5-question diagnosis; since all pass, write one candidate
TrainingProposal citing the example ids as lineage, with the recipe, held-out
eval, and rollback target recorded. Does not train or change weights.

Not expected:
- Proposing when any prerequisite fails (e.g. unauthorized data, no held-out
  eval, <2 examples) — it returns the failed reasons and writes nothing.
- Proposing for a one-off miss rather than a true repeated gap.
- Proposing when plain memory/retrieval would close the gap.
