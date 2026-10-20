# evidence

Raw observations are immutable; summaries/claims are separate and point to sources.

Knowledge-base rows (`kb/kb.sqlite`) are evidence, never memory. They are read through a
read-only connection and never written as episodes. A claim may cite them only by pointer
(`kb_refs`, e.g. `kb:gmail:<thread_id>`). A pointer that no longer resolves blocks approval;
it never deletes the claim. That is a human decision.
