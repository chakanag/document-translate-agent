# AI Agent Blueprint

## 목표

사용자는 문서를 업로드하고 최종 번역 언어와 다운로드 형식을 선택한다. 시스템은 원문 언어를 감지하고 문서 내용을 번역한 뒤, 원문/번역 미리보기를 제공하고, 사용자가 원하는 형식의 번역 문서를 다운로드할 수 있게 한다. PDF의 경우 원본의 이미지, 차트, 테이블, 페이지 구성은 유지하고 문자 영역만 번역어로 치환하는 것을 목표로 한다. 모든 작업은 이력으로 남긴다.

## 권장 시스템 구조

### Frontend

- 업로드 화면
- 대상 언어 선택기
- 문서 종류 표시 및 검증 결과
- 원문/번역 미리보기 화면
- 다운로드 형식 선택
- 번역 이력 화면

### Backend

- 파일 업로드 API
- 문서 파서
- 번역 작업 큐
- AI 번역 오케스트레이터
- 미리보기 데이터 생성
- 문서 내보내기
- 이력 DB

### Storage

- 원본 파일 저장소
- 추출된 block JSON
- 번역된 block JSON
- 내보낸 결과 파일
- 작업 이력 DB

## Agent 역할

### 1. Intake Agent

업로드 파일과 사용자 옵션을 검증한다. 파일 확장자만 믿지 않고 MIME type, 크기, 지원 가능 여부를 함께 확인한다.

### 2. Extraction Agent

문서별 파서를 선택해 텍스트와 구조를 추출한다.

- PDF: page, text span, bounding box, font size, table 영역, drawing/image 객체 정보 추출
- DOC/DOCX: heading, paragraph, table 추출
- TXT: line/paragraph 추출
- MD: markdown block 추출
- XLS/XLSX: sheet, row, cell 단위 추출

### 3. Language Detection Agent

대표 텍스트 샘플에서 원본 언어를 감지한다. 문서가 혼합 언어인 경우 block별 언어도 기록한다.

### 4. Translation Agent

긴 문서를 chunk로 나누어 번역한다. 문장 의미뿐 아니라 표, 숫자, placeholder, markdown syntax, 고유명사를 보존한다.

### 5. Preview Agent

사용자에게 원문과 번역문을 함께 보여줄 preview model을 만든다. PDF는 page 중심, XLS는 sheet 중심, 일반 문서는 block 중심으로 탐색하게 한다.

### 6. Export Agent

번역된 block을 원하는 형식으로 재조립한다. PDF 출력에서는 원본 페이지 canvas를 유지하고 이미지, 차트, 도형, 테이블 선, 배경은 건드리지 않는다. 기존 문자 영역만 가림 처리 또는 redaction 후 같은 bounding box에 한국어 번역문을 overlay한다. 사용자가 다른 출력 형식을 선택한 경우에는 해당 형식에 맞는 구조 보존 export를 수행한다.

### 7. History Agent

작업 상태, 원본 파일명, 문서 종류, 원문 언어, 번역 언어, 다운로드 형식, 생성 시각, 완료 시각, 실패 사유, 다운로드 링크를 관리한다.

### 8. QA Agent

완료 전 자동 검증을 수행한다.

- 추출 block 수와 번역 block 수 일치 여부
- 큰 미번역 구간 존재 여부
- PDF page count, page size, 이미지 수, drawing 객체 보존 여부
- 표/markdown 구조 보존 여부
- export 파일 생성 및 열람 가능 여부

## 기본 데이터 모델

```ts
type TranslationJob = {
  id: string;
  originalFileName: string;
  fileType: "pdf" | "doc" | "docx" | "txt" | "md" | "xls" | "xlsx";
  sourceLanguage?: string;
  targetLanguage: string;
  outputFormat: "pdf" | "doc" | "docx" | "txt" | "md" | "xls" | "xlsx";
  status:
    | "queued"
    | "extracting"
    | "extracted"
    | "detecting_language"
    | "language_detected"
    | "translating"
    | "translated"
    | "preview_ready"
    | "verified"
    | "exporting"
    | "completed"
    | "failed"
    | "cancelled";
  createdAt: string;
  updatedAt: string;
  completedAt?: string;
  errorMessage?: string;
};

type DocumentBlock = {
  id: string;
  type: "heading" | "paragraph" | "table" | "cell" | "list" | "code" | "page" | "pdf_text_span";
  sourceText: string;
  translatedText?: string;
  pageNumber?: number;
  sheetName?: string;
  bbox?: [number, number, number, number];
  fontSize?: number;
  order: number;
  metadata?: Record<string, unknown>;
};

type PreviewModel = {
  job: TranslationJob;
  blocks: DocumentBlock[];
  warnings: string[];
};
```

## API 설계 초안

```http
POST /api/documents
Content-Type: multipart/form-data

file=<document>
targetLanguage=ko
outputFormat=docx
```

```http
GET /api/jobs/{job_id}
GET /api/jobs/{job_id}/preview
POST /api/jobs/{job_id}/export
GET /api/jobs/{job_id}/download
GET /api/history
DELETE /api/history/{job_id}
```

## 상태 흐름

```mermaid
flowchart LR
  A["Upload"] --> B["Extract"]
  B --> C["Detect Language"]
  C --> D["Translate"]
  D --> E["Preview"]
  E --> F["QA"]
  F --> G["Export"]
  G --> H["History"]
```

## 기술 스택 제안

- Backend: FastAPI
- Frontend: React 또는 Next.js
- DB: SQLite로 시작, 이후 PostgreSQL 전환 가능
- Background Jobs: RQ/Celery 또는 FastAPI BackgroundTasks로 시작
- PDF: PyMuPDF/pdfplumber
- Layout-preserving PDF export: PyMuPDF redaction/overlay, Korean font embedding
- DOCX: python-docx
- XLSX: openpyxl
- Markdown: markdown-it-py 또는 mistune
- AI Translation: provider adapter 패턴으로 OpenAI, Azure OpenAI, local model 교체 가능하게 구성

## MVP 범위

1. TXT, MD 업로드 및 번역
2. 대상 언어 선택
3. block 기반 미리보기
4. TXT/MD 다운로드
5. 이력 목록/상세

## 2차 범위

1. PDF/DOCX/XLSX 파서 추가
2. DOCX/XLSX/PDF export
3. OCR fallback
4. glossary/style guide
5. 사용자별 이력/권한
