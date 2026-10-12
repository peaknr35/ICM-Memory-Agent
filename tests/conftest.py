import os

# Tests must never read a developer's local .env (it may select paid backends).
os.environ.setdefault("ICM_NO_DOTENV", "1")
