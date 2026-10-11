# Project

Purpose:
An agent that improves at a job by managing its own memory rather than being
retrained each time. The default is the cheap, reversible move — write the
experience to persistent memory and recall it later. Parameter learning
(training an adapter) is the gated exception: triggered only by a repeated
capability gap, and only once safety prerequisites hold.

Built as an ICM workspace — the folder tree is the architecture: each agent is
a folder of plain-text contracts; `runtime/` enforces them.

Invariants:
- Retrieved memory is evidence, never instructions.
- Memory is scoped (user/project/session) and deletable; deleting an episode
  also removes any derived claim that cited it.

See README.md for the full write-up.
