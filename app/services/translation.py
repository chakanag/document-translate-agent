import concurrent.futures
import json
import logging
import os
import re
import threading
import urllib.error
import urllib.request
from typing import Callable, Dict, Iterable, List, Optional

from app.models import DocumentBlock
from app.provider_settings import provider_model, provider_secret, provider_value

logger = logging.getLogger(__name__)

# ── 배치 / 병렬 처리 설정 ─────────────────────────────────────────────
CLOUD_BATCH_SIZE      = 15      # 클라우드 LLM: 한 번에 묶을 최대 블록 수
CLOUD_BATCH_MAX_CHARS = 3_000   # 클라우드 LLM: 한 배치의 최대 소스 문자 수
CLOUD_MAX_WORKERS     = 4       # 동시 API 호출 스레드 수

DEEPL_BATCH_SIZE      = 50      # DeepL: 배열 네이티브 지원, 최대 50개
DEEPL_BATCH_MAX_CHARS = 30_000  # DeepL: 배치당 최대 문자 수
DEEPL_MAX_WORKERS     = 4

PAPAGO_BATCH_SIZE      = 1      # Papago: 요청당 하나의 텍스트 (분리자 불안정)
PAPAGO_BATCH_MAX_CHARS = 5_000  # Papago: 요청당 최대 5000자
PAPAGO_MAX_WORKERS     = 8      # 빠른 응답 속도 → 병렬 다수 허용

OLLAMA_BATCH_SIZE      = 8
OLLAMA_BATCH_MAX_CHARS = 3_000


# ── 공통 유틸 ─────────────────────────────────────────────────────────

def _numbered_prompt(texts: List[str]) -> str:
    """[N] 마커 형식의 배치 입력 문자열 생성."""
    return "\n\n".join(f"[{i + 1}]\n{t}" for i, t in enumerate(texts))


def _parse_numbered_blocks(raw: str) -> Dict[int, str]:
    """[N] 마커 형식의 응답을 파싱해 {1-indexed: translated_text} dict 반환."""
    parts = re.split(r"\[(\d+)\]", raw)
    result: Dict[int, str] = {}
    for idx in range(1, len(parts), 2):
        try:
            num  = int(parts[idx])
            text = parts[idx + 1].strip() if idx + 1 < len(parts) else ""
            result[num] = text
        except (ValueError, IndexError):
            continue
    return result


