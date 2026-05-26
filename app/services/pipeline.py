import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

from app.config import ORIGINALS_DIR, SUPPORTED_INPUT_TYPES, SUPPORTED_OUTPUT_TYPES
from app.models import DocumentBlock, TranslationJob
from app.services.export import export_job
from app.services.extraction import extract_blocks
from app.services.language import detect_blocks_language
from app.services.translation import get_translation_provider, is_provider_available, translate_blocks
from app.storage import create_job, load_blocks, save_blocks, update_job, utc_now


def create_translation_job(
    original_file_name: str,
    file_bytes: bytes,
    target_language: str,
    output_format: str,
    ai_provider: str,
    user_id: str = None,
) -> TranslationJob:
    file_type = extension_for(original_file_name)
    if file_type not in SUPPORTED_INPUT_TYPES:
        raise ValueError(f"Unsupported input type: {file_type}")
    if output_format not in SUPPORTED_OUTPUT_TYPES:
        raise ValueError(f"Unsupported output format: {output_format}")
    if not is_provider_available(ai_provider):
        raise ValueError(f"AI provider is not available: {ai_provider}")

    job_id = uuid.uuid4().hex
    safe_name = Path(original_file_name).name
    original_path = ORIGINALS_DIR / f"{job_id}-{safe_name}"
    original_path.write_bytes(file_bytes)
    now = utc_now()
    job = TranslationJob(
        id=job_id,
        originalFileName=safe_name,
        fileType=file_type,
        sourceLanguage=None,
        targetLanguage=target_language,
        outputFormat=output_format,
        aiProvider=ai_provider,
        status="queued",
        createdAt=now,
        updatedAt=now,
        originalPath=str(original_path),
        userId=user_id,
    )
    return create_job(job)


def run_translation_pipeline(job: TranslationJob) -> TranslationJob:
    try:
        update_job(job.id, status="extracting")
        blocks = extract_blocks(Path(job.originalPath), job.fileType)
        if not blocks:
            raise RuntimeError("No extractable text was found")
        save_blocks(job.id, blocks)

        update_job(job.id, status="detecting_language")
        source_language = detect_blocks_language(blocks)
        update_job(job.id, source_language=source_language, status="translating")

        provider = get_translation_provider(job.aiProvider)

        # 진행률 콜백: 25% 단위로 중간 저장해 UI 폴링에 반영
        _last_saved_pct = [-1]

        def on_progress(done: int, total: int) -> None:
            if total == 0:
                return
            pct = done * 100 // total
            if pct >= _last_saved_pct[0] + 25:
                _last_saved_pct[0] = pct - (pct % 25)
                logger.info("[pipeline] 번역 진행: %d%% (%d/%d)", pct, done, total)
                save_blocks(job.id, blocks)   # 부분 결과 저장

        translated_blocks = translate_blocks(
            blocks, source_language, job.targetLanguage, provider, on_progress
        )
        save_blocks(job.id, translated_blocks)

        warnings = qa_warnings(job, translated_blocks)
        update_job(job.id, status="preview_ready", warnings_json=json.dumps(warnings, ensure_ascii=False))
        return update_job(job.id, status="verified")
    except Exception as exc:
        logger.exception("[pipeline] 번역 실패 job=%s provider=%s: %s", job.id, job.aiProvider, exc)
        return update_job(job.id, status="failed", error_message=str(exc))


def export_translation_job(job: TranslationJob) -> TranslationJob:
    try:
        update_job(job.id, status="exporting")
        blocks = load_blocks(job.id)
        out_path = export_job(job, blocks)
        return update_job(job.id, status="completed", completed_at=utc_now(), exported_path=str(out_path))
    except Exception as exc:
        return update_job(job.id, status="failed", error_message=str(exc))


def extension_for(file_name: str) -> str:
    return Path(file_name).suffix.lower().lstrip(".")


def qa_warnings(job: TranslationJob, blocks: List[DocumentBlock]) -> List[str]:
    warnings = []
    missing = [block.id for block in blocks if block.sourceText.strip() and not (block.translatedText or "").strip()]
    if missing:
        warnings.append(f"{len(missing)} blocks have no translated text.")
    if job.fileType == "pdf":
        warnings.append(
            "PDF layout preservation uses text bounding boxes. Image-embedded labels require OCR and may need review."
        )
    return warnings


def copy_sample_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
