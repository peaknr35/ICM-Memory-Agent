Input:
Two claims: "the production release label is cedar aaa111" and
"the production release label is cedar bbb222".

Expected:
Flag both as `contradicted` (same subject, different value) and keep both with
their sources for later resolution. A contradicted claim cannot be approved.

Not expected:
- Deleting or silently overwriting either claim.
- Flagging two claims that merely share a couple of common words but are about
  different subjects.
