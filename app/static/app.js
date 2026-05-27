// ── DOM refs ──────────────────────────────────────────────────────────
const uploadForm        = document.querySelector("#uploadForm");
const fileInput         = document.querySelector("#fileInput");
const fileLabel         = document.querySelector("#fileLabel");
const statusRow         = document.querySelector("#statusRow");
const statusText        = document.querySelector("#statusText");
const sourcePreview     = document.querySelector("#sourcePreview");
const targetPreview     = document.querySelector("#targetPreview");
const sourceMeta        = document.querySelector("#sourceMeta");
const targetMeta        = document.querySelector("#targetMeta");
const exportButton      = document.querySelector("#exportButton");
const downloadLink      = document.querySelector("#downloadLink");
const downloadHint      = document.querySelector("#downloadHint");
const historyList       = document.querySelector("#historyList");
const refreshHistory    = document.querySelector("#refreshHistory");
const aiProviderSelect  = document.querySelector("#aiProvider");
const editToggle        = document.querySelector("#editToggle");
const editBar           = document.querySelector("#editBar");
const saveEditsButton   = document.querySelector("#saveEditsButton");
const cancelEditButton  = document.querySelector("#cancelEditButton");

// 문서 미리보기 refs
const docSourceContainer = document.querySelector("#docSourceContainer");
const docTargetContainer = document.querySelector("#docTargetContainer");
const docSourceMeta      = document.querySelector("#docSourceMeta");
const docTargetMeta      = document.querySelector("#docTargetMeta");

let currentJobId   = null;
let currentBlocks  = [];   // 현재 로드된 블록 배열 (편집 기준값)
let editMode       = false;
let currentJobData = null; // 현재 job 메타

// ── 뷰 모드 탭 ──────────────────────────────────────────────────────
const tabBtns   = document.querySelectorAll(".tab-btn");
const viewPanels = document.querySelectorAll(".view-panel");

tabBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    const view = btn.dataset.view;
    tabBtns.forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    viewPanels.forEach((p) => {
      p.hidden = p.id !== `view${view.charAt(0).toUpperCase() + view.slice(1)}`;
    });
    if (view === "doc" && currentJobId) {
      renderDocPreview(currentJobId, currentJobData);
    }
  });
});

// ── 스크롤 싱크 ───────────────────────────────────────────────────────
// 현재 실제로 사용자가 조작 중인 패널을 기억.
// target.scrollTop을 바꾸면 target에서도 scroll 이벤트가 발생하는데,
// 그 이벤트는 무시해야 진동(무한루프)이 생기지 않는다.
let activeScrollEl = null;
let scrollReleaseTimer = null;

function syncScrollFrom(source, target) {
  // 프로그래밍적으로 발생한 scroll 이벤트면 무시
  if (activeScrollEl && activeScrollEl !== source) return;

  activeScrollEl = source;
  clearTimeout(scrollReleaseTimer);

  const maxSrc = source.scrollHeight - source.clientHeight;
  const ratio  = maxSrc > 0 ? source.scrollTop / maxSrc : 0;
  target.scrollTop = ratio * (target.scrollHeight - target.clientHeight);

  // 사용자가 스크롤을 멈춘 후 잠시 뒤 잠금 해제
  scrollReleaseTimer = setTimeout(() => { activeScrollEl = null; }, 80);
}

sourcePreview.addEventListener("scroll", () => syncScrollFrom(sourcePreview, targetPreview));
targetPreview.addEventListener("scroll", () => syncScrollFrom(targetPreview, sourcePreview));

