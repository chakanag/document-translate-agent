import re
from typing import Iterable

from app.models import DocumentBlock


JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
KOREAN_RE = re.compile(r"[\uac00-\ud7af]")
LATIN_RE = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str:
    if KOREAN_RE.search(text):
        return "ko"
    if JAPANESE_RE.search(text):
        return "ja"
    if LATIN_RE.search(text):
        return "en"
    return "unknown"


def detect_blocks_language(blocks: Iterable[DocumentBlock]) -> str:
    sample = "\n".join(block.sourceText for block in blocks if block.sourceText.strip())[:5000]
    return detect_language(sample)
