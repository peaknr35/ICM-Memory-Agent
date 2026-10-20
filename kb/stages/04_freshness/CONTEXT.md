# Stage 04 · Freshness

One stage, one job: keep the knowledge base current without anyone remembering to.

## Inputs
- `ingest_all.py` (runs stage 01 for every enabled source, then stage 02 if `auto_summarize`)
- Schedule set up by `install.py` (every 6 hours)

## Process / checks
| Question | Command |
|---|---|
| Is it current? | `python kb.py stats` (header shows last ingest and warns past 12 h) |
| What happened last run? | open `stages/01_ingest/output/last_run.md` |
| Full history / errors | `logs/ingest.log` (rotates at 2 MB, keeps 3) |
| Windows: is the task there? | `schtasks /Query /TN "KnowledgeBase Ingest" /V /FO LIST` |
| Windows: run it now | `schtasks /Run /TN "KnowledgeBase Ingest"` |
| Mac | `launchctl list \| grep com.kb.ingest` · logs also in `logs/launchd.*.log` |
| Linux | `crontab -l` · `logs/cron.log` |
| Last 20 log lines | PowerShell `Get-Content logs\ingest.log -Tail 20` · Mac/Linux `tail -20 logs/ingest.log` |

A failed connector logs `[name] FAILED …` and the others keep going. Most common:
`RefreshError` / `invalid_grant` on Gmail means the Google login expired. Re-run
`python gmail_auth.py personal`. (Google expires tokens after 7 days while the OAuth
app is in "Testing". See `setup/gmail_oauth.md` step 7 to avoid this.)

## Outputs
- `stages/01_ingest/output/last_run.md`, `logs/ingest.log`