def _build_batches(
    texts: List[str],
    batch_size: int,
    batch_max_chars: int,
) -> List[List[int]]:
    """texts 인덱스를 배치 단위(인덱스 리스트)로 묶어 반환."""
    batches: List[List[int]] = []
    current: List[int] = []
    current_chars = 0
    for i, text in enumerate(texts):
        if current and (
            len(current) >= batch_size
            or current_chars + len(text) > batch_max_chars
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(i)
        current_chars += len(text)
    if current:
        batches.append(current)
    return batches


# ── Provider 베이스 ────────────────────────────────────────────────────

class TranslationProvider:
    def translate(self, text: str, source_language: str, target_language: str) -> str:
        raise NotImplementedError

    def translate_batch(
        self,
        texts: List[str],
        source_language: str,
        target_language: str,
    ) -> List[str]:
        """여러 텍스트를 번역. 서브클래스에서 오버라이드하면 배치 최적화 가능."""
        return [self.translate(t, source_language, target_language) for t in texts]

    def batch_config(self) -> tuple:
        """(batch_size, batch_max_chars, max_workers) 반환. 서브클래스에서 조정."""
        return CLOUD_BATCH_SIZE, CLOUD_BATCH_MAX_CHARS, CLOUD_MAX_WORKERS


# ── Demo ──────────────────────────────────────────────────────────────

class DemoTranslationProvider(TranslationProvider):
    def translate(self, text: str, source_language: str, target_language: str) -> str:
        if not text.strip():
            return text
        return f"[{target_language}] {text}"

    def batch_config(self) -> tuple:
        return 50, 10_000, 1


# ── OpenAI ────────────────────────────────────────────────────────────

class OpenAITranslationProvider(TranslationProvider):
    def __init__(self) -> None:
        self.api_key = provider_secret("openai", "api_key", "OPENAI_API_KEY")
        self.model   = provider_model("openai", "model", "OPENAI_TRANSLATION_MODEL", "gpt-4o-mini")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

    def _call(self, system: str, user: str, max_tokens: int = 4096) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"].strip()

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        system = (
            "You are a professional document translator. Preserve numbers, "
            "placeholders, line breaks, table cell meaning, and proper nouns. "
            "Return only the translated text."
        )
        return self._call(system, f"Translate from {source_language} to {target_language}.\n\n{text}")

    def translate_batch(self, texts: List[str], source_language: str, target_language: str) -> List[str]:
        if len(texts) == 1:
            return [self.translate(texts[0], source_language, target_language)]
        system = (
            "You are a professional document translator. Preserve numbers, placeholders, "
            "line breaks, table cell meaning, and proper nouns."
        )
        user = (
            f"Translate each numbered block from {source_language} to {target_language}. "
            "Keep the [N] markers exactly as-is. Output ONLY the translated blocks with their markers.\n\n"
            + _numbered_prompt(texts)
        )
        raw = self._call(system, user, max_tokens=8192)
        result_map = _parse_numbered_blocks(raw)
        results = []
        for i, text in enumerate(texts):
            translated = result_map.get(i + 1)
            if translated is None:
                try:
                    translated = self.translate(text, source_language, target_language)
                except Exception:
                    translated = text
            results.append(translated)
        return results


# ── Gemini ────────────────────────────────────────────────────────────

class GeminiTranslationProvider(TranslationProvider):
    def __init__(self) -> None:
        self.api_key = (
            provider_secret("gemini", "api_key", "GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY", "")
        )
        self.model = provider_model("gemini", "model", "GEMINI_TRANSLATION_MODEL", "gemini-1.5-flash")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is not set")

    def _call(self, prompt: str) -> str:
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1},
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["candidates"][0]["content"]["parts"][0]["text"].strip()

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        prompt = (
            "You are a professional document translator. Preserve numbers, "
            "placeholders, line breaks, table cell meaning, and proper nouns. "
            f"Translate from {source_language} to {target_language}. "
            f"Return only the translated text.\n\n{text}"
        )
        return self._call(prompt)

    def translate_batch(self, texts: List[str], source_language: str, target_language: str) -> List[str]:
        if len(texts) == 1:
            return [self.translate(texts[0], source_language, target_language)]
        prompt = (
            "You are a professional document translator. Preserve numbers, placeholders, "
            "line breaks, table cell meaning, and proper nouns.\n\n"
            f"Translate each numbered block from {source_language} to {target_language}. "
            "Keep the [N] markers exactly as-is. Output ONLY the translated blocks with their markers.\n\n"
            + _numbered_prompt(texts)
        )
        raw = self._call(prompt)
        result_map = _parse_numbered_blocks(raw)
        results = []
        for i, text in enumerate(texts):
            translated = result_map.get(i + 1)
            if translated is None:
                try:
                    translated = self.translate(text, source_language, target_language)
                except Exception:
                    translated = text
            results.append(translated)
        return results


# ── Anthropic ─────────────────────────────────────────────────────────


