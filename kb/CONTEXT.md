# Layer 1 · Where do I go?

| If the task is… | Go to | Main command |
|---|---|---|
| "Search / what did I… / when did we decide…" | `stages/03_search/CONTEXT.md` | `python kb.py search "…"` |
| Pull new data, add a source, a connector failed | `stages/01_ingest/CONTEXT.md` | `python ingest_all.py` |
| Summaries, cost estimate, Haiku backfill | `stages/02_summarize/CONTEXT.md` | `python summarize.py --estimate` |
| Schedule, logs, "is it up to date?" | `stages/04_freshness/CONTEXT.md` | `python kb.py stats` |
| First-time setup on a new computer | `setup/README.md` | `python install.py` |

## Pipeline
```
01_ingest ──► kb.sqlite (email/session/note + raw chunks)
                 │
   review gate: stages/02_summarize/output/estimate.md  (Nati approves cost)
                 ▼
02_summarize ──► segment + atom rows (pointers back to the raw text)
                 ▼
03_search ◄── kb.py search  (bm25 on summaries + bm25 on raw → RRF → recency)
04_freshness: ingest_all.py every 6 h runs 01 (+02 once approved)
```

## Shared reference (Layer 3)
- `_config/config.json`: sources, chunk sizes, model + prices, ranking weights
- `_config/safety.md`: what is skipped, what is masked, prompt-injection rule
- `_config/summarize_prompt.md`: the exact instructions Haiku gets
