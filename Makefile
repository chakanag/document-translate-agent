.PHONY: venv dev serve test optional

venv:
	./scripts/bootstrap_venv.sh

dev:
	./scripts/run_dev.sh

serve:  ## LAN 접근 서버 — 모바일/외부 접속용 (AUTH_USER, AUTH_PASS 환경변수 권장)
	HOST=0.0.0.0 ./scripts/serve.sh

test:
	./scripts/test.sh

optional:
	./scripts/install_optional.sh
