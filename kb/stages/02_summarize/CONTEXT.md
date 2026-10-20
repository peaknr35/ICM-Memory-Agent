# Stage 02 · Summarize (costs money: review gate)

One stage, one job: give long items search-friendly pointers. Raw text is never changed.

## Inputs
- Layer 4: long items in `kb.sqlite` (header row with `metadata.long = 1` + their `raw` chunks)
- Layer 3: `../../_config/summarize_prompt.md` (the instructions Haiku gets)
- Layer 3: `../../_config/config.json` → `summarize` (model, prices, limits)
- `.env` → `ANTHROPIC_API_KEY` (never print it)

## Process
1. `python summarize.py --estimate` writes `output/estimate.md` (item count + $ estimate).
2. **Gate:** show Nati the estimate. Only he approves the spend.
3. `python summarize.py --run` makes one Haiku call per item (forced tool call, JSON out) and writes:
   - `segment` rows: title, the question someone would type, 2–3 sentence summary
   - `atom` rows: exact errors + fixes, commands, decisions + reasons, file paths
4. After the backfill, if Nati agrees, set `summarize.auto_summarize: true` so each
   scheduled run summarizes only the new long items (usually cents).

Sessions touched in the last `min_idle_hours` (2) wait until the next run (they may still be going).
If an item changes, ingest deletes its old summaries and this stage redoes it.

## Outputs
- `segment` + `atom` rows (same `source_id` as the original, so results point back)
- `output/estimate.md`, `output/last_run.md` (actual tokens and cost)

## Edit surface
Change how summaries look by editing `_config/summarize_prompt.md`. To redo
everything: `DELETE FROM docs WHERE kind IN ('segment','atom'); DELETE FROM ingest_state WHERE source='_summary';`
(ask first: this means paying again).
