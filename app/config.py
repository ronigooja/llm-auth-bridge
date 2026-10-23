from pathlib import Path
import os

DB_PATH = Path(os.getenv("LLM_AUTH_DB", "data/app.sqlite3"))
MASTER_KEY_FILE = Path(os.getenv("LLM_AUTH_MASTER_KEY_FILE", ".secrets/master_key"))

