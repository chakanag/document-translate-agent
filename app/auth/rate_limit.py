import threading
import time
from collections import defaultdict, deque
from typing import Dict, Deque


_lock = threading.Lock()
_windows: Dict[str, Deque[float]] = defaultdict(deque)

# 엔드포인트별 (최대 요청 수, 윈도우 초)
LIMITS = {
    "register": (5,  60),   # IP당 분당 5회
    "login":    (10, 60),   # IP당 분당 10회
    "upload":   (10, 60),   # IP당 분당 10회 (문서 업로드)
    "export":   (20, 60),   # IP당 분당 20회 (내보내기)
    "api":      (120, 60),  # IP당 분당 120회 (일반 API fallback)
}


def check(key: str, endpoint: str) -> bool:
    """True = 허용, False = 초과 (429 반환해야 함)"""
    max_requests, window_seconds = LIMITS.get(endpoint, (120, 60))
    bucket_key = f"{endpoint}:{key}"
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        q = _windows[bucket_key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= max_requests:
            return False
        q.append(now)
        return True
