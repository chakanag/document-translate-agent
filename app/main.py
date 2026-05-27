import cgi
import json
import logging
import mimetypes
import os
import threading
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple
from urllib.parse import parse_qs, quote

from app.admin.routes import AdminRouter
from app.auth import rate_limit
from app.auth.routes import AuthRouter, _parse_cookie
from app.config import BASE_DIR, DEFAULT_TARGET_LANGUAGE, MAX_UPLOAD_BYTES, ensure_storage_dirs

logger = logging.getLogger(__name__)
from app.models import TranslationJob
from app.services.pipeline import create_translation_job, export_translation_job, run_translation_pipeline
from app.services.translation import available_providers
from app.storage import (
    delete_expired_challenges,
    delete_expired_sessions,
    delete_job,
    get_job,
    get_session,
    get_user_by_id,
    init_db,
    list_jobs,
    load_blocks,
    save_blocks,
    utc_now,
)


RouteHandler = Callable[[Dict[str, Any], bytes], Tuple[int, Dict[str, str], bytes]]

SECURITY_HEADERS: Dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "frame-src 'self' blob:; "
        "connect-src 'self'; "
        "img-src 'self' data: blob:; "
        # PDF.js가 CJK 폰트를 합성할 때 data: / blob: URI를 사용하므로 허용
        "font-src 'self' data: blob:;"
    ),
}

# 파일 형식별 매직바이트 (오프셋, 시그니처)
# OLE2 컴파운드 문서 헤더 = .doc / .xls
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FILE_MAGIC: Dict[str, bytes] = {
    "pdf":  b"%PDF",
    "docx": b"PK\x03\x04",   # ZIP 기반
    "xlsx": b"PK\x03\x04",
    "doc":  _OLE2_MAGIC,
    "xls":  _OLE2_MAGIC,
}


def _get_client_ip(scope: Dict[str, Any]) -> str:
    """nginx X-Forwarded-For 헤더에서 실제 클라이언트 IP를 추출."""
    headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
    xff = headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


_auth_router = AuthRouter()
_admin_router = AdminRouter()