// ── 원문 클릭 → 번역 포커싱 ──────────────────────────────────────────
function attachBlockClickHandlers() {
  const srcBlocks = sourcePreview.querySelectorAll(".block[data-idx]");
  srcBlocks.forEach((srcBlock) => {
    srcBlock.addEventListener("click", () => {
      const idx = srcBlock.dataset.idx;
      const tgtBlock = targetPreview.querySelector(`.block[data-idx="${idx}"]`);
      if (!tgtBlock) return;

      // 이전 하이라이트 제거
      targetPreview.querySelectorAll(".block.focused").forEach((b) => b.classList.remove("focused"));
      sourcePreview.querySelectorAll(".block.active-src").forEach((b) => b.classList.remove("active-src"));

      // 현재 블록 강조
      srcBlock.classList.add("active-src");
      tgtBlock.classList.add("focused");

      // 번역 패널 스크롤 (블록이 패널 중앙에 오도록)
      const panelTop    = targetPreview.getBoundingClientRect().top;
      const blockTop    = tgtBlock.getBoundingClientRect().top;
      const offset      = blockTop - panelTop - targetPreview.clientHeight / 2 + tgtBlock.clientHeight / 2;
      // 클릭 이동 중에는 싱크 루프 방지 (smooth scroll이 끝날 때까지)
      activeScrollEl = targetPreview;
      clearTimeout(scrollReleaseTimer);
      targetPreview.scrollBy({ top: offset, behavior: "smooth" });
      scrollReleaseTimer = setTimeout(() => { activeScrollEl = null; }, 600);
    });
  });
}

// ── 파일 선택 ─────────────────────────────────────────────────────────
const ocrRow      = document.querySelector("#ocrRow");
const ocrEngine   = document.querySelector("#ocrEngine");
const ocrCostHint = document.querySelector("#ocrCostHint");

// Claude Vision 비용 안내 (페이지 수 미리 읽기)
async function _getPdfPageCount(file) {
  // PDF 헤더에서 /Count 값으로 간이 추정
  const buf = await file.slice(0, 1024 * 50).arrayBuffer();
  const text = new TextDecoder("latin1").decode(buf);
  const m = text.match(/\/Count\s+(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

function _updateOcrCostHint(pageCount) {
  if (!ocrCostHint) return;
  if (ocrEngine.value === "claude_vision") {
    const lo = pageCount ? (pageCount * 0.003).toFixed(3) : "?";
    const hi = pageCount ? (pageCount * 0.006).toFixed(3) : "?";
    ocrCostHint.textContent = `예상 비용: $${lo}~$${hi} (페이지당 약 $0.003~$0.006, Claude Haiku 기준)`;
    ocrCostHint.hidden = false;
  } else {
    ocrCostHint.hidden = true;
  }
}

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  fileLabel.textContent = file ? file.name : "PDF, DOC, TXT, MD, XLS 문서를 선택하세요";
  if (file) {
    const ext = file.name.split(".").pop().toLowerCase();
    // 입력 확장자 → 기본 출력 포맷 매핑 (동일 계열끼리 연결)
    const FORMAT_MAP = {
      pdf: "pdf", txt: "txt", md: "md",
      doc: "docx", docx: "docx",
      xls: "xlsx", xlsx: "xlsx",
    };
    document.querySelector("#outputFormat").value = FORMAT_MAP[ext] || "txt";

    // PDF일 때만 OCR 옵션 표시
    if (ext === "pdf") {
      ocrRow.hidden = false;
      const pageCount = await _getPdfPageCount(file);
      ocrEngine._pageCount = pageCount;
      _updateOcrCostHint(pageCount);
    } else {
      ocrRow.hidden = true;
      if (ocrEngine) ocrEngine.value = "none";
    }
  }
});

ocrEngine && ocrEngine.addEventListener("change", () => {
  _updateOcrCostHint(ocrEngine._pageCount || null);
});

// ── Provider 레이블 ───────────────────────────────────────────────────
const PROVIDER_LABELS = {
  deepl:     "DeepL",
  papago:    "Papago (Naver)",
  openai:    "OpenAI GPT",
  gemini:    "Google Gemini",
  anthropic: "Claude (Anthropic)",
  ollama:    "Local Ollama",
  demo:      "Demo",
};

function statusLabel(status, aiProvider) {
  const providerName = PROVIDER_LABELS[aiProvider] || aiProvider || "AI";
  const labels = {
    queued:            "대기 중...",
    extracting:        "문서 텍스트 추출 중...",
    detecting_language:"언어 감지 중...",
    translating:       `번역 중... (${providerName} 처리 중)`,
    preview_ready:     "번역 완료 — 미리보기 로드 중",
    verified:          "번역 완료 — 미리보기 로드 중",
    exporting:         "문서 생성 중...",
    completed:         "완료",
    failed:            "오류 발생",
  };
  return labels[status] || status;
}

// ── 폴링 ──────────────────────────────────────────────────────────────
async function pollJobUntilDone(jobId, intervalMs = 1500) {
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const res  = await fetch(`/api/jobs/${jobId}`);
        const data = await res.json();
        const job  = data;
        const label = statusLabel(job.status, job.aiProvider);
        setStatus(label);
        if (["preview_ready", "verified", "completed"].includes(job.status)) {
          clearInterval(timer);
          resolve(job);
        } else if (job.status === "failed") {
          clearInterval(timer);
          reject(new Error(job.errorMessage || "번역 실패"));
        }
      } catch (err) {
        clearInterval(timer);
        reject(err);
      }
    }, intervalMs);
  });
}

