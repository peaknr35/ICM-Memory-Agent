Input:
Episodic store with: "deploy uses the staging config and token rotation",
"staging config requires token rotation before deploy", and an unrelated
"lunch was a cheese sandwich".

Expected:
Cluster the two staging/deploy episodes together (high token overlap) and hand
that cluster to consolidation. Never re-executes the actions in the episodes.

Not expected:
- Emitting the singleton unrelated episode as a cluster (consolidation needs ≥2).
- Modifying or deleting any episode (episodes are immutable).
