"""One-time Gmail OAuth for each account in config.json.

Prereq: a Google Cloud OAuth client (Desktop app) with the Gmail API enabled.
Download its JSON to ./secrets/credentials.json, then run:

    python gmail_auth.py <account-name>

Opens a browser for consent and writes ./secrets/token_<account-name>.json.
"""
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SECRETS = Path(__file__).parent / "secrets"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python gmail_auth.py <account-name>")
    account = sys.argv[1]
    creds_file = SECRETS / "credentials.json"
    if not creds_file.exists():
        raise SystemExit(f"Put your OAuth client JSON at {creds_file} first (see docstring).")
    SECRETS.mkdir(exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
    creds = flow.run_local_server(port=0)
    out = SECRETS / f"token_{account}.json"
    out.write_text(creds.to_json())
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