// ── 업로드 제출 ───────────────────────────────────────────────────────
const MAX_UPLOAD_MB = 20;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file) return;

  if (file.size > MAX_UPLOAD_BYTES) {
    setStatus(`파일 크기 초과: ${(file.size / 1024 / 1024).toFixed(1)} MB (최대 ${MAX_UPLOAD_MB} MB)`, true);
    return;
  }

  setStatus("업로드 중...");
  exportButton.disabled = true;
  downloadLink.classList.add("disabled");
  downloadLink.href = "#";

  const formData = new FormData(uploadForm);
  try {
    const response = await fetch("/api/documents", { method: "POST", body: formData });
    const payload  = await response.json();
    if (!response.ok) throw new Error(payload.error || "업로드 실패");
    currentJobId = payload.job.id;
    await pollJobUntilDone(currentJobId);
    await loadPreview(currentJobId);
    await loadHistory();
  } catch (error) {
    setStatus(error.message, true);
  }
});

// ── 문서 생성 ─────────────────────────────────────────────────────────
exportButton.addEventListener("click", async () => {
  if (!currentJobId) return;
  setStatus("문서 생성 중...");
  try {
    const response = await fetch(`/api/jobs/${currentJobId}/export`, { method: "POST" });
    const payload  = await response.json();
    if (!response.ok) throw new Error(payload.error || payload.job?.errorMessage || "문서 생성 실패");
    setStatus("문서 생성 완료");
    downloadLink.href = `/api/jobs/${currentJobId}/download`;
    downloadLink.classList.remove("disabled");
    downloadHint.textContent = `${payload.job.outputFormat.toUpperCase()} 파일을 내려받을 수 있습니다.`;
    currentJobData = payload.job;
    // 문서 뷰가 열려있으면 번역 미리보기 갱신
    if (!document.querySelector("#viewDoc").hidden) {
      renderDocPreview(currentJobId, currentJobData);
    }
    await loadHistory();
  } catch (error) {
    setStatus(error.message, true);
  }
});

// ── 편집 모드 ─────────────────────────────────────────────────────────
function enterEditMode() {
  editMode = true;
  editToggle.textContent = "👁 보기";
  editToggle.classList.add("active");
  editBar.hidden = false;

  const blocks = targetPreview.querySelectorAll(".block");
  blocks.forEach((div, idx) => {
    const ta       = document.createElement("textarea");
    ta.className   = "block-edit";
    ta.value       = div.textContent;
    ta.dataset.idx = idx;
    ta.addEventListener("input", () => {
      ta.style.height = "auto";
      ta.style.height = ta.scrollHeight + "px";
    });
    div.replaceWith(ta);
  });
  targetPreview.querySelectorAll(".block-edit").forEach((ta) => {
    ta.style.height = "auto";
    ta.style.height = ta.scrollHeight + "px";
  });
}

