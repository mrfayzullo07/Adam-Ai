# Adam backend — FastAPI + aiogram + Gemini Live
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10001 adam && chown -R adam /app
USER adam

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4)"

# Bitta worker: WebSocket sessiyalar uzoq yashaydi; masshtab — instance soni orqali (Redis lock umumiy).
# ws-ping: proxy (Railway/Render/Fly) bo'sh ulanishni uzib qo'ymasligi uchun.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --ws-ping-interval 20 --ws-ping-timeout 30 --timeout-keep-alive 75 --ws-max-size 1048576"]
