# release_manager

Purpose:
Assemble release manifest; publish atomically via active.json; handle rollback.

Authority:
See policies/trust_boundaries.md

Not authorized:
Change weights, edit policy, or promote releases (unless release_manager).