function exitEditMode(applyChanges = false) {
  editMode = false;
  editToggle.textContent = "✏️ 편집";
  editToggle.classList.remove("active");
  editBar.hidden = true;

  const textareas = targetPreview.querySelectorAll(".block-edit");
  textareas.forEach((ta) => {
    const idx      = parseInt(ta.dataset.idx, 10);
    const original = currentBlocks[idx]?.translatedText || "";
    const current  = ta.value;
    const div      = document.createElement("div");
    div.className  = "block";
    div.dataset.idx = idx;
    if (applyChanges && current !== original) {
      div.classList.add("edited");
      if (currentBlocks[idx]) currentBlocks[idx].translatedText = current;
    }
    div.textContent = applyChanges ? current : original;
    ta.replaceWith(div);
  });
  // 편집 모드 종료 후 클릭 핸들러 재등록
  attachBlockClickHandlers();
}

editToggle.addEventListener("click", () => {
  if (editMode) exitEditMode(false);
  else enterEditMode();
});

cancelEditButton.addEventListener("click", () => exitEditMode(false));

saveEditsButton.addEventListener("click", async () => {
  if (!currentJobId) return;

  const updates = [];
  targetPreview.querySelectorAll(".block-edit").forEach((ta) => {
    const idx      = parseInt(ta.dataset.idx, 10);
    const original = currentBlocks[idx]?.translatedText || "";
    if (ta.value !== original) {
      updates.push({ id: currentBlocks[idx].id, translatedText: ta.value });
    }
  });

  if (updates.length === 0) {
    setStatus("변경된 내용이 없습니다.");
    exitEditMode(false);
    return;
  }

  saveEditsButton.disabled = true;
  setStatus(`${updates.length}개 블록 저장 중...`);
  try {
    const res  = await fetch(`/api/jobs/${currentJobId}/blocks`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "저장 실패");

    exitEditMode(true);
    setStatus(`✅ ${updates.length}개 블록 저장 완료 — 문서 생성 버튼으로 다시 생성하세요.`);
    exportButton.disabled = false;
    downloadLink.href = "#";
    downloadLink.classList.add("disabled");
    downloadHint.textContent = "수정된 번역으로 문서를 다시 생성하세요.";
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    saveEditsButton.disabled = false;
  }
});

// ── 워크스페이스 초기화 ───────────────────────────────────────────────
function resetWorkspace() {
  // 편집 모드 중이면 취소
  if (editMode) exitEditMode(false);

  // 상태 변수 초기화
  currentJobId   = null;
  currentBlocks  = [];
  currentJobData = null;

  // 파일 입력 초기화
  uploadForm.reset();
  fileLabel.textContent = "PDF, DOC, TXT, MD, XLS 문서를 선택하세요";

  // 상태 표시 초기화
  setStatus("대기 중");

  // 텍스트 뷰 미리보기 초기화
  sourcePreview.innerHTML = "업로드 후 원문이 표시됩니다.";
  sourcePreview.classList.add("empty");
  targetPreview.innerHTML = "업로드 후 번역 미리보기가 표시됩니다.";
  targetPreview.classList.add("empty");
  sourceMeta.textContent = "";
  targetMeta.textContent = "";
  editToggle.hidden = true;
  editBar.hidden    = true;

  // 문서 미리보기 초기화
  docSourceContainer.innerHTML = '<p class="doc-placeholder">번역 후 원본 문서 미리보기가 표시됩니다.</p>';
  docTargetContainer.innerHTML = '<p class="doc-placeholder">번역 후 문서 미리보기가 표시됩니다.</p>';
  docSourceMeta.textContent = "";
  docTargetMeta.textContent = "";

  // 다운로드 영역 초기화
  exportButton.disabled = true;
  downloadLink.href = "#";
  downloadLink.classList.add("disabled");
  downloadHint.textContent = "미리보기 생성 후 export 할 수 있습니다.";

  // 뷰 탭을 텍스트 뷰로 초기화
  tabBtns.forEach((b) => b.classList.toggle("active", b.dataset.view === "text"));
  viewPanels.forEach((p) => { p.hidden = p.id !== "viewText"; });

  // 스크롤 맨 위로
  sourcePreview.scrollTop = 0;
  targetPreview.scrollTop = 0;
}