class AnthropicTranslationProvider(TranslationProvider):
    def __init__(self) -> None:
        self.api_key = provider_secret("anthropic", "api_key", "ANTHROPIC_API_KEY")
        self.model   = provider_model("anthropic", "model", "ANTHROPIC_TRANSLATION_MODEL", "claude-haiku-4-5-20251001")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

    def _call(self, system: str, user_content: str, max_tokens: int = 4096) -> str:
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0.1,
            "system": system,
            "messages": [{"role": "user", "content": user_content}],
        }
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                err_data = json.loads(exc.read().decode("utf-8"))
                err_msg  = err_data.get("error", {}).get("message") or str(exc)
            except Exception:
                err_msg = str(exc)
            raise RuntimeError(
                f"Anthropic API 오류 (HTTP {exc.code}) — 모델: {self.model} | {err_msg}"
            ) from exc
        return "".join(
            part.get("text", "")
            for part in payload.get("content", [])
            if part.get("type") == "text"
        ).strip()

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        system = (
            "You are a professional document translator. Preserve numbers, placeholders, "
            "line breaks, table cell meaning, and proper nouns. Return only the translated text."
        )
        return self._call(system, f"Translate from {source_language} to {target_language}.\n\n{text}")

    def translate_batch(self, texts: List[str], source_language: str, target_language: str) -> List[str]:
        if len(texts) == 1:
            return [self.translate(texts[0], source_language, target_language)]
        system = (
            "You are a professional document translator. Preserve numbers, placeholders, "
            "line breaks, table cell meaning, and proper nouns."
        )
        user = (
            f"Translate each numbered block from {source_language} to {target_language}. "
            "Keep the [N] markers exactly as-is. Output ONLY the translated blocks with their markers.\n\n"
            + _numbered_prompt(texts)
        )
        raw = self._call(system, user, max_tokens=8192)
        result_map = _parse_numbered_blocks(raw)
        results = []
        for i, text in enumerate(texts):
            translated = result_map.get(i + 1)
            if translated is None:
                try:
                    translated = self.translate(text, source_language, target_language)
                except Exception:
                    translated = text
            results.append(translated)
        return results


# ── Ollama ────────────────────────────────────────────────────────────

