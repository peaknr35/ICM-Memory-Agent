"""Slack connector — pulls channel history, resolves threads, distills each
thread into a structured artifact (question / summary / resolution) with a
small LLM before it lands in the embeddings table. Raw one-off messages are
stored as-is; short filler ("sounds good, thanks!") is filtered out.
"""
import json
import os
import time
from datetime import datetime, timezone

import requests

API = "https://slack.com/api"
DISTILL_MODEL = "claude-haiku-4-5-20251001"
MIN_CHARS = 60  # skip pure-filler messages

DISTILL_PROMPT = """Distill this Slack thread into a JSON object with keys:
- "question": the one-line question someone would search for
- "summary": 1-2 sentence summary
- "resolution": how it was resolved (or "unresolved")
- "systems": list of tools/systems mentioned

Thread from #{channel}:
{transcript}

Reply with ONLY the JSON object."""


def _token():
    tok = os.environ.get("SLACK_USER_TOKEN") or os.environ.get("SLACK_BOT_TOKEN")
    if not tok:
        raise RuntimeError("No SLACK_USER_TOKEN / SLACK_BOT_TOKEN in env")
    return tok


def _call(method, **params):
    for attempt in range(4):
        resp = requests.get(f"{API}/{method}", params=params, headers={"Authorization": f"Bearer {_token()}"}, timeout=30)
        data = resp.json()
        if data.get("ok"):
            return data
        if data.get("error") == "ratelimited":
            time.sleep(int(resp.headers.get("Retry-After", 5)))
            continue
        raise RuntimeError(f"Slack {method}: {data.get('error')}")
    raise RuntimeError(f"Slack {method}: rate limited")


def _users(limit=500):
    data = _call("users.list", limit=limit)
    return {u["id"]: u["profile"].get("display_name") or u["profile"].get("real_name", "?") for u in data["members"]}


def _distill(channel, transcript):
    import anthropic

    msg = anthropic.Anthropic().messages.create(
        model=DISTILL_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": DISTILL_PROMPT.format(channel=channel, transcript=transcript[:8000])}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return json.loads(text)


def fetch(per_channel=100, distill=True):
    """Yield doc dicts: one per thread, one per substantive standalone message."""
    users = _users()
    channels = _call("conversations.list", types="public_channel,private_channel", exclude_archived="true", limit=200)["channels"]
    docs = []
    for ch in channels:
        if not ch.get("is_member") and ch.get("is_private"):
            continue
        try:
            history = _call("conversations.history", channel=ch["id"], limit=per_channel)["messages"]
        except RuntimeError as e:
            print(f"  #{ch['name']}: skipped ({e})")
            continue
        for m in history:
            if m.get("subtype") or not m.get("text"):
                continue
            ts_iso = datetime.fromtimestamp(float(m["ts"]), tz=timezone.utc).isoformat()
            author = users.get(m.get("user", ""), "?")
            if m.get("thread_ts") == m["ts"] and int(m.get("reply_count", 0)) > 0:
                replies = _call("conversations.replies", channel=ch["id"], ts=m["ts"], limit=50)["messages"]
                transcript = "\n".join(f"{users.get(r.get('user',''),'?')}: {r.get('text','')}" for r in replies)
                title, content = f"#{ch['name']}: {m['text'][:80]}", transcript
                if distill:
                    try:
                        art = _distill(ch["name"], transcript)
                        title = art.get("question") or title
                        content = (
                            f"Q: {art.get('question','')}\nSummary: {art.get('summary','')}\n"
                            f"Resolution: {art.get('resolution','')}\nSystems: {', '.join(art.get('systems') or [])}\n\n"
                            f"--- transcript ---\n{transcript}"
                        )
                    except Exception as e:
                        print(f"  distill failed ({e}), storing raw")
                docs.append(dict(
                    source="slack", source_id=f"{ch['id']}:{m['ts']}", ts=ts_iso, title=title, content=content,
                    metadata={"channel": ch["name"], "author": author, "replies": m.get("reply_count", 0)},
                ))
            elif not m.get("thread_ts") and len(m["text"]) >= MIN_CHARS:
                docs.append(dict(
                    source="slack", source_id=f"{ch['id']}:{m['ts']}", ts=ts_iso,
                    title=f"#{ch['name']}: {m['text'][:80]}", content=f"{author}: {m['text']}",
                    metadata={"channel": ch["name"], "author": author},
                ))
        print(f"  #{ch['name']}: {len(history)} messages scanned")
    return docs
