Input:
One approved semantic claim in scope `default`; active.json currently at
`release_0000`.

Expected:
Write an immutable `manifests/release_0001.json` pinning the approved claims +
lineage and workspace/policy/memory/model/adapter/retrieval/permissions
(`adapter` is null — weights are Stage 4), then swap active.json to
`release_0001` atomically. `rollback()` repoints active.json back to
`release_0000`; both manifests are preserved.

Not expected:
- Including `candidate` or `contradicted` claims in a release.
- Mutating a published manifest, or losing the previous release on rollback.
- Changing model weights.
