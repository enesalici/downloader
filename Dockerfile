FROM python:3.12-slim

# ffmpeg: YouTube'un ayrı gelen görüntü + ses dosyalarını birleştirmek için
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Deno: yt-dlp'nin YouTube için ihtiyaç duyduğu JavaScript çalıştırıcısı
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PORT=8000
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

CMD ["sh", "/app/entrypoint.sh"]
