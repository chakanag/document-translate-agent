FROM python:3.12-slim

WORKDIR /app

# 한글 폰트 + fontconfig + antiword + Tesseract OCR (영/일/중/한 언어팩)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-nanum \
    fontconfig \
    antiword \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-jpn \
    tesseract-ocr-jpn-vert \
    tesseract-ocr-chi-sim \
    tesseract-ocr-chi-tra \
    tesseract-ocr-kor \
 && fc-cache -fv \
 && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 복사 (레이어 캐시 활용)
COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir -r requirements-optional.txt

COPY . .

# 스토리지 디렉토리 생성
RUN mkdir -p storage/originals storage/blocks storage/exports

EXPOSE 8010

# --proxy-headers: nginx가 전달하는 X-Forwarded-* 헤더 신뢰
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8010", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
