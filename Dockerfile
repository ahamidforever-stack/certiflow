# CertiFlow: one image for the web API and the workers.
# Stage 1 builds the React frontend; stage 2 is the Python runtime with LibreOffice, Poppler, Tesseract and fonts.
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
# optional extra CA (only for builds behind an inspecting proxy): docker build --secret id=ca,src=ca.crt ...
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    CERTIFLOW_DATA_DIR=/data CERTIFLOW_STATIC_DIR=/app/web/dist PATH=/opt/venv/bin:$PATH
# the optional "ca" build secret is only for builds behind an inspecting HTTPS proxy
RUN --mount=type=secret,id=ca,required=false \
    CA=""; if [ -f /run/secrets/ca ]; then \
      cp /run/secrets/ca /tmp/build-ca.crt && chmod 644 /tmp/build-ca.crt; \
      sed -i 's|http://|https://|g' /etc/apt/sources.list.d/*.sources; CA="-o Acquire::https::CAInfo=/tmp/build-ca.crt"; fi; \
    apt-get $CA update && apt-get $CA install -y --no-install-recommends \
      python3 python3-venv ca-certificates \
      libreoffice-writer-nogui poppler-utils fontconfig \
      tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-deu tesseract-ocr-spa \
      tesseract-ocr-ita tesseract-ocr-por tesseract-ocr-nld tesseract-ocr-tur tesseract-ocr-rus tesseract-ocr-fas \
      tesseract-ocr-urd tesseract-ocr-heb tesseract-ocr-chi-sim tesseract-ocr-jpn tesseract-ocr-kor tesseract-ocr-hin \
      fonts-liberation fonts-hosny-amiri fonts-noto-core fonts-noto-cjk postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/* /tmp/build-ca.crt && sed -i 's|https://|http://|g' /etc/apt/sources.list.d/*.sources \
    && python3 -m venv /opt/venv
RUN useradd --create-home --uid 10001 certiflow
WORKDIR /app
COPY pyproject.toml ./
COPY certiflow ./certiflow
COPY config ./config
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; pip install --no-cache-dir ".[web]"
COPY --from=web /web/dist ./web/dist
# licensed office fonts (e.g. Sakkal Majalla) are mounted at /fonts and installed at start
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /data && chown certiflow /data
USER certiflow
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["web"]
