# Document Translate Agent

문서를 업로드하면 원문을 분석하고, 사용자가 선택한 최종 번역 언어로 번역한 뒤, 미리보기와 다운로드, 이력 관리를 제공하는 AI 기반 문서 번역 에이전트 프로젝트입니다.

## 핵심 요건

1. 최종 번역 언어 선택
2. 번역 대상 문서 종류 지원: PDF, DOC/DOCX, TXT, MD, XLS/XLSX
3. 업로드 문서의 언어를 감지하고 최종 번역 언어로 번역
4. 원본 문서 업로드 후 원문/번역 미리보기 제공
5. 번역 완료 문서를 원하는 형식으로 다운로드
6. 번역 작업 이력 관리

## Agent 구성

에이전트 구성은 [agents/document-translation-agents.yaml](/Users/chakanag/DEV/00_repository/Document-translate-agent/agents/document-translation-agents.yaml)에 정의되어 있습니다.

상세 설계는 [docs/agent-blueprint.md](/Users/chakanag/DEV/00_repository/Document-translate-agent/docs/agent-blueprint.md)를 기준으로 진행합니다.

## 구현 로드맵

작업 백로그와 인수 기준은 [docs/implementation-backlog.md](/Users/chakanag/DEV/00_repository/Document-translate-agent/docs/implementation-backlog.md)에 정리되어 있습니다.

## 현재 MVP

현재 구현된 기능:

- TXT/MD 업로드
- 최종 번역 언어 선택
- 원문 언어 감지
- 원문/번역 미리보기
- TXT/MD 다운로드
- 번역 이력 관리
- PyMuPDF 설치 시 PDF text span 추출 및 layout-preserving PDF overlay export 경로

화면의 AI 선택기는 서버에서 사용 가능한 provider만 보여줍니다. OpenAI, Gemini, Anthropic은 API key가 등록되어 있을 때 선택 가능하고, Ollama는 로컬 서버가 응답할 때 선택 가능합니다. 기본 번역 provider는 로컬 개발용 `demo`입니다.

AI provider 설정은 프로젝트 내부 파일에서 관리합니다.

```json
{
  "openai": {
    "api_key": "",
    "model": "gpt-4o-mini"
  },
  "gemini": {
    "api_key": "",
    "model": "gemini-1.5-flash"
  },
  "anthropic": {
    "api_key": "",
    "model": "claude-3-5-haiku-latest"
  },
  "ollama": {
    "base_url": "http://127.0.0.1:11434",
    "model": "qwen3.6:27b-coding-mxfp8",
    "generate_timeout_seconds": null
  }
}
```

실제 설정 파일은 `config/providers.local.json`입니다. 예시는 `config/providers.example.json`에 있습니다. `providers.local.json`은 API key가 들어갈 수 있으므로 `.gitignore`에 포함되어 있습니다.

Ollama 번역 생성은 `generate_timeout_seconds`가 `null`이면 timeout 없이 기다립니다. 운영상 제한이 필요할 때만 초 단위 숫자를 넣습니다.

## 실행

```bash
./scripts/bootstrap_venv.sh
./scripts/run_dev.sh
```

브라우저에서 `http://127.0.0.1:8010`을 엽니다.

## 테스트

```bash
./scripts/test.sh
```

## PDF 레이아웃 보존

PDF에서 원본 이미지, 차트, 테이블 선, 배경을 유지하고 텍스트만 바꾸려면 PyMuPDF가 필요합니다.

```bash
./scripts/install_optional.sh
```

상세 전략은 [docs/pdf-layout-preserving-strategy.md](/Users/chakanag/DEV/00_repository/Document-translate-agent/docs/pdf-layout-preserving-strategy.md)를 참고하세요.
