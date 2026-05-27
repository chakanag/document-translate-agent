from pathlib import Path
from typing import Iterable, List, Optional

from app.config import EXPORTS_DIR
from app.models import DocumentBlock, TranslationJob

# 한글(CJK)을 지원하는 시스템 폰트 후보 목록 (macOS → Linux → Windows 순)
_CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",          # macOS 기본 한글 폰트
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",  # macOS 구버전
    "/Library/Fonts/NanumGothic.ttf",                      # 나눔고딕 (설치 시)
    "/Library/Fonts/NanumBarunGothic.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJKkr-Regular.otf",  # Linux Noto
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",     # Linux 나눔
    "/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf",  # Linux 은폰트
    "C:/Windows/Fonts/malgun.ttf",                         # Windows 맑은 고딕
    "C:/Windows/Fonts/gulim.ttc",
]


def _find_cjk_font() -> Optional[str]:
    """시스템에서 한글을 지원하는 폰트 파일 경로를 반환. 없으면 None."""
    for p in _CJK_FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def export_job(job: TranslationJob, blocks: List[DocumentBlock]) -> Path:
    if job.outputFormat in {"txt", "md"}:
        return export_text(job, blocks, job.outputFormat)
    if job.outputFormat == "pdf":
        # Vision OCR 블록(bbox 없음)은 별도 텍스트 PDF로 출력
        has_vision = any(b.type == "pdf_vision_span" for b in blocks)
        if has_vision:
            return export_pdf_vision_ocr(job, blocks)
        return export_pdf_layout_preserving(job, blocks)
    if job.outputFormat in {"doc", "docx"}:
        return export_docx_preserving(job, blocks)
    if job.outputFormat in {"xls", "xlsx"}:
        return export_xlsx_preserving(job, blocks)
    raise ValueError(f"{job.outputFormat.upper()} 내보내기는 지원하지 않습니다")


def export_text(job: TranslationJob, blocks: Iterable[DocumentBlock], extension: str) -> Path:
    out_path = EXPORTS_DIR / f"{job.id}.{extension}"
    text = "\n\n".join((block.translatedText or "") for block in blocks)
    out_path.write_text(text, encoding="utf-8")
    return out_path


def export_pdf_layout_preserving(job: TranslationJob, blocks: List[DocumentBlock]) -> Path:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Layout-preserving PDF export requires PyMuPDF. Install dependencies with: python3 -m pip install PyMuPDF"
        ) from exc

    if not job.originalPath:
        raise RuntimeError("Original PDF path is missing")

    out_path = EXPORTS_DIR / f"{job.id}.pdf"
    doc = fitz.open(job.originalPath)

    # pdf_text_span: 벡터 텍스트 교체 / pdf_ocr_span: 이미지 위 오버레이
    pdf_blocks = [
        block for block in blocks
        if block.type in ("pdf_text_span", "pdf_ocr_span") and block.bbox
    ]

    # ── ① 벡터 텍스트(pdf_text_span)만 Redact으로 제거 ──────────────────
    # (pdf_ocr_span은 이미지 위에 있으므로 redact 불필요 — draw_rect로 처리)
    for block in pdf_blocks:
        if block.type != "pdf_text_span":
            continue
        page = doc[block.pageNumber - 1 if block.pageNumber else 0]
        rect = fitz.Rect(*block.bbox)
        page.add_redact_annot(rect, fill=(1, 1, 1))

    for page in doc:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    # ── ② 한글 폰트 준비 ─────────────────────────────────────────────────
    cjk_font_path = _find_cjk_font()
    font_registered: set = set()   # 페이지별 폰트 등록 여부 추적

    # ── ③ 번역 텍스트 삽입 ───────────────────────────────────────────────
    for block in pdf_blocks:
        page_idx = block.pageNumber - 1 if block.pageNumber else 0
        page = doc[page_idx]

        # 페이지당 한 번만 한글 폰트 등록
        if cjk_font_path and page_idx not in font_registered:
            try:
                page.insert_font(fontname="KR", fontfile=cjk_font_path)
                font_registered.add(page_idx)
            except Exception:
                pass  # 폰트 등록 실패 시 기본 폰트로 fallback

        fontname = "KR" if page_idx in font_registered else "helv"
        rect = fitz.Rect(*block.bbox)
        text = block.translatedText or ""
        font_size = max(5, min(block.fontSize or 9, 14))

        # OCR 블록: 이미지 위에 흰 사각형을 덮어 원본 텍스트 이미지를 가림
        if block.type == "pdf_ocr_span":
            page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))

        inserted = page.insert_textbox(
            rect, text, fontsize=font_size, fontname=fontname,
            color=(0, 0, 0), align=fitz.TEXT_ALIGN_LEFT,
        )
        # 공간이 부족하면 폰트 크기를 줄여서 재시도
        while inserted < 0 and font_size > 5:
            font_size -= 0.5
            inserted = page.insert_textbox(
                rect, text, fontsize=font_size, fontname=fontname,
                color=(0, 0, 0), align=fitz.TEXT_ALIGN_LEFT,
            )

    doc.save(out_path)
    doc.close()
    return out_path


