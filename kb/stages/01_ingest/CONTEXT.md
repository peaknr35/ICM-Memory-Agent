# Stage 01 · Ingest

One stage, one job: copy new items from each source into `kb.sqlite`. No AI here.

## Inputs
- Layer 3: `../../_config/config.json` → `sources`, `chunking`
- Layer 3: `../../_config/safety.md`
- Sources: Gmail API (read-only token in `secrets/`), `~/.claude/projects/**/*.jsonl`, optional notes folders

## Process
`python ingest_all.py [gmail|claude_code|notes]`, which calls `connectors.py`:

| Source | New-since-last-run rule | One item = | Pointer |
|---|---|---|---|
| gmail | 1st run: `after:` 365 days ago. Later: last run minus 3 days. Threads skipped if their `historyId` is unchanged. | one thread | `metadata.url` (opens in Gmail) |
| claude_code | file `mtime:size` watermark per `.jsonl` | one session | `metadata.path` |
| notes | file `mtime:size` watermark | one file | `metadata.path` |

Each item goes through `replace_rows(source, source_id, rows)`: delete its old rows,
insert new ones, so re-runs never duplicate. Every row gets `ts`.
Items longer than `long_threshold_chars` (6,000) are stored as a short header row
plus `raw` rows of 4,000 characters. Short items are one row.

Before storing: password-reset/2FA mail is skipped, secrets are masked (`kbcore.py`).

## Outputs
- rows in `kb.sqlite` (`docs`, `ingest_state`)
- `output/last_run.md`: per-connector counts and errors. **Read this after a run.**

## Adding a source
Write `ingest_<name>(db, cfg)` in `connectors.py` following the pattern of
`ingest_notes`, add it to `CONNECTORS`, and add a block under `sources` in config.json.
