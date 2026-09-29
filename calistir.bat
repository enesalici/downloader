@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Video İndir
rem Windows'ta 8000 portu çoğu zaman sistem tarafından kullanılıyor, bu yüzden 8765.
if not defined PORT set PORT=8765

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo .env dosyası oluşturuldu. Not Defteri'nde açıp APP_PASSWORD satırına şifreyi yazın, sonra bunu tekrar çalıştırın.
    notepad ".env"
    pause
    exit /b
)

if not exist ".venv\Scripts\python.exe" (
    echo İlk kurulum yapılıyor, bir dakika sürebilir...
    python -m venv .venv || goto :hata
)

echo Paketler kontrol ediliyor / güncelleniyor...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check --upgrade -r requirements.txt || goto :hata

where ffmpeg >nul 2>nul || echo UYARI: ffmpeg bulunamadı. YouTube videoları sessiz ya da düşük kaliteli inebilir. Kurmak için: winget install ffmpeg

".venv\Scripts\python.exe" app.py
pause
exit /b

:hata
echo.
echo Bir hata oldu. Python kurulu mu? (python.org'dan kurarken "Add to PATH" işaretlenmeli)
pause