def export_pdf_vision_ocr(job: TranslationJob, blocks: List[DocumentBlock]) -> Path:
    """Claude Vision OCR 블록(bbox 없음)을 번역된 텍스트 PDF로 내보내기.
    원본 PDF 페이지를 배경으로 넣고, 하단에 반투명 번역 텍스트 오버레이를 추가."""
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMuPDF가 필요합니다") from exc

    out_path = EXPORTS_DIR / f"{job.id}.pdf"
    cjk_font_path = _find_cjk_font()

    # 원본 PDF가 있으면 배경으로 사용, 없으면 빈 A4 페이지
    if job.originalPath and Path(job.originalPath).exists():
        orig_doc = fitz.open(job.originalPath)
    else:
        orig_doc = None

    out_doc = fitz.open()

    # 페이지별로 블록 그룹화
    from collections import defaultdict
    page_blocks: dict = defaultdict(list)
    for block in blocks:
        if block.type == "pdf_vision_span":
            page_blocks[block.pageNumber or 1].append(block)

    page_nums = sorted(page_blocks.keys())
    if not page_nums:
        # 블록 없으면 빈 PDF
        out_doc.new_page()
        out_doc.save(out_path)
        out_doc.close()
        return out_path

    for page_num in page_nums:
        blks = page_blocks[page_num]

        # 원본 페이지 크기 가져오기
        if orig_doc and page_num - 1 < len(orig_doc):
            orig_page = orig_doc[page_num - 1]
            w, h = orig_page.rect.width, orig_page.rect.height
        else:
            w, h = 595, 842  # A4

        new_page = out_doc.new_page(width=w, height=h)

        # ── 원본 페이지를 배경 이미지로 복사 ──────────────────────────────
        if orig_doc and page_num - 1 < len(orig_doc):
            new_page.show_pdf_page(new_page.rect, orig_doc, page_num - 1)

        # ── 번역 텍스트 오버레이 (반투명 흰 박스 + 텍스트) ──────────────
        if cjk_font_path:
            try:
                new_page.insert_font(fontname="KR", fontfile=cjk_font_path)
                fontname = "KR"
            except Exception:
                fontname = "helv"
        else:
            fontname = "helv"

        # 오버레이 영역: 페이지 우측 절반 또는 전체 하단 (텍스트 양에 따라)
        overlay_rect = fitz.Rect(w * 0.5, 20, w - 10, h - 20)
        # 반투명 흰 배경
        new_page.draw_rect(overlay_rect, color=(0.9, 0.9, 0.9), fill=(1, 1, 1), fill_opacity=0.85)

        combined_text = "\n\n".join(b.translatedText or "" for b in blks if b.translatedText)
        if combined_text:
            new_page.insert_textbox(
                overlay_rect.inflate(-8),
                combined_text,
                fontsize=9,
                fontname=fontname,
                color=(0, 0, 0),
                align=fitz.TEXT_ALIGN_LEFT,
            )

    if orig_doc:
        orig_doc.close()

    out_doc.save(out_path)
    out_doc.close()
    return out_path


