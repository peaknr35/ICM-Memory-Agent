Input:
A trained adapter and a held-out evaluation (run by an evaluator that is
separate from whatever produced the adapter).

Expected:
Mark the adapter `validated` only if it improves on the rollback baseline with
no regressions; otherwise `rejected`. The producer never grades its own work.
Validation alone does not deploy — deployment is approval-required.

Not expected:
- Passing an adapter that regresses on the held-out set.
- Using the training outcome (or the trainer) as its own grade.
- Changing the active release or weights (that is release_manager + approval).