class App:
    def __init__(self) -> None:
        ensure_storage_dirs()
        init_db()
        # 백그라운드에서 만료 데이터 주기적 정리
        threading.Thread(target=self._cleanup_loop, daemon=True).start()

    def _cleanup_loop(self) -> None:
        import time
        while True:
            time.sleep(3600)
            try:
                delete_expired_sessions()
                delete_expired_challenges()
            except Exception:
                pass

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            return
        body = await read_body(receive)
        status, headers, payload = self.handle(scope, body)
        await send({"type": "http.response.start", "status": status, "headers": encode_headers(headers)})
        await send({"type": "http.response.body", "body": payload})

    def _get_session_user(self, scope: Dict[str, Any]):
        headers_raw = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        cookie = _parse_cookie(headers_raw.get("cookie", ""))
        session_id = cookie.get("session_id", "")
        if not session_id:
            return None
        session = get_session(session_id)
        if not session or session.expiresAt < utc_now():
            return None
        return get_user_by_id(session.userId)

    def handle(self, scope: Dict[str, Any], body: bytes) -> Tuple[int, Dict[str, str], bytes]:
        try:
            method = scope["method"]
            path = scope["path"]
            ip = _get_client_ip(scope)

            # ── 공개 경로 — 인증 불필요 ──────────────────────────────────
            public = (
                path == "/api/health"
                or path.startswith("/api/auth/")
                or path == "/"
                or path.startswith("/static/")
            )

            # ── 세션 주입 ────────────────────────────────────────────────
            user = self._get_session_user(scope)
            scope["user"] = user

            if not public and user is None:
                return json_response({"error": "Unauthorized"}, 401)

            # ── 일반 API 레이트 리미팅 (IP 기준) ────────────────────────
            if path.startswith("/api/") and not path.startswith("/api/auth/"):
                if not rate_limit.check(ip, "api"):
                    return json_response({"error": "Too many requests"}, 429)

            # ── 인증 라우터 ──────────────────────────────────────────────
            if path.startswith("/api/auth/"):
                status, headers, payload = _auth_router.handle(scope, body)
                headers.update(SECURITY_HEADERS)
                return status, headers, payload

            # ── 어드민 라우터 ────────────────────────────────────────────
            if path.startswith("/api/admin/"):
                status, headers, payload = _admin_router.handle(scope, body)
                headers.update(SECURITY_HEADERS)
                return status, headers, payload

            # ── 정적 파일 ────────────────────────────────────────────────
            if method == "GET" and path == "/":
                return file_response(Path("app/static/index.html"))
            if method == "GET" and path.startswith("/static/"):
                static_root = (BASE_DIR / "app" / "static").resolve()
                target = (BASE_DIR / "app" / path.lstrip("/")).resolve()
                if not str(target).startswith(str(static_root) + os.sep) and str(target) != str(static_root):
                    return json_response({"error": "Forbidden"}, 403)
                return file_response(target)

            # ── API ──────────────────────────────────────────────────────
            if method == "GET" and path == "/api/health":
                return json_response({"ok": True})
            if method == "GET" and path == "/api/providers":
                return json_response({"providers": available_providers()})
            if method == "POST" and path == "/api/documents":
                if not rate_limit.check(ip, "upload"):
                    return json_response({"error": "Too many uploads. Please wait a moment."}, 429)
                return self.create_document(scope, body)
            if method == "GET" and path == "/api/history":
                user_id = user.id if user.role != "admin" else None
                return json_response({"jobs": [job.to_dict() for job in list_jobs(user_id)]})
            if method == "GET" and path.startswith("/api/jobs/") and path.endswith("/preview"):
                job_id = path.split("/")[3]
                return self.preview(job_id, user)
            if method == "POST" and path.startswith("/api/jobs/") and path.endswith("/export"):
                if not rate_limit.check(ip, "export"):
                    return json_response({"error": "Too many requests"}, 429)
                job_id = path.split("/")[3]
                return self.export(job_id, user)
            if method == "GET" and path.startswith("/api/jobs/") and path.endswith("/download"):
                job_id = path.split("/")[3]
                return self.download(job_id, user)
            if method == "GET" and path.startswith("/api/jobs/") and path.endswith("/export-preview"):
                job_id = path.split("/")[3]
                return self.serve_export_preview(job_id, user)
            if method == "GET" and path.startswith("/api/jobs/") and path.endswith("/original"):
                job_id = path.split("/")[3]
                return self.serve_original(job_id, user)
            if method == "GET" and path.startswith("/api/jobs/"):
                job_id = path.split("/")[3]
                job = get_job(job_id)
                if job and not self._can_access_job(job, user):
                    return json_response({"error": "Forbidden"}, 403)
                return json_response(job.to_dict() if job else {"error": "Job not found"}, 200 if job else 404)
            if method == "PATCH" and path.startswith("/api/jobs/") and path.endswith("/blocks"):
                job_id = path.split("/")[3]
                return self.patch_blocks(job_id, body, user)
            if method == "DELETE" and path.startswith("/api/history/"):
                job_id = path.split("/")[3]
                return self.delete_history(job_id, user)
            return json_response({"error": "Not found"}, 404)
        except Exception as exc:
            logger.exception("Unhandled error: %s %s", scope.get("method"), scope.get("path"))
            return json_response({"error": "Internal server error"}, 500)

    def _can_access_job(self, job: TranslationJob, user) -> bool:
        if user is None:
            return False
        if user.role == "admin":
            return True
        return job.userId == user.id

    def create_document(self, scope: Dict[str, Any], body: bytes) -> Tuple[int, Dict[str, str], bytes]:
        form = parse_multipart(scope, body)
        file_item = form.get("file")
        if not isinstance(file_item, UploadedFile):
            return json_response({"error": "file is required"}, 400)
        if len(file_item.content) > MAX_UPLOAD_BYTES:
            return json_response({"error": "file is too large"}, 400)

        # ── 확장자 추출 및 허용 형식 검사 ────────────────────────────────
        ext = Path(file_item.filename).suffix.lower().lstrip(".")
        from app.config import SUPPORTED_INPUT_TYPES
        if ext not in SUPPORTED_INPUT_TYPES:
            return json_response({"error": f"지원하지 않는 파일 형식: .{ext}"}, 400)

        # ── 매직바이트 검증 (확장자 위조 방어) ───────────────────────────
        magic = _FILE_MAGIC.get(ext)
        if magic and not file_item.content.startswith(magic):
            logger.warning("Magic byte mismatch for .%s from %s", ext, _get_client_ip(scope))
            return json_response({"error": "파일 내용이 확장자와 일치하지 않습니다"}, 400)

        target_language = str(form.get("targetLanguage") or DEFAULT_TARGET_LANGUAGE)
        output_format = str(form.get("outputFormat") or ext or "txt")
        ai_provider = str(form.get("aiProvider") or "demo")
        ocr_engine = str(form.get("ocrEngine") or "none")
        if ocr_engine not in {"none", "tesseract", "claude_vision"}:
            ocr_engine = "none"
        user = scope.get("user")
        user_id = user.id if user else None
        job = create_translation_job(
            file_item.filename, file_item.content, target_language,
            output_format, ai_provider, user_id, ocr_engine=ocr_engine,
        )
        thread = threading.Thread(target=run_translation_pipeline, args=(job,), daemon=True)
        thread.start()
        return json_response({"job": job.to_dict()}, 202)

    def preview(self, job_id: str, user) -> Tuple[int, Dict[str, str], bytes]:
        job = get_job(job_id)
        if not job:
            return json_response({"error": "Job not found"}, 404)
        if not self._can_access_job(job, user):
            return json_response({"error": "Forbidden"}, 403)
        return json_response(
            {
                "job": job.to_dict(),
                "blocks": [block.to_dict() for block in load_blocks(job_id)],
                "warnings": job.warnings,
            }
        )

    def export(self, job_id: str, user) -> Tuple[int, Dict[str, str], bytes]:
        job = get_job(job_id)
        if not job:
            return json_response({"error": "Job not found"}, 404)
        if not self._can_access_job(job, user):
            return json_response({"error": "Forbidden"}, 403)
        if job.status not in {"preview_ready", "verified", "completed"}:
            return json_response({"error": f"Job is not ready for export: {job.status}"}, 409)
        exported = export_translation_job(job)
        status = 200 if exported.status == "completed" else 500
        return json_response({"job": exported.to_dict()}, status)

    def patch_blocks(self, job_id: str, body: bytes, user) -> Tuple[int, Dict[str, str], bytes]:
        job = get_job(job_id)
        if not job:
            return json_response({"error": "Job not found"}, 404)
        if not self._can_access_job(job, user):
            return json_response({"error": "Forbidden"}, 403)
        try:
            updates = json.loads(body.decode("utf-8"))
            if not isinstance(updates, list):
                raise ValueError("배열 형식이어야 합니다")
        except Exception as exc:
            return json_response({"error": f"잘못된 요청: {exc}"}, 400)
        blocks = load_blocks(job_id)
        update_map = {u["id"]: u["translatedText"] for u in updates if "id" in u}
        edited = 0
        for block in blocks:
            if block.id in update_map:
                block.translatedText = update_map[block.id]
                edited += 1
        save_blocks(job_id, blocks)
        return json_response({"updated": edited})

    def serve_original(self, job_id: str, user) -> Tuple[int, Dict[str, str], bytes]:
        job = get_job(job_id)
        if not job or not job.originalPath:
            return json_response({"error": "Original file not found"}, 404)
        if not self._can_access_job(job, user):
            return json_response({"error": "Forbidden"}, 403)
        path = Path(job.originalPath)
        if not path.exists():
            return json_response({"error": "Original file is missing on disk"}, 404)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return (
            200,
            {
                "Content-Type": content_type,
                "Content-Disposition": f"inline; filename*=UTF-8''{quote(path.name)}",
                **SECURITY_HEADERS,
            },
            path.read_bytes(),
        )

    def serve_export_preview(self, job_id: str, user) -> Tuple[int, Dict[str, str], bytes]:
        job = get_job(job_id)
        if not job or not job.exportedPath:
            return json_response({"error": "Exported file not found"}, 404)
        if not self._can_access_job(job, user):
            return json_response({"error": "Forbidden"}, 403)
        path = Path(job.exportedPath)
        if not path.exists():
            return json_response({"error": "Exported file is missing on disk"}, 404)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return (
            200,
            {
                "Content-Type": content_type,
                "Content-Disposition": f"inline; filename*=UTF-8''{quote(path.name)}",
                **SECURITY_HEADERS,
            },
            path.read_bytes(),
        )

    def download(self, job_id: str, user) -> Tuple[int, Dict[str, str], bytes]:
        job = get_job(job_id)
        if not job or not job.exportedPath:
            return json_response({"error": "Exported file not found"}, 404)
        if not self._can_access_job(job, user):
            return json_response({"error": "Forbidden"}, 403)
        path = Path(job.exportedPath)
        if not path.exists():
            return json_response({"error": "Exported file is missing on disk"}, 404)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return (
            200,
            {
                "Content-Type": content_type,
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(path.name)}",
                **SECURITY_HEADERS,
            },
            path.read_bytes(),
        )

    def delete_history(self, job_id: str, user) -> Tuple[int, Dict[str, str], bytes]:
        job = get_job(job_id)
        if job and not self._can_access_job(job, user):
            return json_response({"error": "Forbidden"}, 403)
        deleted = delete_job(job_id)
        return json_response({"deleted": deleted}, 200 if deleted else 404)


