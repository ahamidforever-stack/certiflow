# CertiFlow: one image for the web API and the workers.
# Stage 1 builds the React frontend; stage 2 is the Python runtime with LibreOffice, Poppler, Tesseract and fonts.
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    CERTIFLOW_DATA_DIR=/data CERTIFLOW_STATIC_DIR=/app/web/dist
RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-writer-nogui poppler-utils fontconfig \
      tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-deu tesseract-ocr-spa \
      tesseract-ocr-ita tesseract-ocr-por tesseract-ocr-nld tesseract-ocr-tur tesseract-ocr-rus tesseract-ocr-fas \
      tesseract-ocr-urd tesseract-ocr-heb tesseract-ocr-chi-sim tesseract-ocr-jpn tesseract-ocr-kor tesseract-ocr-hin \
      fonts-liberation fonts-hosny-amiri fonts-noto-core fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 certiflow
WORKDIR /app
COPY pyproject.toml ./
COPY certiflow ./certiflow
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir ".[web]"
COPY --from=web /web/dist ./web/dist
# licensed office fonts (e.g. Sakkal Majalla) are mounted at /fonts and installed at start
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /data && chown certiflow /data
USER certiflow
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["web"]