// ── 이력 ──────────────────────────────────────────────────────────────
refreshHistory.addEventListener("click", () => {
  resetWorkspace();
  loadHistory();
});

// ── 문서 미리보기 렌더링 ──────────────────────────────────────────────
function renderDocPreview(jobId, job) {
  if (!job) return;

  const fileType = (job.fileType || "").toLowerCase();
  docSourceMeta.textContent = `${fileType.toUpperCase()} · ${job.sourceLanguage || "unknown"}`;
  docTargetMeta.textContent = `${job.targetLanguage} · ${providerLabel(job.aiProvider)}`;

  // ── 원본 문서 (왼쪽) ──
  docSourceContainer.innerHTML = "";
  if (fileType === "pdf") {
    const iframe = document.createElement("iframe");
    iframe.src   = `/api/jobs/${jobId}/original`;
    iframe.title = "원본 PDF 미리보기";
    iframe.className = "doc-iframe";
    docSourceContainer.appendChild(iframe);
  } else if (["txt", "md"].includes(fileType)) {
    // 텍스트 기반: 원문 블록을 그대로 pre 태그로 표시
    const pre = document.createElement("pre");
    pre.className = "doc-text-preview";
    pre.textContent = currentBlocks.map((b) => b.sourceText).join("\n\n");
    docSourceContainer.appendChild(pre);
  } else {
    // DOCX / XLSX 등 — 브라우저 내 임베드 불가, 원문 텍스트만 표시
    const notice = document.createElement("div");
    notice.className = "doc-unsupported";
    notice.innerHTML = `
      <span class="doc-unsupported-icon">📁</span>
      <p><strong>${fileType.toUpperCase()}</strong> 형식은 브라우저 내 미리보기가 지원되지 않습니다.</p>
      <p class="doc-unsupported-sub">아래에 원문 텍스트를 표시합니다.</p>
    `;
    const pre = document.createElement("pre");
    pre.className = "doc-text-preview";
    pre.textContent = currentBlocks.map((b) => b.sourceText).join("\n\n");
    docSourceContainer.appendChild(notice);
    docSourceContainer.appendChild(pre);
  }

  // ── 번역 문서 (오른쪽) ──
  docTargetContainer.innerHTML = "";

  if (job.status === "completed" && job.exportedPath && job.outputFormat === "pdf") {
    // 내보낸 PDF가 있으면 inline 서빙 엔드포인트로 iframe 미리보기
    const iframe = document.createElement("iframe");
    iframe.src   = `/api/jobs/${jobId}/export-preview`;
    iframe.title = "번역된 PDF 미리보기";
    iframe.className = "doc-iframe";
    docTargetContainer.appendChild(iframe);
  } else {
    // 번역 블록을 스타일된 HTML 문서로 렌더링
    const doc = buildTranslatedDocHTML(job);
    const iframe = document.createElement("iframe");
    iframe.className = "doc-iframe";
    iframe.title = "번역 미리보기";
    docTargetContainer.appendChild(iframe);
    // srcdoc 사용 (동일 출처 iframe)
    iframe.srcdoc = doc;
  }
}

