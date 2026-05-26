import re
import subprocess
from pathlib import Path
from typing import List

from app.models import DocumentBlock


def extract_blocks(path: Path, file_type: str) -> List[DocumentBlock]:
    if file_type in {"txt", "md"}:
        return extract_text_blocks(path, file_type)
    if file_type == "pdf":
        return extract_pdf_blocks(path)
    if file_type == "docx":
        return extract_docx_blocks(path)
    if file_type == "doc":
        return extract_doc_blocks(path)
    if file_type == "xlsx":
        return extract_xlsx_blocks(path)
    if file_type == "xls":
        return extract_xls_blocks(path)
    raise ValueError(f"{file_type.upper()} extraction is not supported")


def extract_text_blocks(path: Path, file_type: str) -> List[DocumentBlock]:
    text = path.read_text(encoding="utf-8", errors="replace")
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not parts and text.strip():
        parts = [text.strip()]
    blocks = []
    for index, part in enumerate(parts):
        block_type = "paragraph"
        if file_type == "md" and part.startswith("#"):
            block_type = "heading"
        blocks.append(
            DocumentBlock(
                id=f"block-{index + 1}",
                type=block_type,
                sourceText=part,
                order=index,
                metadata={"fileType": file_type},
            )
        )
    return blocks


def extract_pdf_blocks(path: Path) -> List[DocumentBlock]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PDF extraction requires PyMuPDF. Install dependencies with: python3 -m pip install PyMuPDF"
        ) from exc

    doc = fitz.open(path)
    blocks: List[DocumentBlock] = []
    order = 0
    for page_index, page in enumerate(doc):
        raw = page.get_text("dict")
        for raw_block in raw.get("blocks", []):
            if raw_block.get("type") != 0:
                continue
            for line in raw_block.get("lines", []):
                spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
                if not spans:
                    continue
                text = "".join(span.get("text", "") for span in spans).strip()
                first_span = spans[0]
                x0, y0, x1, y1 = line.get("bbox", first_span.get("bbox"))
                blocks.append(
                    DocumentBlock(
                        id=f"page-{page_index + 1}-span-{order + 1}",
                        type="pdf_text_span",
                        sourceText=text,
                        translatedText=None,
                        pageNumber=page_index + 1,
                        bbox=(float(x0), float(y0), float(x1), float(y1)),
                        fontSize=float(first_span.get("size", 10)),
                        order=order,
                        metadata={
                            "font": first_span.get("font"),
                            "color": first_span.get("color"),
                        },
                    )
                )
                order += 1
    doc.close()
    return blocks


def extract_docx_blocks(path: Path) -> List[DocumentBlock]:
    """python-docx로 단락 및 표 셀 텍스트를 추출.
    메타데이터에 단락/테이블 인덱스를 저장해 내보내기 시 원위치 교체에 사용."""
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "DOCX 추출에는 python-docx가 필요합니다: pip install python-docx"
        ) from exc

    doc = Document(path)
    blocks: List[DocumentBlock] = []
    order = 0

    # ── 일반 단락 ──────────────────────────────────────────
    for para_idx, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
        blocks.append(
            DocumentBlock(
                id=f"para-{para_idx}",
                type="docx_paragraph",
                sourceText=text,
                order=order,
                metadata={
                    "para_index": para_idx,
                    "style": para.style.name if para.style else "",
                    "alignment": str(para.alignment),
                },
            )
        )
        order += 1

    # ── 표 셀 ──────────────────────────────────────────────
    for tbl_idx, table in enumerate(doc.tables):
        seen_cells: set = set()          # 병합 셀 중복 방지
        for row_idx, row in enumerate(table.rows):
            for col_idx, cell in enumerate(row.cells):
                cell_key = id(cell._tc)  # 병합 셀은 같은 _tc를 공유
                if cell_key in seen_cells:
                    continue
                seen_cells.add(cell_key)
                text = cell.text.strip()
                if not text:
                    continue
                blocks.append(
                    DocumentBlock(
                        id=f"tbl-{tbl_idx}-r{row_idx}-c{col_idx}",
                        type="docx_table_cell",
                        sourceText=text,
                        order=order,
                        metadata={
                            "table_index": tbl_idx,
                            "row_index": row_idx,
                            "col_index": col_idx,
                        },
                    )
                )
                order += 1

    return blocks