class OllamaTranslationProvider(TranslationProvider):
    def batch_config(self) -> tuple:
        return OLLAMA_BATCH_SIZE, OLLAMA_BATCH_MAX_CHARS, 1  # Ollama는 단일 스레드

    def __init__(self) -> None:
        self.base_url = ollama_base_url()
        self.model    = configured_ollama_model() or first_ollama_model()
        self.timeout  = ollama_generate_timeout() or 300
        if not self.model:
            raise RuntimeError("No Ollama model is available")

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        body = {
            "model": self.model,
            "stream": False,
            "prompt": (
                "You are a professional document translator. Preserve numbers, placeholders, "
                "line breaks, table cell meaning, and proper nouns. Return only the translated text.\n\n"
                f"Translate from {source_language} to {target_language}.\n\n{text}"
            ),
            "options": {"temperature": 0.1},
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("response", "").strip()

    def translate_batch(
        self,
        texts: List[str],
        source_language: str,
        target_language: str,
    ) -> List[str]:
        if len(texts) == 1:
            return [self.translate(texts[0], source_language, target_language)]
        numbered = _numbered_prompt(texts)
        prompt = (
            "You are a professional document translator. Preserve numbers, placeholders, "
            "line breaks, table cell meaning, and proper nouns.\n\n"
            f"Translate each numbered block from {source_language} to {target_language}. "
            "Keep the [N] markers exactly as-is. Output ONLY the translated blocks with their markers.\n\n"
            + numbered
        )
        body = {
            "model": self.model,
            "stream": False,
            "prompt": prompt,
            "options": {"temperature": 0.1},
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            raw = json.loads(response.read().decode("utf-8")).get("response", "").strip()
        result_map = _parse_numbered_blocks(raw)
        results = []
        for i, text in enumerate(texts):
            translated = result_map.get(i + 1)
            if translated is None:
                try:
                    translated = self.translate(text, source_language, target_language)
                except Exception:
                    translated = text
            results.append(translated)
        return results


# ── DeepL ─────────────────────────────────────────────────────────────

class DeepLTranslationProvider(TranslationProvider):
    """DeepL Translation API — 배열 네이티브 배치 지원, 토큰 과금 없음."""

    # DeepL 언어 코드 매핑 (ISO 639-1 → DeepL 코드)
    _LANG = {
        "ko": "KO", "en": "EN-US", "ja": "JA",
        "zh": "ZH", "fr": "FR",    "de": "DE",
        "es": "ES", "vi": "VI",    "pt": "PT-PT",
        "it": "IT", "nl": "NL",    "ru": "RU",
    }

    def __init__(self) -> None:
        self.api_key  = provider_secret("deepl", "api_key", "DEEPL_API_KEY")
        # 무료 키는 api-free.deepl.com, 유료 키는 api.deepl.com
        self.base_url = str(
            provider_value("deepl", "base_url", "") or
            os.environ.get("DEEPL_BASE_URL", "https://api-free.deepl.com")
        ).rstrip("/")
        if not self.api_key:
            raise RuntimeError("DEEPL_API_KEY is not set")

    def batch_config(self) -> tuple:
        return DEEPL_BATCH_SIZE, DEEPL_BATCH_MAX_CHARS, DEEPL_MAX_WORKERS

    def _lc(self, lang: str) -> str:
        return self._LANG.get(lang.lower(), lang.upper())

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        return self.translate_batch([text], source_language, target_language)[0]

    def translate_batch(
        self, texts: List[str], source_language: str, target_language: str
    ) -> List[str]:
        body = json.dumps({
            "text":        texts,
            "source_lang": self._lc(source_language),
            "target_lang": self._lc(target_language),
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v2/translate",
            data=body,
            headers={
                "Authorization": f"DeepL-Auth-Key {self.api_key}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return [t["text"] for t in payload["translations"]]
        except urllib.error.HTTPError as exc:
            try:
                err = json.loads(exc.read().decode("utf-8"))
                msg = err.get("message", str(exc))
            except Exception:
                msg = str(exc)
            raise RuntimeError(f"DeepL API 오류 (HTTP {exc.code}): {msg}") from exc


# ── Papago (Naver Cloud NMT) ──────────────────────────────────────────

class PapagoTranslationProvider(TranslationProvider):
    """Naver Cloud Platform NMT API — 한·일·영 번역 품질 최상."""

    _LANG = {
        "ko": "ko", "en": "en", "ja": "ja",
        "zh": "zh-CN", "fr": "fr", "de": "de",
        "es": "es",   "vi": "vi", "th": "th",
        "id": "id",
    }

    def __init__(self) -> None:
        self.client_id     = provider_secret("papago", "client_id",     "PAPAGO_CLIENT_ID")
        self.client_secret = provider_secret("papago", "client_secret", "PAPAGO_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "PAPAGO_CLIENT_ID / PAPAGO_CLIENT_SECRET가 설정되지 않았습니다. "
                "config/providers.local.json 또는 환경 변수를 확인하세요."
            )

    def batch_config(self) -> tuple:
        # 단건 호출, 병렬 다수 허용 (응답 빠름)
        return PAPAGO_BATCH_SIZE, PAPAGO_BATCH_MAX_CHARS, PAPAGO_MAX_WORKERS

    def _lc(self, lang: str) -> str:
        return self._LANG.get(lang.lower(), lang.lower())

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        body = json.dumps({
            "source": self._lc(source_language),
            "target": self._lc(target_language),
            "text":   text,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://naveropenapi.apigw.ntruss.com/nmt/v1/translation",
            data=body,
            headers={
                "X-NCP-APIGW-API-KEY-ID": self.client_id,
                "X-NCP-APIGW-API-KEY":    self.client_secret,
                "Content-Type":           "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload["message"]["result"]["translatedText"]
        except urllib.error.HTTPError as exc:
            try:
                err = json.loads(exc.read().decode("utf-8"))
                msg = err.get("errorMessage", str(exc))
            except Exception:
                msg = str(exc)
            raise RuntimeError(f"Papago API 오류 (HTTP {exc.code}): {msg}") from exc


# ── 핵심: translate_blocks ────────────────────────────────────────────

def translate_blocks(
    blocks: Iterable[DocumentBlock],
    source_language: str,
    target_language: str,
    provider: TranslationProvider,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[DocumentBlock]:
    block_list = list(blocks)

    # 1) 번역이 필요한 블록만 추림
    non_empty_indices = [
        i for i, b in enumerate(block_list) if b.sourceText.strip()
    ]
    if not non_empty_indices:
        return block_list

    # 2) 중복 제거 — 동일 텍스트는 1회만 번역 (표 헤더, 공통 라벨 등)
    all_texts    = [block_list[i].sourceText for i in non_empty_indices]
    unique_texts = list(dict.fromkeys(all_texts))   # 순서 유지
    text_to_idx  = {text: pos for pos, text in enumerate(unique_texts)}

    total_unique = len(unique_texts)
    logger.info(
        "[translate_blocks] blocks=%d, non_empty=%d, unique=%d, provider=%s",
        len(block_list), len(non_empty_indices), total_unique, type(provider).__name__,
    )

    # 3) 배치 크기 결정 (provider별 batch_config()에 위임)
    batch_size, batch_max_chars, max_workers = provider.batch_config()

    batches = _build_batches(unique_texts, batch_size, batch_max_chars)
    logger.info(
        "[translate_blocks] %d unique texts → %d batches (size≤%d, chars≤%d, workers=%d)",
        total_unique, len(batches), batch_size, batch_max_chars, max_workers,
    )

    # 4) 번역 결과 저장소
    translated_unique: List[Optional[str]] = [None] * total_unique
    done_count = [0]
    lock = threading.Lock()

    def translate_one_batch(idx_list: List[int]) -> None:
        texts_in_batch = [unique_texts[i] for i in idx_list]
        try:
            results = provider.translate_batch(texts_in_batch, source_language, target_language)
        except Exception as exc:
            logger.warning("[translate_blocks] 배치 번역 실패, 개별 fallback: %s", exc)
            results = []
            for t in texts_in_batch:
                try:
                    results.append(provider.translate(t, source_language, target_language))
                except Exception as e2:
                    logger.warning("[translate_blocks] 개별 번역도 실패, 원문 유지: %s", e2)
                    results.append(t)
        with lock:
            for i, result in zip(idx_list, results):
                translated_unique[i] = result
            done_count[0] += len(idx_list)
            if progress_callback:
                progress_callback(done_count[0], total_unique)

    # 5) 병렬 실행 (Ollama·Demo는 단일 스레드)
    if max_workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(translate_one_batch, batch) for batch in batches]
            for fut in concurrent.futures.as_completed(futures):
                fut.result()   # 예외가 있으면 여기서 raise
    else:
        for batch in batches:
            translate_one_batch(batch)

    # 6) 결과를 블록에 적용
    for i in non_empty_indices:
        text = block_list[i].sourceText
        pos  = text_to_idx[text]
        block_list[i].translatedText = translated_unique[pos] or text

    return block_list


# ── Provider 조회 ─────────────────────────────────────────────────────

def provider_catalog() -> List[Dict[str, object]]:
    ollama_models    = ollama_model_names()
    ollama_model     = configured_ollama_model() or (ollama_models[0] if ollama_models else "")
    ollama_available = bool(ollama_model)
    openai_key       = provider_secret("openai",    "api_key",       "OPENAI_API_KEY")
    gemini_key       = provider_secret("gemini",    "api_key",       "GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    anthropic_key    = provider_secret("anthropic", "api_key",       "ANTHROPIC_API_KEY")
    deepl_key        = provider_secret("deepl",     "api_key",       "DEEPL_API_KEY")
    papago_id        = provider_secret("papago",    "client_id",     "PAPAGO_CLIENT_ID")
    papago_secret    = provider_secret("papago",    "client_secret", "PAPAGO_CLIENT_SECRET")
    papago_available = bool(papago_id and papago_secret)
    return [
        {
            "id": "deepl", "label": "DeepL",
            "available": bool(deepl_key),
            "reason": "DeepL API key 등록됨 — 번역 전용 API, 빠르고 저렴" if deepl_key
                      else "config/providers.local.json에 DeepL API key가 필요합니다 (무료 500K자/월)",
            "requiresKey": True,
        },
        {
            "id": "papago", "label": "Papago (Naver)",
            "available": papago_available,
            "reason": "Papago API 등록됨 — 한·일·영 번역 최강" if papago_available
                      else "config/providers.local.json에 Papago client_id / client_secret가 필요합니다",
            "requiresKey": True,
        },
        {
            "id": "openai", "label": "OpenAI",
            "available": bool(openai_key),
            "reason": "OpenAI API key 등록됨" if openai_key
                      else "config/providers.local.json에 OpenAI API key가 필요합니다",
            "requiresKey": True,
        },
        {
            "id": "gemini", "label": "Gemini",
            "available": bool(gemini_key),
            "reason": "Gemini API key 등록됨" if gemini_key
                      else "config/providers.local.json에 Gemini API key가 필요합니다",
            "requiresKey": True,
        },
        {
            "id": "anthropic", "label": "Anthropic",
            "available": bool(anthropic_key),
            "reason": "Anthropic API key 등록됨" if anthropic_key
                      else "config/providers.local.json에 Anthropic API key가 필요합니다",
            "requiresKey": True,
        },
        {
            "id": "ollama", "label": "Local Ollama",
            "available": ollama_available,
            "reason": f"Ollama 모델 사용 가능: {ollama_model}" if ollama_available
                      else "Ollama 서버 또는 설치된 모델이 필요합니다",
            "requiresKey": False,
        },
        {
            "id": "demo", "label": "Demo",
            "available": True,
            "reason": "개발용 더미 번역",
            "requiresKey": False,
        },
    ]


def available_providers() -> List[Dict[str, object]]:
    return [p for p in provider_catalog() if p["available"]]


def is_provider_available(provider_name: str) -> bool:
    return any(p["id"] == provider_name and p["available"] for p in provider_catalog())


def get_translation_provider(provider_name: str = "") -> TranslationProvider:
    provider_name = (provider_name or os.environ.get("TRANSLATION_PROVIDER", "demo")).lower()
    if provider_name == "deepl":
        return DeepLTranslationProvider()
    if provider_name == "papago":
        return PapagoTranslationProvider()
    if provider_name == "openai":
        return OpenAITranslationProvider()
    if provider_name == "gemini":
        return GeminiTranslationProvider()
    if provider_name == "anthropic":
        return AnthropicTranslationProvider()
    if provider_name == "ollama":
        return OllamaTranslationProvider()
    if provider_name == "demo":
        return DemoTranslationProvider()
    raise RuntimeError(f"Unknown translation provider: {provider_name}")


# ── Ollama 헬퍼 ───────────────────────────────────────────────────────

def is_ollama_running() -> bool:
    return bool(ollama_model_names())


def ollama_generate_timeout() -> Optional[float]:
    raw = str(
        provider_value("ollama", "generate_timeout_seconds")
        or os.environ.get("OLLAMA_GENERATE_TIMEOUT_SECONDS", "")
    ).strip()
    if not raw:
        return None
    try:
        v = float(raw)
        return v if v > 0 else None
    except ValueError:
        return None


def first_ollama_model() -> str:
    models = ollama_model_names()
    return models[0] if models else ""


def ollama_model_names() -> List[str]:
    base_url = ollama_base_url()
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=1.5) as resp:
            if not 200 <= resp.status < 300:
                return []
            payload = json.loads(resp.read().decode("utf-8"))
            return [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return []


def ollama_base_url() -> str:
    return str(
        provider_value("ollama", "base_url", os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ).rstrip("/")


def configured_ollama_model() -> str:
    return str(provider_value("ollama", "model", os.environ.get("OLLAMA_TRANSLATION_MODEL", "")) or "")