function buildTranslatedDocHTML(job) {
  const pageGroups = {};
  currentBlocks.forEach((b) => {
    const page = b.pageNumber ?? (b.sheetName || "1");
    if (!pageGroups[page]) pageGroups[page] = [];
    pageGroups[page].push(b);
  });

  const pages = Object.keys(pageGroups);
  const pagesHTML = pages.map((page) => {
    const blocksHTML = pageGroups[page]
      .map((b) => {
        const text = (b.translatedText || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        const tag  = b.type === "heading" ? "h2" : "p";
        const cls  = b.type === "heading" ? "doc-heading" : "doc-para";
        return `<${tag} class="${cls}">${text}</${tag}>`;
      })
      .join("\n");
    const pageLabel = typeof page === "number" || !isNaN(Number(page))
      ? `Page ${page}`
      : page;
    return `<section class="doc-page"><div class="page-label">${pageLabel}</div>${blocksHTML}</section>`;
  }).join("\n");

  const langMap = { ko: "한국어", ja: "일본어", en: "English", zh: "中文", vi: "Tiếng Việt" };
  const langName = langMap[job.targetLanguage] || job.targetLanguage;

  return `<!doctype html>
<html lang="${job.targetLanguage}">
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", sans-serif;
         background: #f0f2f4; color: #1d252c; padding: 20px; }
  .doc-header { background: #146c63; color: #fff; border-radius: 8px;
                padding: 14px 20px; margin-bottom: 18px; font-size: 14px; }
  .doc-header strong { font-size: 16px; display: block; margin-bottom: 4px; }
  .doc-page { background: #fff; border-radius: 8px; padding: 32px 36px;
              margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08);
              min-height: 200px; }
  .page-label { font-size: 11px; color: #8fa5b1; text-transform: uppercase;
                letter-spacing: .06em; margin-bottom: 18px; padding-bottom: 8px;
                border-bottom: 1px solid #e8edf0; }
  .doc-heading { font-size: 18px; font-weight: 700; margin-bottom: 14px; line-height: 1.4; }
  .doc-para { font-size: 14px; line-height: 1.7; margin-bottom: 12px; white-space: pre-wrap; }
</style>
</head>
<body>
<div class="doc-header">
  <strong>번역 미리보기</strong>
  ${job.originalFileName} → ${langName}
</div>
${pagesHTML}
</body>
</html>`;
}

// ── Providers 로드 ─────────────────────────────────────────────────────
async function loadProviders() {
  try {
    const response = await fetch("/api/providers");
    const payload  = await response.json();
    if (!response.ok) throw new Error(payload.error || "AI provider 로드 실패");
    aiProviderSelect.innerHTML = "";
    for (const provider of payload.providers) {
      const option       = document.createElement("option");
      option.value       = provider.id;
      option.textContent = `${provider.label}${provider.id === "demo" ? " (개발용)" : ""}`;
      option.title       = provider.reason;
      aiProviderSelect.appendChild(option);
    }
    const preferred = payload.providers.find((p) => p.id !== "demo") || payload.providers[0];
    if (preferred) aiProviderSelect.value = preferred.id;
  } catch (error) {
    aiProviderSelect.innerHTML = '<option value="demo">Demo</option>';
    setStatus(error.message, true);
  }
}

// ── 미리보기 로드 ─────────────────────────────────────────────────────
async function loadPreview(jobId) {
  const response = await fetch(`/api/jobs/${jobId}/preview`);
  const payload  = await response.json();
  if (!response.ok) throw new Error(payload.error || "미리보기 로드 실패");

  renderPreview(payload);
  currentJobId   = jobId;
  currentJobData = payload.job;

  if (["preview_ready", "verified", "completed"].includes(payload.job.status)) {
    exportButton.disabled = false;
    setStatus(
      `미리보기 준비 완료: ${payload.job.sourceLanguage || "unknown"} → ${payload.job.targetLanguage} · ${providerLabel(payload.job.aiProvider)}`
    );
    if (payload.job.status === "completed" && payload.job.exportedPath) {
      downloadLink.href = `/api/jobs/${payload.job.id}/download`;
      downloadLink.classList.remove("disabled");
      downloadHint.textContent = `${payload.job.outputFormat.toUpperCase()} 파일을 내려받을 수 있습니다.`;
    } else {
      downloadLink.href = "#";
      downloadLink.classList.add("disabled");
      downloadHint.textContent = "미리보기 확인 후 문서를 생성하세요.";
    }
  } else if (payload.job.status === "failed") {
    setStatus(payload.job.errorMessage || "번역 실패", true);
  } else {
    setStatus(`현재 상태: ${payload.job.status}`);
  }

  // 문서 뷰가 활성화 상태라면 바로 렌더링
  if (!document.querySelector("#viewDoc").hidden) {
    renderDocPreview(jobId, payload.job);
  }
}

// ── 미리보기 렌더링 ───────────────────────────────────────────────────
function renderPreview(payload) {
  const { job, blocks } = payload;

  if (editMode) exitEditMode(false);

  currentBlocks = blocks.map((b) => ({ ...b }));

  sourcePreview.classList.remove("empty");
  targetPreview.classList.remove("empty");
  sourceMeta.textContent = `${job.fileType.toUpperCase()} · ${job.sourceLanguage || "unknown"}`;
  targetMeta.textContent = `${job.targetLanguage} · ${providerLabel(job.aiProvider)}`;

  sourcePreview.innerHTML = "";
  targetPreview.innerHTML = "";

  if (!blocks.length) {
    sourcePreview.classList.add("empty");
    targetPreview.classList.add("empty");
    sourcePreview.textContent = "추출된 원문이 없습니다.";
    targetPreview.textContent = "번역 결과가 없습니다.";
    editToggle.hidden = true;
    return;
  }

  blocks.forEach((block, idx) => {
    sourcePreview.appendChild(blockElement(block.sourceText, idx));
    targetPreview.appendChild(blockElement(block.translatedText || "", idx));
  });

  if (["preview_ready", "verified", "completed"].includes(job.status)) {
    editToggle.hidden = false;
  }

  attachBlockClickHandlers();
}

function blockElement(text, idx) {
  const div         = document.createElement("div");
  div.className     = "block";
  div.dataset.idx   = idx;
  div.textContent   = text;
  return div;
}

// ── 이력 ──────────────────────────────────────────────────────────────
async function loadHistory() {
  const response = await fetch("/api/history");
  const payload  = await response.json();
  historyList.innerHTML = "";
  if (!payload.jobs.length) {
    const empty       = document.createElement("p");
    empty.className   = "history-meta";
    empty.textContent = "아직 번역 이력이 없습니다.";
    historyList.appendChild(empty);
    return;
  }
  for (const job of payload.jobs) {
    const item = document.createElement("button");
    item.className = "history-item";
    item.innerHTML = `
      <div class="history-title"></div>
      <div class="history-meta">${job.fileType.toUpperCase()} · ${job.sourceLanguage || "unknown"} → ${job.targetLanguage} · ${providerLabel(job.aiProvider)}</div>
      <span class="badge">${job.status}</span>
    `;
    item.querySelector(".history-title").textContent = job.originalFileName;
    item.addEventListener("click", () => loadPreview(job.id));
    historyList.appendChild(item);
  }
}

// ── 유틸 ──────────────────────────────────────────────────────────────
function setStatus(message, isError = false) {
  statusText.textContent = message;
  statusRow.classList.toggle("error", isError);
}

function providerLabel(providerId) {
  return PROVIDER_LABELS[providerId] || providerId || "AI";
}

// ── 인증 연동 ─────────────────────────────────────────────────────────
async function initAuth() {
  const res = await fetch("/api/auth/me");
  if (!res.ok) { location.replace("/static/auth.html"); return; }
  const { user } = await res.json();
  window.__currentUser = user;
  if (user.role === "admin") {
    document.getElementById("adminLink").hidden = false;
  }
}

document.getElementById("logoutBtn").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  location.href = "/static/auth.html";
});

// 401 응답 → 로그인 페이지
const _origFetch = window.fetch;
window.fetch = async function(...args) {
  const res = await _origFetch(...args);
  if (res.status === 401 && !String(args[0]).includes("/api/auth/")) {
    location.replace("/static/auth.html");
  }
  return res;
};

// ── 초기화 ────────────────────────────────────────────────────────────
initAuth();
loadProviders();
loadHistory();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js").catch(() => {});
}
