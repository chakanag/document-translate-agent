import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import webauthn
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from app.auth import rate_limit
from app.auth.webauthn_helpers import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication,
    verify_registration,
)
from app.config import CHALLENGE_TTL_SECONDS, SESSION_DURATION_DAYS
from app.models import Session, User
from app.storage import (
    count_users,
    create_challenge,
    create_credential,
    create_session,
    create_user,
    delete_challenge,
    delete_session,
    get_challenge,
    get_credential_by_id,
    get_credentials_by_user,
    get_session,
    get_user_by_id,
    get_user_by_username,
    update_credential_sign_count,
    utc_now,
)


def _utc_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _utc_after_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _json(data: object, status: int = 200) -> Tuple[int, Dict[str, str], bytes]:
    return status, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(data, ensure_ascii=False).encode()


def _get_ip(scope: Dict[str, Any]) -> str:
    headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


def _parse_cookie(cookie_str: str) -> Dict[str, str]:
    result = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip()] = v.strip()
    return result


def _session_cookie(session_id: str, secure: bool = False) -> str:
    flags = "HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000"
    if secure:
        flags += "; Secure"
    return f"session_id={session_id}; {flags}"


def _clear_cookie() -> str:
    return "session_id=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"


def _validate_username(username: str) -> Optional[str]:
    if not username or not isinstance(username, str):
        return "username은 필수입니다"
    username = username.strip()
    if len(username) < 2 or len(username) > 32:
        return "username은 2~32자여야 합니다"
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if not all(c in allowed for c in username):
        return "username은 영문/숫자/_/- 만 사용 가능합니다"
    return None


