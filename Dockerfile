# umppa-monitor 웹 대시보드 + 감시 루프 (Render / Koyeb / Fly / 자체 서버용)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=Asia/Seoul \
    PORT=8000

WORKDIR /app
COPY pyproject.toml README.md ./
COPY umppa_monitor ./umppa_monitor
RUN pip install --no-cache-dir -e ".[web]" \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY config.example.yaml ./config.example.yaml
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /data

VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=10s --retries=3 CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/healthz'%os.environ.get('PORT','8000'))" || exit 1
ENTRYPOINT ["/entrypoint.sh"]