class UploadedFile:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self.content = content


def parse_multipart(scope: Dict[str, Any], body: bytes) -> Dict[str, object]:
    headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope.get("headers", [])}
    content_type = headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data"):
        return {}
    environ = {
        "REQUEST_METHOD": "POST",
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
    }
    form = cgi.FieldStorage(fp=BytesIO(body), environ=environ, keep_blank_values=True)
    result: Dict[str, object] = {}
    for key in form.keys():
        item = form[key]
        if isinstance(item, list):
            item = item[0]
        if item.filename:
            result[key] = UploadedFile(Path(item.filename).name, item.file.read())
        else:
            result[key] = item.value
    return result


async def read_body(receive: Callable) -> bytes:
    chunks = []
    while True:
        message = await receive()
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def json_response(data: object, status: int = 200) -> Tuple[int, Dict[str, str], bytes]:
    headers = {"Content-Type": "application/json; charset=utf-8", **SECURITY_HEADERS}
    return status, headers, json.dumps(data, ensure_ascii=False).encode("utf-8")


def file_response(path: Path) -> Tuple[int, Dict[str, str], bytes]:
    if not path.exists() or not path.is_file():
        return json_response({"error": "File not found"}, 404)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"Content-Type": content_type, **SECURITY_HEADERS}
    return 200, headers, path.read_bytes()


def encode_headers(headers: Dict[str, str]) -> Iterable[Tuple[bytes, bytes]]:
    return [(key.lower().encode("latin1"), value.encode("latin1")) for key, value in headers.items()]


app = App()
