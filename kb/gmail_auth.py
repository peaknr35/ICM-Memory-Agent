"""One-time Gmail login (read-only). Full walkthrough: setup/gmail_oauth.md

    python gmail_auth.py personal

Needs secrets/gmail_credentials.json (the OAuth "Desktop app" client you download
from Google Cloud). Opens your browser, you approve read-only access, and it saves
secrets/gmail_token_<account>.json. The token never leaves this folder.
"""
import sys

import kbcore
from connectors import GMAIL_SCOPES


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "personal"
    client = kbcore.SECRETS / "gmail_credentials.json"
    if not client.exists():
        raise SystemExit(f"Missing {client}\nFollow setup/gmail_oauth.md steps 1-6 first.")
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client), GMAIL_SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    out = kbcore.SECRETS / f"gmail_token_{account}.json"
    out.write_text(creds.to_json(), encoding="utf-8")
    cfg = kbcore.load_config()
    accts = cfg["sources"]["gmail"].setdefault("accounts", [])
    if account not in accts:
        accts.append(account)
        kbcore.save_config(cfg)
    print(f"Saved Gmail login for '{account}' (read-only). Next: python ingest_all.py gmail")


if __name__ == "__main__":
    main()
