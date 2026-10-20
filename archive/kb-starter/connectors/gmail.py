"""Gmail connector — one doc per recent message, per configured account.
Accounts are defined in config.json; OAuth tokens live in ./secrets/
(created by gmail_auth.py, gitignored).
"""
import base64
import sys
from datetime import datetime, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

SECRETS = Path(__file__).parent.parent / "secrets"


def _service(account):
    creds = Credentials.from_authorized_user_file(str(SECRETS / f"token_{account}.json"))
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _body(payload):
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        text = _body(part)
        if text:
            return text
    return ""


def fetch(per_account=None, query=None):
    cfg = config.load().get("gmail", {})
    accounts = cfg.get("accounts", [])
    per_account = per_account or cfg.get("per_account", 100)
    query = query or cfg.get("query", "newer_than:90d -category:promotions")
    docs = []
    for account in accounts:
        try:
            svc = _service(account)
            msgs = svc.users().messages().list(userId="me", q=query, maxResults=per_account).execute().get("messages", [])
        except Exception as e:
            print(f"  {account}: skipped ({e})")
            continue
        for ref in msgs:
            m = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
            ts = datetime.fromtimestamp(int(m["internalDate"]) / 1000, tz=timezone.utc).isoformat()
            body = _body(m["payload"]) or m.get("snippet", "")
            docs.append(dict(
                source="gmail", source_id=f"{account}:{m['id']}", ts=ts,
                title=headers.get("subject", "(no subject)"),
                content=f"From: {headers.get('from','')}\nTo: {headers.get('to','')}\n\n{body[:12000]}",
                metadata={"account": account, "from": headers.get("from", ""), "thread": m.get("threadId")},
            ))
        print(f"  {account}: {len(msgs)} messages")
    return docs
