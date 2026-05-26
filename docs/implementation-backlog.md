# Implementation Backlog

## Epic 1. Project Foundation

- [ ] Backend app scaffold
- [ ] Frontend app scaffold
- [ ] Shared job status and file type constants
- [ ] Local storage directories for originals, extracted blocks, translated blocks, exports
- [ ] SQLite schema and migration setup

Acceptance criteria:

- App can start locally.
- Health check API returns OK.
- Empty history list can be loaded.

## Epic 2. Upload and Options

- [ ] Target language selector
- [ ] Output format selector
- [ ] File upload component
- [ ] File type validation for PDF, DOC, DOCX, TXT, MD, XLS, XLSX
- [ ] Translation job creation API

Acceptance criteria:

- Supported file creates a job.
- Unsupported file returns a clear error.
- Job stores original filename, file type, target language, output format, and status.

## Epic 3. Text Extraction

- [ ] TXT extractor
- [ ] MD extractor
- [ ] PDF text span and bounding box extractor
- [ ] PDF image, drawing, page geometry metadata extractor
- [ ] DOCX extractor
- [ ] XLSX extractor
- [ ] Extraction warning model

Acceptance criteria:

- Extracted content is stored as ordered blocks.
- PDF blocks include page number, bounding box, font size, and reading order.
- Empty or unreadable documents fail with a user-visible reason.

## Epic 4. Language Detection and Translation

- [ ] Source language detection
- [ ] Translation provider interface
- [ ] Chunking strategy
- [ ] Retry and partial failure handling
- [ ] Translation block persistence

Acceptance criteria:

- Job source language is detected.
- Blocks are translated into the selected target language.
- Translation preserves block order.

## Epic 5. Preview

- [ ] Preview API
- [ ] Side-by-side source and translated content
- [ ] Page/sheet/block navigation
- [ ] Warning display
- [ ] Export confirmation action

Acceptance criteria:

- User can inspect source and translated content before download.
- Preview reflects latest translated blocks.

## Epic 6. Export and Download

- [ ] TXT export
- [ ] MD export
- [ ] DOC/DOCX export
- [ ] XLS/XLSX export
- [ ] Layout-preserving PDF text replacement export
- [ ] Korean font embedding for translated PDF
- [ ] Text fitting strategy for translated PDF bounding boxes
- [ ] Download API

Acceptance criteria:

- User can select a supported output format.
- Exported file is linked to the job.
- PDF export preserves original page count, page size, images, charts, table lines, and drawing objects.
- PDF export changes text content only, within the original text regions as much as possible.
- Download returns the generated file.

## Epic 7. History

- [ ] History list API
- [ ] History detail API
- [ ] Delete history item
- [ ] Re-download completed output
- [ ] Retry failed job

Acceptance criteria:

- User can see previous translation jobs.
- Completed jobs expose download links.
- Failed jobs show failure reason.

## Epic 8. QA and Observability

- [ ] Block count consistency checks
- [ ] Untranslated segment checks
- [ ] PDF visual preservation checks
- [ ] Export readability checks
- [ ] Structured logging
- [ ] Error dashboard or admin logs

Acceptance criteria:

- Job completion includes QA result.
- Known failure modes are logged with enough context to debug.
