# Gmail read-only login: one step at a time

Takes about 10 minutes, once. Free. Do one step, check it worked, then the next.
You're creating your **own** private Google "app" that only you use, with permission
to *read* mail and nothing else (`gmail.readonly`: it can't send, delete or change anything).

### Step 1: Make a Google Cloud project
1. Go to <https://console.cloud.google.com/> and sign in with the Gmail account you want indexed.
2. Top bar → project picker → **New project** → name it `personal-kb` → **Create**.
3. Make sure `personal-kb` is selected in the project picker.

✅ Check: the top bar says `personal-kb`.

### Step 2: Turn on the Gmail API
1. Menu ☰ → **APIs & Services → Library**.
2. Search **Gmail API** → open it → **Enable**.

✅ Check: you land on a "Gmail API" page with a **Manage** button.

### Step 3: Set up the consent screen
1. Menu ☰ → **Google Auth Platform** (older consoles: *APIs & Services → OAuth consent screen*) → **Get started**.
2. App name `personal-kb`, support email: your Gmail → **Next**.
3. Audience: **External** → **Next**.
4. Contact email: your Gmail → **Next** → agree → **Create**.

### Step 4: Add yourself as a test user
1. Google Auth Platform → **Audience** → *Test users* → **Add users** → your Gmail → **Save**.

✅ Check: your address is listed under Test users.

### Step 5: Add the read-only scope
1. Google Auth Platform → **Data Access** → **Add or remove scopes**.
2. Filter for `gmail.readonly` → tick `https://www.googleapis.com/auth/gmail.readonly` → **Update** → **Save**.

### Step 6: Create the desktop client and download it
1. Google Auth Platform → **Clients** → **Create client**.
2. Application type: **Desktop app**, name `kb-desktop` → **Create**.
3. Click **Download JSON**.
4. Rename the file to `gmail_credentials.json` and move it into this folder's `secrets/` folder.

✅ Check: `secrets/gmail_credentials.json` exists. **Don't share this file or commit it.**

### Step 7: Log in (Claude asks you before this step)
```
python gmail_auth.py personal
```
A browser opens. Choose your account. You'll see **"Google hasn't verified this app."**
That's expected, because it's your own app. Click **Continue**, then allow **"View your email messages and settings"**.
The terminal prints `Saved Gmail login for 'personal'`.

**About the 7-day expiry:** while the app's publishing status is *Testing*, Google
expires the login after 7 days, and the scheduled run will log `invalid_grant`.
Two fixes:
- **Easy:** re-run `python gmail_auth.py personal` when that happens.
- **Permanent:** Google Auth Platform → **Audience** → **Publish app** → *In production*.
  For a personal app you don't need to submit for verification. You'll keep seeing the
  "unverified app" warning when you log in, but the login stops expiring. Then run step 7 once more.

### Step 8: First pull (12 months)
```
python ingest_all.py gmail
python kb.py stats
```
The first run can take a while for a busy inbox (roughly 5–15 threads per second).
Later runs only look at the last few days.

Want a second account (e.g. work)? Repeat step 7 with `python gmail_auth.py work`.
Promotions, social, spam and trash are excluded. Change `query_extra` in `_config/config.json`.