def export_docx_preserving(job: TranslationJob, blocks: List[DocumentBlock]) -> Path:
    """원본 docx의 스타일/서식을 유지하면서 번역 텍스트만 교체.
    extraction.py 의 extract_docx_blocks()와 block.id 구조를 공유합니다.
    원본이 .doc 바이너리인 경우 서식 없이 새 DOCX를 생성합니다."""
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "DOCX 내보내기에는 python-docx가 필요합니다: pip install python-docx"
        ) from exc

    if not job.originalPath:
        raise RuntimeError("원본 파일 경로가 없습니다")

    original_ext = Path(job.originalPath).suffix.lower()

    # ── .doc 바이너리: python-docx로 열 수 없으므로 새 문서로 생성 ──
    if original_ext == ".doc":
        return _export_docx_from_blocks(blocks, EXPORTS_DIR / f"{job.id}.docx")

    # ── .docx: 원본 열고 텍스트만 교체 (서식 유지) ───────────────────
    doc = Document(job.originalPath)
    translation_map = {b.id: (b.translatedText or "") for b in blocks}

    # 일반 단락 교체
    for para_idx, para in enumerate(doc.paragraphs):
        translated = translation_map.get(f"para-{para_idx}")
        if translated is None:
            continue
        # runs 전체를 유지하되 첫 번째 run에 번역문을 넣고 나머지를 비움
        # → bold/italic/font/color 등 인라인 서식이 첫 run 기준으로 유지됨
        if para.runs:
            para.runs[0].text = translated
            for run in para.runs[1:]:
                run.text = ""
        else:
            para.clear()
            para.add_run(translated)

    # 표 셀 교체
    seen_cells: set = set()
    for tbl_idx, table in enumerate(doc.tables):
        for row_idx, row in enumerate(table.rows):
            for col_idx, cell in enumerate(row.cells):
                cell_key = id(cell._tc)
                if cell_key in seen_cells:
                    continue
                seen_cells.add(cell_key)
                translated = translation_map.get(f"tbl-{tbl_idx}-r{row_idx}-c{col_idx}")
                if translated is None:
                    continue
                if cell.paragraphs and cell.paragraphs[0].runs:
                    cell.paragraphs[0].runs[0].text = translated
                    for run in cell.paragraphs[0].runs[1:]:
                        run.text = ""
                elif cell.paragraphs:
                    cell.paragraphs[0].clear()
                    cell.paragraphs[0].add_run(translated)

    out_path = EXPORTS_DIR / f"{job.id}.docx"
    doc.save(out_path)
    return out_path


def _export_docx_from_blocks(blocks: List[DocumentBlock], out_path: Path) -> Path:
    """번역 블록만으로 새 DOCX 문서를 생성 (서식 없음).
    .doc 바이너리 원본처럼 원본 서식을 읽을 수 없는 경우에 사용."""
    from docx import Document  # type: ignore
    doc = Document()
    for block in blocks:
        text = block.translatedText or ""
        if not text.strip():
            continue
        doc.add_paragraph(text)
    doc.save(out_path)
    return out_path


def export_xlsx_preserving(job: TranslationJob, blocks: List[DocumentBlock]) -> Path:
    """xlsx 서식을 유지하면서 번역 텍스트만 교체.
    원본이 .xls 바이너리인 경우 서식 없이 새 XLSX를 생성합니다."""
    try:
        import openpyxl  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "XLSX 내보내기에는 openpyxl이 필요합니다: pip install openpyxl"
        ) from exc

    if not job.originalPath:
        raise RuntimeError("원본 파일 경로가 없습니다")

    out_path = EXPORTS_DIR / f"{job.id}.xlsx"
    original_ext = Path(job.originalPath).suffix.lower()

    # ── .xls 바이너리: openpyxl로 열 수 없으므로 새 문서로 생성 ───────
    if original_ext == ".xls":
        return _export_xlsx_from_blocks(blocks, out_path)

    # ── .xlsx: 원본 열고 셀 값만 교체 (서식 유지) ────────────────────
    # keep_vba=True 로 매크로 유지, data_only=False 로 수식 셀도 보존
    wb = openpyxl.load_workbook(job.originalPath, keep_vba=True)
    translation_map = {b.id: (b.translatedText or "") for b in blocks}

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for row in ws.iter_rows():
            for cell in row:
                block_id = f"sheet-{sheet_name}-{cell.coordinate}"
                translated = translation_map.get(block_id)
                if translated is None:
                    continue
                # 셀 값만 교체 — number_format, font, fill, border 등은 그대로
                cell.value = translated

    wb.save(out_path)
    return out_path


def _export_xlsx_from_blocks(blocks: List[DocumentBlock], out_path: Path) -> Path:
    """번역 블록만으로 새 XLSX 문서를 생성 (서식 없음).
    .xls 바이너리처럼 원본 서식을 읽을 수 없는 경우에 사용."""
    import openpyxl  # type: ignore
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    sheets: dict = {}

    for block in blocks:
        if block.type != "xlsx_cell":
            continue
        sheet_name = block.sheetName or "Sheet1"
        if sheet_name not in sheets:
            if not sheets:
                ws = wb.active
                ws.title = sheet_name
            else:
                ws = wb.create_sheet(sheet_name)
            sheets[sheet_name] = ws
        else:
            ws = sheets[sheet_name]

        coord = block.metadata.get("coordinate", "A1")
        ws[coord] = block.translatedText or ""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path
