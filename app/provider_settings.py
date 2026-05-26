import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import BASE_DIR


PROVIDER_CONFIG_PATH = BASE_DIR / "config" / "providers.local.json"


def provider_settings() -> Dict[str, Any]:
    """providers.local.json 을 매번 읽어서 반환 (lru_cache 없음 — 서버 재시작 불필요)."""
    if not PROVIDER_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(PROVIDER_CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def provider_value(provider: str, key: str, default: Optional[Any] = None) -> Optional[Any]:
    value = provider_settings().get(provider, {}).get(key)
    if value in ("", None):
        return default
    return value


def provider_secret(provider: str, key: str, env_name: str) -> str:
    value = provider_value(provider, key)
    if value:
        return str(value)
    return os.environ.get(env_name, "")


def provider_model(provider: str, key: str, env_name: str, default: str) -> str:
    value = provider_value(provider, key)
    if value:
        return str(value)
    return os.environ.get(env_name, default)
