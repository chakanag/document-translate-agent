# Layout-Preserving PDF Translation Strategy

## Requirement

When the source document is a Japanese PDF and the target language is Korean, the exported PDF must preserve the original visual composition. Images, charts, tables, page size, drawing objects, and general placement should remain unchanged. Only text should be translated and replaced.

## Core Approach

Use the original PDF page as the base canvas.

1. Extract text spans from each page with bounding boxes, font size, and reading order.
2. Translate the extracted Japanese text into Korean.
3. Redact or cover only the original text bounding boxes.
4. Insert translated Korean text back into the same bounding boxes.
5. Embed a Korean-capable font such as Noto Sans CJK KR.
6. Save the modified PDF as the translated output.

## Digital PDF Path

For PDFs with selectable text:

- Use PyMuPDF to extract text spans and coordinates.
- Preserve original images, vector drawings, chart graphics, table lines, and page geometry.
- Replace text by bounding box.
- Fit Korean text using wrapping, font-size reduction, or overflow warnings.

## Scanned PDF Path

For image-only PDFs:

- Run Japanese OCR with bounding boxes.
- Translate OCR text.
- Overlay translated Korean text on the original page image.
- Preserve the scanned page image underneath.

This path is less reliable because OCR errors and background text cleanup can affect visual quality.

## Tables and Charts

Tables should preserve borders, cell geometry, and background styling. Only the text inside detected cell or text span boxes should be replaced.

Charts are handled depending on how the PDF stores chart labels:

- If labels are real PDF text, replace them like other text spans.
- If labels are embedded inside chart images, OCR and overlay are required.
- If image labels cannot be cleanly detected, report a preview warning before export.

## Known Constraints

- Korean translation may be longer than Japanese source text.
- Some PDFs have broken text extraction order.
- Font substitution may slightly change glyph metrics.
- Flattened or scanned PDFs require OCR and may not support perfect text removal.
- Password-protected or restricted PDFs may need user-provided permission before processing.

## QA Checks

- Page count unchanged.
- Page size unchanged.
- Image count unchanged.
- Drawing object count approximately unchanged.
- Text block count translated.
- No large Japanese text regions remain, except intentional terms or OCR failures.
- Exported PDF opens successfully.