class AuthRouter:
    def handle(self, scope: Dict[str, Any], body: bytes) -> Tuple[int, Dict[str, str], bytes]:
        method = scope["method"]
        path = scope["path"]
        try:
            if method == "POST" and path == "/api/auth/register/begin":
                return self.register_begin(scope, body)
            if method == "POST" and path == "/api/auth/register/complete":
                return self.register_complete(scope, body)
            if method == "POST" and path == "/api/auth/login/begin":
                return self.login_begin(scope, body)
            if method == "POST" and path == "/api/auth/login/complete":
                return self.login_complete(scope, body)
            if method == "POST" and path == "/api/auth/logout":
                return self.logout(scope)
            if method == "GET" and path == "/api/auth/me":
                return self.me(scope)
            return _json({"error": "Not found"}, 404)
        except Exception as exc:
            return _json({"error": str(exc)}, 500)

    def register_begin(self, scope: Dict[str, Any], body: bytes) -> Tuple[int, Dict[str, str], bytes]:
        ip = _get_ip(scope)
        if not rate_limit.check(ip, "register"):
            return _json({"error": "요청이 너무 많습니다. 잠시 후 다시 시도하세요."}, 429)

        data = json.loads(body or b"{}")
        username = (data.get("username") or "").strip()
        err = _validate_username(username)
        if err:
            return _json({"error": err}, 400)

        if get_user_by_username(username):
            return _json({"error": "이미 사용 중인 username입니다"}, 409)

        user_id = str(uuid.uuid4())
        existing_creds = get_credentials_by_user(user_id)
        existing_ids = [base64url_to_bytes(c["id"]) for c in existing_creds]

        options = generate_registration_options(user_id, username, existing_ids)
        challenge_b64 = bytes_to_base64url(options.challenge)

        create_challenge(
            challenge=challenge_b64,
            user_id=user_id,
            username=username,
            challenge_type="registration",
            expires_at=_utc_after(CHALLENGE_TTL_SECONDS),
        )

        options_dict = json.loads(webauthn.options_to_json(options))
        options_dict["_userId"] = user_id
        return _json(options_dict)

    def register_complete(self, scope: Dict[str, Any], body: bytes) -> Tuple[int, Dict[str, str], bytes]:
        data = json.loads(body or b"{}")
        username = (data.get("username") or "").strip()
        credential = data.get("credential")
        if not username or not credential:
            return _json({"error": "username과 credential이 필요합니다"}, 400)

        # challenge 조회 (username 기반)
        raw_challenge = data.get("challenge")
        if not raw_challenge:
            return _json({"error": "challenge가 없습니다"}, 400)
        stored = get_challenge(raw_challenge)
        if not stored:
            return _json({"error": "challenge가 만료되었거나 유효하지 않습니다"}, 400)
        if stored["expires_at"] < utc_now():
            delete_challenge(raw_challenge)
            return _json({"error": "challenge가 만료되었습니다"}, 400)
        if stored["type"] != "registration":
            return _json({"error": "잘못된 challenge 타입입니다"}, 400)
        delete_challenge(raw_challenge)

        user_id = stored["user_id"]
        stored_username = stored["username"]

        if get_user_by_username(stored_username):
            return _json({"error": "이미 등록된 사용자입니다"}, 409)

        try:
            challenge_bytes = base64url_to_bytes(raw_challenge)
            verification = verify_registration(challenge_bytes, credential)
        except Exception as exc:
            return _json({"error": f"패스키 검증 실패: {exc}"}, 400)

        # 첫 번째 유저이면 admin (즉시 활성), 이후 유저는 승인 대기
        role = "admin" if count_users() == 0 else "user"
        is_active = role == "admin"
        email = (data.get("email") or "").strip() or None

        now = utc_now()
        user = User(
            id=user_id,
            username=stored_username,
            email=email,
            role=role,
            isActive=is_active,
            createdAt=now,
            updatedAt=now,
        )
        create_user(user)

        cred_id = bytes_to_base64url(verification.credential_id)
        create_credential(
            credential_id=cred_id,
            user_id=user_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            device_name=data.get("deviceName") or None,
        )

        # 승인 대기 유저: 세션 발급 없이 대기 안내
        if not is_active:
            return _json({
                "pending": True,
                "message": "가입이 완료되었습니다. 관리자 승인 후 로그인하실 수 있습니다.",
            }, 202)

        session = _issue_session(user_id)
        status, headers, payload = _json({"user": user.to_dict()})
        headers["Set-Cookie"] = _session_cookie(session.id, secure=_is_https(scope))
        return status, headers, payload

    def login_begin(self, scope: Dict[str, Any], body: bytes) -> Tuple[int, Dict[str, str], bytes]:
        ip = _get_ip(scope)
        if not rate_limit.check(ip, "login"):
            return _json({"error": "요청이 너무 많습니다. 잠시 후 다시 시도하세요."}, 429)

        data = json.loads(body or b"{}")
        username = (data.get("username") or "").strip()
        err = _validate_username(username)
        if err:
            return _json({"error": err}, 400)

        user = get_user_by_username(username)
        if not user:
            # 타이밍 공격 방지: 존재하지 않아도 동일 오류
            return _json({"error": "등록되지 않은 사용자이거나 패스키가 없습니다"}, 404)
        if not user.isActive:
            return _json({"error": "승인 대기 중인 계정입니다. 관리자에게 문의하세요.", "pending": True}, 403)

        creds = get_credentials_by_user(user.id)
        if not creds:
            return _json({"error": "등록된 패스키가 없습니다"}, 404)

        credential_ids = [base64url_to_bytes(c["id"]) for c in creds]
        options = generate_authentication_options(credential_ids)
        challenge_b64 = bytes_to_base64url(options.challenge)

        create_challenge(
            challenge=challenge_b64,
            user_id=user.id,
            username=username,
            challenge_type="authentication",
            expires_at=_utc_after(CHALLENGE_TTL_SECONDS),
        )

        return _json(json.loads(webauthn.options_to_json(options)))

    def login_complete(self, scope: Dict[str, Any], body: bytes) -> Tuple[int, Dict[str, str], bytes]:
        data = json.loads(body or b"{}")
        credential = data.get("credential")
        raw_challenge = data.get("challenge")
        if not credential or not raw_challenge:
            return _json({"error": "credential과 challenge가 필요합니다"}, 400)

        stored = get_challenge(raw_challenge)
        if not stored:
            return _json({"error": "challenge가 만료되었거나 유효하지 않습니다"}, 400)
        if stored["expires_at"] < utc_now():
            delete_challenge(raw_challenge)
            return _json({"error": "challenge가 만료되었습니다"}, 400)
        if stored["type"] != "authentication":
            return _json({"error": "잘못된 challenge 타입입니다"}, 400)
        delete_challenge(raw_challenge)

        user = get_user_by_id(stored["user_id"])
        if not user or not user.isActive:
            return _json({"error": "사용자를 찾을 수 없습니다"}, 404)

        # credential ID로 저장된 키 조회
        cred_id_b64 = credential.get("id") or credential.get("rawId")
        stored_cred = get_credential_by_id(cred_id_b64)
        if not stored_cred or stored_cred["user_id"] != user.id:
            return _json({"error": "패스키를 찾을 수 없습니다"}, 400)

        try:
            challenge_bytes = base64url_to_bytes(raw_challenge)
            verification = verify_authentication(
                challenge_bytes=challenge_bytes,
                credential_response=credential,
                public_key=stored_cred["public_key"],
                current_sign_count=stored_cred["sign_count"],
            )
        except Exception as exc:
            return _json({"error": f"패스키 검증 실패: {exc}"}, 400)

        update_credential_sign_count(cred_id_b64, verification.new_sign_count)

        session = _issue_session(user.id)
        status, headers, payload = _json({"user": user.to_dict()})
        headers["Set-Cookie"] = _session_cookie(session.id, secure=_is_https(scope))
        return status, headers, payload

    def logout(self, scope: Dict[str, Any]) -> Tuple[int, Dict[str, str], bytes]:
        headers_raw = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        cookie = _parse_cookie(headers_raw.get("cookie", ""))
        session_id = cookie.get("session_id", "")
        if session_id:
            delete_session(session_id)
        status, headers, payload = _json({"ok": True})
        headers["Set-Cookie"] = _clear_cookie()
        return status, headers, payload

    def me(self, scope: Dict[str, Any]) -> Tuple[int, Dict[str, str], bytes]:
        user = scope.get("user")
        if not user:
            return _json({"error": "Unauthorized"}, 401)
        return _json({"user": user.to_dict()})


def _issue_session(user_id: str) -> Session:
    session = Session(
        id=secrets.token_urlsafe(32),
        userId=user_id,
        createdAt=utc_now(),
        expiresAt=_utc_after_days(SESSION_DURATION_DAYS),
    )
    return create_session(session)


def _is_https(scope: Dict[str, Any]) -> bool:
    headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
    return headers.get("x-forwarded-proto", "") == "https"
