# Setup on your computer

Works on Windows, Mac and Linux with Python 3.10+.

## 1. Put the folder somewhere permanent
Unzip it to e.g. `C:\Users\<you>\kb` (Windows) or `~/kb`. Don't leave it in Downloads.
The schedule and the CLAUDE.md section point at this exact path. If you move it later,
re-run `python install.py`.

## 2. Run the installer
Windows PowerShell:
```powershell
cd $HOME\kb
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python install.py
```
Mac / Linux: same with `python3 -m venv .venv && source .venv/bin/activate && python install.py`.

It asks before each step: install packages, create `.env`, create `kb.sqlite`, add the
search section to `~/.claude/CLAUDE.md`, raise `cleanupPeriodDays`, register the 6-hour schedule.

## 3. Your API key
Open `.env` in a text editor and paste your key: `ANTHROPIC_API_KEY=sk-ant-...`
(from <https://console.anthropic.com/settings/keys>). Only needed for summaries.

## 4. Claude Code sessions (no login needed)
```
python ingest_all.py claude_code
python kb.py stats
```

## 5. Gmail
Follow `gmail_oauth.md`, then `python ingest_all.py gmail`.

## 6. Summaries (costs money: you approve)
```
python summarize.py --estimate     # prints count + $ estimate, nothing is sent
python summarize.py --run          # asks y/N, then summarizes
```
Then set `"auto_summarize": true` in `_config/config.json` so new long items get summarized on each scheduled run.

## 7. Try it
```
python kb.py search "andon assistant" --after 2026-09-01
```

See `claude_code_retention.md` for keeping sessions longer than 30 days.
