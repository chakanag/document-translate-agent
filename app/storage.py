import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from app.config import BLOCKS_DIR, DB_PATH, ensure_storage_dirs
from app.models import DocumentBlock, Session, TranslationJob, User


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    ensure_storage_dirs()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db() -> None:
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS translation_jobs (
                id TEXT PRIMARY KEY,
                original_file_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                source_language TEXT,
                target_language TEXT NOT NULL,
                output_format TEXT NOT NULL,
                ai_provider TEXT NOT NULL DEFAULT 'demo',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT,
                original_path TEXT,
                exported_path TEXT,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                user_id TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS webauthn_credentials (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                public_key BLOB NOT NULL,
                sign_count INTEGER NOT NULL DEFAULT 0,
                device_name TEXT,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS webauthn_challenges (
                challenge TEXT PRIMARY KEY,
                user_id TEXT,
                username TEXT,
                type TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        # 마이그레이션: 기존 테이블에 컬럼 추가
        _migrate(con)


def _migrate(con: sqlite3.Connection) -> None:
    job_cols = {r["name"] for r in con.execute("PRAGMA table_info(translation_jobs)").fetchall()}
    if "ai_provider" not in job_cols:
        con.execute("ALTER TABLE translation_jobs ADD COLUMN ai_provider TEXT NOT NULL DEFAULT 'demo'")
    if "user_id" not in job_cols:
        con.execute("ALTER TABLE translation_jobs ADD COLUMN user_id TEXT")
    if "ocr_engine" not in job_cols:
        con.execute("ALTER TABLE translation_jobs ADD COLUMN ocr_engine TEXT NOT NULL DEFAULT 'none'")


# ── Jobs ──────────────────────────────────────────────────────────────

def row_to_job(row: sqlite3.Row) -> TranslationJob:
    return TranslationJob(
        id=row["id"],
        originalFileName=row["original_file_name"],
        fileType=row["file_type"],
        sourceLanguage=row["source_language"],
        targetLanguage=row["target_language"],
        outputFormat=row["output_format"],
        aiProvider=row["ai_provider"],
        status=row["status"],
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
        completedAt=row["completed_at"],
        errorMessage=row["error_message"],
        originalPath=row["original_path"],
        exportedPath=row["exported_path"],
        warnings=json.loads(row["warnings_json"] or "[]"),
        userId=row["user_id"] if "user_id" in row.keys() else None,
        ocrEngine=row["ocr_engine"] if "ocr_engine" in row.keys() else "none",
    )


def create_job(job: TranslationJob) -> TranslationJob:
    with connect() as con:
        con.execute(
            """
            INSERT INTO translation_jobs (
                id, original_file_name, file_type, source_language, target_language,
                output_format, ai_provider, status, created_at, updated_at, completed_at,
                error_message, original_path, exported_path, warnings_json, user_id, ocr_engine
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.originalFileName,
                job.fileType,
                job.sourceLanguage,
                job.targetLanguage,
                job.outputFormat,
                job.aiProvider,
                job.status,
                job.createdAt,
                job.updatedAt,
                job.completedAt,
                job.errorMessage,
                job.originalPath,
                job.exportedPath,
                json.dumps(job.warnings, ensure_ascii=False),
                job.userId,
                job.ocrEngine,
            ),
        )
    return job


def update_job(job_id: str, **changes: object) -> TranslationJob:
    allowed = {
        "source_language": "source_language",
        "status": "status",
        "updated_at": "updated_at",
        "completed_at": "completed_at",
        "error_message": "error_message",
        "exported_path": "exported_path",
        "warnings_json": "warnings_json",
    }
    assignments = []
    values = []
    for key, value in changes.items():
        if key not in allowed:
            raise ValueError(f"Unsupported job update field: {key}")
        assignments.append(f"{allowed[key]} = ?")
        values.append(value)
    assignments.append("updated_at = ?")
    values.append(utc_now())
    values.append(job_id)
    with connect() as con:
        con.execute(f"UPDATE translation_jobs SET {', '.join(assignments)} WHERE id = ?", values)
    job = get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    return job


def get_job(job_id: str) -> Optional[TranslationJob]:
    with connect() as con:
        row = con.execute("SELECT * FROM translation_jobs WHERE id = ?", (job_id,)).fetchone()
    return row_to_job(row) if row else None


def list_jobs(user_id: Optional[str] = None) -> List[TranslationJob]:
    with connect() as con:
        if user_id is not None:
            rows = con.execute(
                "SELECT * FROM translation_jobs WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM translation_jobs ORDER BY created_at DESC").fetchall()
    return [row_to_job(row) for row in rows]


def delete_job(job_id: str) -> bool:
    job = get_job(job_id)
    if job is None:
        return False
    for raw_path in (job.originalPath, job.exportedPath, str(blocks_path(job_id))):
        if not raw_path:
            continue
        path = Path(raw_path)
        if path.exists() and path.is_file():
            path.unlink()
    with connect() as con:
        con.execute("DELETE FROM translation_jobs WHERE id = ?", (job_id,))
    return True


def blocks_path(job_id: str) -> Path:
    return BLOCKS_DIR / f"{job_id}.json"


def save_blocks(job_id: str, blocks: Iterable[DocumentBlock]) -> None:
    payload = [block.to_dict() for block in blocks]
    blocks_path(job_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_blocks(job_id: str) -> List[DocumentBlock]:
    path = blocks_path(job_id)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    blocks = []
    for item in payload:
        bbox = tuple(item["bbox"]) if item.get("bbox") else None
        blocks.append(
            DocumentBlock(
                id=item["id"],
                type=item["type"],
                sourceText=item["sourceText"],
                translatedText=item.get("translatedText"),
                pageNumber=item.get("pageNumber"),
                sheetName=item.get("sheetName"),
                bbox=bbox,
                fontSize=item.get("fontSize"),
                order=item["order"],
                metadata=item.get("metadata") or {},
            )
        )
    return blocks


# ── Users ─────────────────────────────────────────────────────────────

def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        role=row["role"],
        isActive=bool(row["is_active"]),
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def create_user(user: User) -> User:
    with connect() as con:
        con.execute(
            "INSERT INTO users (id, username, email, role, is_active, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (user.id, user.username, user.email, user.role, int(user.isActive), user.createdAt, user.updatedAt),
        )
    return user


def get_user_by_id(user_id: str) -> Optional[User]:
    with connect() as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_username(username: str) -> Optional[User]:
    with connect() as con:
        row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _row_to_user(row) if row else None


def count_users() -> int:
    with connect() as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def list_users() -> List[User]:
    with connect() as con:
        rows = con.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
    return [_row_to_user(r) for r in rows]


def update_user(user_id: str, **changes: object) -> bool:
    allowed = {"role", "is_active", "email"}
    assignments, values = [], []
    for key, val in changes.items():
        if key not in allowed:
            raise ValueError(f"Unsupported user update field: {key}")
        assignments.append(f"{key} = ?")
        values.append(val)
    if not assignments:
        return False
    assignments.append("updated_at = ?")
    values.extend([utc_now(), user_id])
    with connect() as con:
        cur = con.execute(f"UPDATE users SET {', '.join(assignments)} WHERE id = ?", values)
    return cur.rowcount > 0


def delete_user(user_id: str) -> bool:
    with connect() as con:
        cur = con.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return cur.rowcount > 0


# ── WebAuthn Credentials ──────────────────────────────────────────────

def create_credential(credential_id: str, user_id: str, public_key: bytes,
                      sign_count: int, device_name: Optional[str]) -> None:
    now = utc_now()
    with connect() as con:
        con.execute(
            "INSERT INTO webauthn_credentials (id, user_id, public_key, sign_count, device_name, created_at) VALUES (?,?,?,?,?,?)",
            (credential_id, user_id, public_key, sign_count, device_name, now),
        )


def get_credentials_by_user(user_id: str) -> List[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM webauthn_credentials WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_credential_by_id(credential_id: str) -> Optional[dict]:
    with connect() as con:
        row = con.execute("SELECT * FROM webauthn_credentials WHERE id = ?", (credential_id,)).fetchone()
    return dict(row) if row else None


def update_credential_sign_count(credential_id: str, sign_count: int) -> None:
    with connect() as con:
        con.execute(
            "UPDATE webauthn_credentials SET sign_count = ?, last_used_at = ? WHERE id = ?",
            (sign_count, utc_now(), credential_id),
        )


# ── Sessions ──────────────────────────────────────────────────────────

def create_session(session: Session) -> Session:
    with connect() as con:
        con.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (session.id, session.userId, session.createdAt, session.expiresAt),
        )
    return session


def get_session(session_id: str) -> Optional[Session]:
    with connect() as con:
        row = con.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return None
    return Session(id=row["id"], userId=row["user_id"], createdAt=row["created_at"], expiresAt=row["expires_at"])


def delete_session(session_id: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def delete_expired_sessions() -> None:
    with connect() as con:
        con.execute("DELETE FROM sessions WHERE expires_at < ?", (utc_now(),))


# ── WebAuthn Challenges ───────────────────────────────────────────────

def create_challenge(challenge: str, user_id: Optional[str], username: Optional[str],
                     challenge_type: str, expires_at: str) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO webauthn_challenges (challenge, user_id, username, type, expires_at) VALUES (?,?,?,?,?)",
            (challenge, user_id, username, challenge_type, expires_at),
        )


def get_challenge(challenge: str) -> Optional[dict]:
    with connect() as con:
        row = con.execute("SELECT * FROM webauthn_challenges WHERE challenge = ?", (challenge,)).fetchone()
    return dict(row) if row else None


def delete_challenge(challenge: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM webauthn_challenges WHERE challenge = ?", (challenge,))


def delete_expired_challenges() -> None:
    with connect() as con:
        con.execute("DELETE FROM webauthn_challenges WHERE expires_at < ?", (utc_now(),))


# ── Admin Stats ───────────────────────────────────────────────────────

def get_stats() -> dict:
    with connect() as con:
        total_users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_users = con.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]
        total_jobs = con.execute("SELECT COUNT(*) FROM translation_jobs").fetchone()[0]
        status_rows = con.execute(
            "SELECT status, COUNT(*) as cnt FROM translation_jobs GROUP BY status"
        ).fetchall()
    jobs_by_status = {r["status"]: r["cnt"] for r in status_rows}
    return {
        "totalUsers": total_users,
        "activeUsers": active_users,
        "totalJobs": total_jobs,
        "jobsByStatus": jobs_by_status,
    }
