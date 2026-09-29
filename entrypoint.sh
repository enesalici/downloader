#!/bin/sh
# Instagram / TikTok / YouTube sık sık değişir; her açılışta yt-dlp'yi en yeni sürüme güncelle.
pip install --no-cache-dir --quiet --upgrade "yt-dlp[default]" || echo "yt-dlp güncellenemedi, mevcut sürümle devam ediliyor"

# Tek işlem (indirme durumları bellekte tutulur), çok iş parçacığı.
exec gunicorn app:app \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers 1 \
    --threads 16 \
    --timeout 300 \
    --access-logfile -