def extract_doc_blocks(path: Path) -> List[DocumentBlock]:
    """구형 .doc 바이너리 형식 — antiword CLI로 텍스트를 추출.
    서식 정보는 손실되며, 내보내기 시 새 DOCX 파일로 생성됩니다."""
    try:
        result = subprocess.run(
            ["antiword", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "antiword가 설치되어 있지 않습니다. "
            "Docker 환경에서는 Dockerfile에 'antiword' 패키지를 추가하세요."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("antiword 실행 시간 초과")

    if result.returncode != 0:
        raise RuntimeError(
            f"antiword 실행 실패 (code={result.returncode}): {result.stderr.strip() or '알 수 없는 오류'}"
        )

    text = result.stdout
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not parts and text.strip():
        parts = [text.strip()]

    blocks = []
    for idx, part in enumerate(parts):
        blocks.append(
            DocumentBlock(
                id=f"para-{idx}",
                type="docx_paragraph",   # export 시 docx 단락으로 취급
                sourceText=part,
                order=idx,
                metadata={"fileType": "doc", "para_index": idx},
            )
        )
    return blocks


def extract_xlsx_blocks(path: Path) -> List[DocumentBlock]:
    """openpyxl로 시트별 셀 텍스트를 추출.
    메타데이터에 시트명·셀 좌표를 저장해 내보내기 시 원위치 교체에 사용."""
    try:
        import openpyxl  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "XLSX 추출에는 openpyxl이 필요합니다: pip install openpyxl"
        ) from exc

    wb = openpyxl.load_workbook(path, data_only=True)
    blocks: List[DocumentBlock] = []
    order = 0

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for row in ws.iter_rows():
            for cell in row:
                raw = cell.value
                if raw is None:
                    continue
                text = str(raw).strip()
                if not text:
                    continue
                blocks.append(
                    DocumentBlock(
                        id=f"sheet-{sheet_name}-{cell.coordinate}",
                        type="xlsx_cell",
                        sourceText=text,
                        sheetName=sheet_name,
                        order=order,
                        metadata={
                            "sheet": sheet_name,
                            "coordinate": cell.coordinate,
                            "row": cell.row,
                            "col": cell.column,
                            "number_format": cell.number_format or "General",
                        },
                    )
                )
                order += 1

    return blocks


def extract_xls_blocks(path: Path) -> List[DocumentBlock]:
    """구형 .xls 바이너리 형식 — xlrd로 텍스트를 추출.
    내보내기 시 새 XLSX 파일로 생성됩니다."""
    try:
        import xlrd  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "XLS 추출에는 xlrd가 필요합니다: pip install 'xlrd>=1.2,<2'"
        ) from exc

    wb = xlrd.open_workbook(str(path))
    blocks: List[DocumentBlock] = []
    order = 0

    for sheet_idx in range(wb.nsheets):
        ws = wb.sheet_by_index(sheet_idx)
        sheet_name = ws.name
        for row_idx in range(ws.nrows):
            for col_idx in range(ws.ncols):
                cell = ws.cell(row_idx, col_idx)
                if cell.ctype == xlrd.XL_CELL_EMPTY:
                    continue
                text = str(cell.value).strip()
                if not text:
                    continue
                # openpyxl 호환 좌표 문자열 생성 (A1, B2, ...)
                col_letter = _col_letter(col_idx)
                coordinate = f"{col_letter}{row_idx + 1}"
                blocks.append(
                    DocumentBlock(
                        id=f"sheet-{sheet_name}-{coordinate}",
                        type="xlsx_cell",   # export 시 xlsx_cell로 취급
                        sourceText=text,
                        sheetName=sheet_name,
                        order=order,
                        metadata={
                            "sheet": sheet_name,
                            "coordinate": coordinate,
                            "row": row_idx + 1,
                            "col": col_idx + 1,
                        },
                    )
                )
                order += 1

    return blocks


def _col_letter(col_idx: int) -> str:
    """0-based column index → Excel 열 문자 (0→A, 25→Z, 26→AA ...)"""
    result = ""
    n = col_idx
    while True:
        result = chr(ord("A") + n % 26) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result
