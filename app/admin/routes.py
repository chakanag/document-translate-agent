import json
import os
from pathlib import Path
from typing import Any, Dict, Tuple

from app.config import STORAGE_DIR
from app.storage import delete_job, delete_user, get_stats, get_user_by_id, list_jobs, list_users, update_user, utc_now


def _json(data: object, status: int = 200) -> Tuple[int, Dict[str, str], bytes]:
    return status, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(data, ensure_ascii=False).encode()


class AdminRouter:
    def handle(self, scope: Dict[str, Any], body: bytes) -> Tuple[int, Dict[str, str], bytes]:
        user = scope.get("user")
        if not user:
            return _json({"error": "Unauthorized"}, 401)
        if user.role != "admin":
            return _json({"error": "관리자 권한이 필요합니다"}, 403)

        method = scope["method"]
        path = scope["path"]
        try:
            if method == "GET" and path == "/api/admin/users":
                return self.list_users()
            if method == "PATCH" and path.startswith("/api/admin/users/"):
                user_id = path.split("/")[4]
                return self.update_user(user_id, body, current_user=user)
            if method == "DELETE" and path.startswith("/api/admin/users/"):
                user_id = path.split("/")[4]
                return self.delete_user(user_id, current_user=user)
            if method == "GET" and path == "/api/admin/jobs":
                return self.list_all_jobs()
            if method == "DELETE" and path.startswith("/api/admin/jobs/"):
                job_id = path.split("/")[4]
                return self.delete_job(job_id)
            if method == "GET" and path == "/api/admin/stats":
                return self.stats()
            return _json({"error": "Not found"}, 404)
        except Exception as exc:
            return _json({"error": str(exc)}, 500)

    def list_users(self) -> Tuple[int, Dict[str, str], bytes]:
        users = list_users()
        return _json({"users": [u.to_dict() for u in users]})

    def update_user(self, user_id: str, body: bytes, current_user) -> Tuple[int, Dict[str, str], bytes]:
        target = get_user_by_id(user_id)
        if not target:
            return _json({"error": "사용자를 찾을 수 없습니다"}, 404)

        data = json.loads(body or b"{}")
        changes: Dict[str, Any] = {}
        if "role" in data:
            role = data["role"]
            if role not in ("user", "admin"):
                return _json({"error": "role은 'user' 또는 'admin'이어야 합니다"}, 400)
            # 마지막 admin의 role을 user로 내릴 수 없음
            if role == "user" and target.role == "admin":
                from app.storage import list_users as _lu
                admin_count = sum(1 for u in _lu() if u.role == "admin")
                if admin_count <= 1:
                    return _json({"error": "마지막 admin은 역할을 변경할 수 없습니다"}, 400)
            changes["role"] = role
        if "isActive" in data:
            changes["is_active"] = 1 if data["isActive"] else 0

        if changes:
            update_user(user_id, **changes)
        updated = get_user_by_id(user_id)
        return _json({"user": updated.to_dict() if updated else {}})

    def delete_user(self, user_id: str, current_user) -> Tuple[int, Dict[str, str], bytes]:
        if user_id == current_user.id:
            return _json({"error": "자기 자신은 삭제할 수 없습니다"}, 400)
        deleted = delete_user(user_id)
        return _json({"deleted": deleted}, 200 if deleted else 404)

    def list_all_jobs(self) -> Tuple[int, Dict[str, str], bytes]:
        jobs = list_jobs(user_id=None)
        return _json({"jobs": [j.to_dict() for j in jobs]})

    def delete_job(self, job_id: str) -> Tuple[int, Dict[str, str], bytes]:
        deleted = delete_job(job_id)
        return _json({"deleted": deleted}, 200 if deleted else 404)

    def stats(self) -> Tuple[int, Dict[str, str], bytes]:
        data = get_stats()
        # 스토리지 용량 계산
        total_bytes = sum(
            f.stat().st_size for f in Path(STORAGE_DIR).rglob("*") if f.is_file()
        )
        data["storageUsedMb"] = round(total_bytes / (1024 * 1024), 2)
        return _json(data)
