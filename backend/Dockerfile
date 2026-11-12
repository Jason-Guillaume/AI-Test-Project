FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .
COPY docker-entrypoint.sh /usr/local/bin/testplatform-entrypoint
RUN chmod +x /usr/local/bin/testplatform-entrypoint

EXPOSE 8001
ENTRYPOINT ["/usr/local/bin/testplatform-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
