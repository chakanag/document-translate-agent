import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
ORIGINALS_DIR = STORAGE_DIR / "originals"
BLOCKS_DIR = STORAGE_DIR / "blocks"
EXPORTS_DIR = STORAGE_DIR / "exports"
DB_PATH = STORAGE_DIR / "jobs.sqlite3"

SUPPORTED_INPUT_TYPES = {"pdf", "doc", "docx", "txt", "md", "xls", "xlsx"}
SUPPORTED_OUTPUT_TYPES = {"pdf", "doc", "docx", "txt", "md", "xls", "xlsx"}

DEFAULT_TARGET_LANGUAGE = "ko"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

# WebAuthn / 세션 설정
RP_ID = os.environ.get("RP_ID", "localhost")
RP_NAME = "Document Translate Agent"
RP_ORIGIN = os.environ.get("RP_ORIGIN", "http://localhost:8010")
SESSION_DURATION_DAYS = 30
CHALLENGE_TTL_SECONDS = 300  # 5분


def ensure_storage_dirs() -> None:
    for path in (STORAGE_DIR, ORIGINALS_DIR, BLOCKS_DIR, EXPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)
