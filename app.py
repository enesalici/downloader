"""Video İndir — Instagram, TikTok ve YouTube videolarını telefona indiren küçük web uygulaması."""

import hashlib
import hmac
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = Path(__file__).resolve().parent

# Docker'sız çalıştırmada .env dosyasını oku (Docker'da değişkenleri compose verir).
if (BASE_DIR / ".env").is_file():
    for _line in (BASE_DIR / ".env").read_text(encoding="utf-8").splitlines():
        _key, _sep, _value = _line.strip().partition("=")
        if _sep and _key and not _key.startswith("#"):
            os.environ.setdefault(_key.strip(), _value.strip().strip("\"'"))

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DOWNLOAD_DIR = DATA_DIR / "downloads"
THUMB_DIR = DATA_DIR / "thumbs"
COOKIES_DIR = DATA_DIR / "cookies"
DB_PATH = DATA_DIR / "videos.db"
for _d in (DOWNLOAD_DIR, THUMB_DIR, COOKIES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

APP_USER = os.environ.get("APP_USER", "vermilia")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
if not APP_PASSWORD or APP_PASSWORD == "buraya-sifreyi-yazin":
    raise SystemExit("APP_PASSWORD ayarlanmamış: .env dosyasına APP_PASSWORD=... satırını yazın.")
# İndirilen video dosyası sunucuda bu kadar süre tutulur, sonra silinir (link geçmişi kalıcıdır).
FILE_TTL = int(os.environ.get("FILE_TTL_MINUTES", "60")) * 60
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL_DOWNLOADS", "2"))
MAX_HEIGHT = int(os.environ.get("MAX_HEIGHT", "1080"))

PLATFORMS = {
    "instagram": ("instagram.com", "instagr.am"),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be", "youtube-nocookie.com"),
}

VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".image"}  # TikTok küçük resmi ".image" uzantılı gelir

# Kullanıcı adı/şifre değişirse eski oturumlar geçersiz olsun diye oturuma yazılır.
CRED_VERSION = hashlib.sha256(f"{APP_USER}\0{APP_PASSWORD}".encode()).hexdigest()[:16]


def _secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    # Anahtar diske yazılır; böylece sunucu yeniden başlasa da oturum açık kalır.
    path = DATA_DIR / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()


app = Flask(__name__)
app.secret_key = _secret_key()
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(days=3650),
    SESSION_REFRESH_EACH_REQUEST=True,
    SESSION_COOKIE_NAME="vi_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
)
if os.environ.get("TRUST_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# --------------------------------------------------------------------------- veritabanı

def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(db()) as conn, conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                platform   TEXT    NOT NULL,
                url        TEXT    NOT NULL UNIQUE,
                title      TEXT,
                uploader   TEXT,
                duration   INTEGER,
                thumb      TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS videos_platform ON videos(platform, created_at)")


def save_history(platform, url, title, uploader, duration, thumb):
    with closing(db()) as conn, conn:
        old = conn.execute("SELECT thumb FROM videos WHERE url = ?", (url,)).fetchone()
        conn.execute(
            """
            INSERT INTO videos (platform, url, title, uploader, duration, thumb, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                uploader = excluded.uploader,
                duration = excluded.duration,
                thumb = COALESCE(excluded.thumb, videos.thumb),
                created_at = excluded.created_at
            """,
            (platform, url, title, uploader, duration, thumb, int(time.time())),
        )
    if old and old["thumb"] and thumb and old["thumb"] != thumb:
        (THUMB_DIR / old["thumb"]).unlink(missing_ok=True)


def video_row(row):
    return {
        "id": row["id"],
        "platform": row["platform"],
        "url": row["url"],
        "title": row["title"],
        "uploader": row["uploader"],
        "duration": row["duration"],
        "thumb": url_for("thumb", name=row["thumb"]) if row["thumb"] else None,
        "created_at": row["created_at"],
    }


# --------------------------------------------------------------------------- yardımcılar

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
BARE_URL_RE = re.compile(
    r"(?:www\.|m\.|vm\.|vt\.)?(?:instagram\.com|instagr\.am|tiktok\.com|youtube\.com|youtu\.be)/[^\s<>\"']+",
    re.I,
)


def extract_url(text):
    """Paylaşım metninin içinden ilk linki bulur (Instagram/TikTok bazen linke yazı ekler)."""
    text = (text or "").strip()
    match = URL_RE.search(text)
    if match:
        url = match.group(0)
    else:
        match = BARE_URL_RE.search(text)
        if not match:
            return None
        url = "https://" + match.group(0)
    return url.rstrip(".,;:!?)]}»”’")


def detect_platform(url):
    host = (urlparse(url).hostname or "").lower()
    for name, domains in PLATFORMS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return name
    return None


def safe_filename(title, fallback):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", title or "")
    name = re.sub(r"\s+", " ", name).strip(" .")[:70].strip()
    return name or fallback


def display_title(platform, info):
    title = (info.get("title") or "").strip()
    description = (info.get("description") or "").strip()
    # Instagram başlığı "Video by kullanıcı" gibi anlamsız olur; açıklamanın ilk satırı daha iyi.
    if platform == "instagram" and description:
        title = description.splitlines()[0]
    if len(title) > 140:
        title = title[:137].rstrip() + "…"
    return title or "Video"


def friendly_error(message):
    m = message.lower()
    if "sign in to confirm" in m or "not a bot" in m:
        return "YouTube bu videoyu şu an vermiyor. Biraz sonra tekrar deneyin."
    if "empty media response" in m or "--cookies" in m:
        return "Bu video şu an alınamadı. Gizli olabilir ya da site geçici olarak engelliyor; biraz sonra tekrar deneyin."
    if "private" in m or "login required" in m or "log in" in m or "requested content is not available" in m:
        return "Bu video gizli ya da görmek için giriş gerekiyor."
    if "unsupported url" in m:
        return "Bu link desteklenmiyor. Videonun kendi linkini kopyaladığınızdan emin olun."
    if "no video" in m or "there is no video" in m:
        return "Bu gönderide video bulunamadı."
    if "larger than max-filesize" in m:
        return "Video çok büyük, indirilemiyor."
    if "unavailable" in m or "removed" in m or "not available" in m or "404" in m:
        return "Video kaldırılmış ya da artık erişilemiyor."
    if "timed out" in m or "connection" in m:
        return "Bağlantı sorunu oldu. Lütfen tekrar deneyin."
    return "Video indirilemedi. Linki kontrol edip tekrar deneyin."


# --------------------------------------------------------------------------- oturum

_login_fails = {}
_login_lock = threading.Lock()
MAX_FAILS = 10
LOCK_SECONDS = 10 * 60


def logged_in():
    return session.get("user") == APP_USER and session.get("v") == CRED_VERSION


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not logged_in():
            if request.path.startswith("/api/"):
                return jsonify(error="Oturum kapandı, lütfen tekrar giriş yapın."), 401
            nxt = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=nxt))
        return view(*args, **kwargs)

    return wrapper


def _safe_next(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("index")


@app.route("/login", methods=["GET", "POST"])
def login():
    if logged_in():
        return redirect(_safe_next(request.args.get("next")))

    error = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        now = time.time()
        with _login_lock:
            count, since = _login_fails.get(ip, (0, now))
            if now - since > LOCK_SECONDS:
                count, since = 0, now
        if count >= MAX_FAILS:
            error = "Çok fazla hatalı deneme. Lütfen 10 dakika sonra tekrar deneyin."
        else:
            user = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            ok_user = hmac.compare_digest(user.lower().encode(), APP_USER.lower().encode())
            ok_pass = hmac.compare_digest(password.encode(), APP_PASSWORD.encode())
            if ok_user and ok_pass:
                with _login_lock:
                    _login_fails.pop(ip, None)
                session.clear()
                session.permanent = True
                session["user"] = APP_USER
                session["v"] = CRED_VERSION
                return redirect(_safe_next(request.args.get("next")))
            with _login_lock:
                _login_fails[ip] = (count + 1, since)
            time.sleep(0.5)
            error = "Kullanıcı adı ya da şifre yanlış."
    return render_template("login.html", error=error), (401 if error else 200)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------- indirme işleri

jobs = {}
jobs_lock = threading.Lock()
slots = threading.Semaphore(MAX_PARALLEL)


def public_job(job):
    return {
        "id": job["id"],
        "platform": job["platform"],
        "url": job["url"],
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
        "detail": job.get("detail"),
        "title": job.get("title"),
        "file_url": url_for("api_file", job_id=job["id"]) if job["status"] == "done" else None,
    }


def new_job(url, platform):
    job = {
        "id": uuid.uuid4().hex,
        "url": url,
        "platform": platform,
        "status": "queued",
        "progress": 0,
        "message": "Sırada bekliyor…",
        "created": time.time(),
        "finished": None,
    }
    with jobs_lock:
        jobs[job["id"]] = job
    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    return job


def ydl_options(job, out_dir):
    def on_progress(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                pct = min(99, int((d.get("downloaded_bytes") or 0) * 100 / total))
                # YouTube'da görüntü ve ses ayrı iner; çubuk geri gitmesin diye sadece ileri alınır.
                job["progress"] = max(job["progress"], pct)
            job["message"] = "İndiriliyor…"
        elif d["status"] == "finished":
            job["message"] = "Hazırlanıyor…"

    def on_postprocess(d):
        if d["status"] == "started":
            job["message"] = "Video hazırlanıyor…"

    h = MAX_HEIGHT
    h264 = "[vcodec~='^(avc|h264)']"
    # Önce her telefonda sorunsuz oynayan H.264 MP4, olmazsa en iyi mevcut biçim.
    fmt = "/".join(
        [
            f"bv[height<=?{h}]{h264}+ba[ext=m4a]",
            f"b[height<=?{h}]{h264}",
            f"bv[height<=?{h}]+ba",
            f"b[height<=?{h}]",
            "bv+ba",
            "b",
        ]
    )
    opts = {
        "format": fmt,
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "playlist_items": "1",
        "writethumbnail": True,
        "restrictfilenames": True,
        "overwrites": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 4,
        "max_filesize": 3 * 1024**3,
        # YouTube için JavaScript çalıştırıcısı gerekir; Docker imajında deno var, yoksa node denenir.
        "js_runtimes": {"deno": {}, "node": {}},
        "progress_hooks": [on_progress],
        "postprocessor_hooks": [on_postprocess],
    }
    cookie_file = COOKIES_DIR / f"{job['platform']}.txt"
    if cookie_file.exists():
        opts["cookiefile"] = str(cookie_file)
    return opts


def pick_file(folder, exts):
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]
    return max(files, key=lambda p: p.stat().st_size) if files else None


def image_ext(path):
    head = path.read_bytes()[:12]
    if head.startswith(b"\xff\xd8"):
        return ".jpg"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


def run_job(job):
    out_dir = DOWNLOAD_DIR / job["id"]
    with slots:
        job.update(status="downloading", message="Video bilgileri alınıyor…")
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            with yt_dlp.YoutubeDL(ydl_options(job, out_dir)) as ydl:
                info = ydl.extract_info(job["url"], download=True)
            if info.get("_type") == "playlist":
                entries = [e for e in (info.get("entries") or []) if e]
                if not entries:
                    raise yt_dlp.utils.DownloadError("There is no video in this post")
                info = entries[0]

            video = None
            for dl in info.get("requested_downloads") or []:
                path = Path(dl.get("filepath") or "")
                if path.is_file():
                    video = path
                    break
            video = video or pick_file(out_dir, VIDEO_EXTS)
            if not video:
                raise yt_dlp.utils.DownloadError("No video formats found")

            thumb_name = None
            thumb = pick_file(out_dir, IMAGE_EXTS)
            ext = image_ext(thumb) if thumb else None
            if ext:
                thumb_name = uuid.uuid4().hex + ext
                shutil.move(str(thumb), THUMB_DIR / thumb_name)

            platform = job["platform"]
            title = display_title(platform, info)
            save_history(
                platform,
                info.get("webpage_url") or job["url"],
                title,
                info.get("uploader") or info.get("channel") or info.get("uploader_id"),
                int(info["duration"]) if info.get("duration") else None,
                thumb_name,
            )
            job.update(
                status="done",
                progress=100,
                message="Video hazır!",
                title=title,
                file=str(video),
                filename=safe_filename(title, f"{platform}-video") + video.suffix.lower(),
            )
        except yt_dlp.utils.DownloadError as exc:
            raw = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
            job.update(status="error", message=friendly_error(raw), detail=raw[:600])
            shutil.rmtree(out_dir, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            app.logger.exception("İndirme hatası: %s", job["url"])
            job.update(
                status="error",
                message="Beklenmeyen bir hata oldu. Lütfen tekrar deneyin.",
                detail=str(exc)[:600],
            )
            shutil.rmtree(out_dir, ignore_errors=True)
        finally:
            job["finished"] = time.time()


def cleanup_loop():
    # Yeniden başlatmadan kalan yarım dosyaları temizle.
    for path in DOWNLOAD_DIR.iterdir():
        shutil.rmtree(path, ignore_errors=True)
    while True:
        time.sleep(300)
        cutoff = time.time() - FILE_TTL
        with jobs_lock:
            expired = [j for j in jobs.values() if j["finished"] and j["finished"] < cutoff]
            for job in expired:
                jobs.pop(job["id"], None)
            live = set(jobs)
        for path in DOWNLOAD_DIR.iterdir():
            if path.name not in live:
                shutil.rmtree(path, ignore_errors=True)


# --------------------------------------------------------------------------- sayfalar ve API

@app.get("/")
@login_required
def index():
    return render_template("index.html", initial_url=request.args.get("url", ""))


@app.get("/share")
@login_required
def share():
    """Android'deki 'Paylaş' menüsünden gelen linki karşılar (PWA share target)."""
    text = " ".join(request.args.get(k, "") for k in ("url", "text", "title"))
    url = extract_url(text)
    return redirect(url_for("index", url=url) if url else url_for("index"))


@app.post("/api/download")
@login_required
def api_download():
    if not request.is_json:
        abort(415)
    url = extract_url((request.get_json(silent=True) or {}).get("url", ""))
    if not url:
        return jsonify(error="Link bulunamadı. Lütfen videonun linkini yapıştırın."), 400
    platform = detect_platform(url)
    if not platform:
        return jsonify(error="Sadece Instagram, TikTok ve YouTube linkleri destekleniyor."), 400
    return jsonify(public_job(new_job(url, platform)))


@app.get("/api/job/<job_id>")
@login_required
def api_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify(error="İndirme bulunamadı."), 404
    return jsonify(public_job(job))


@app.get("/api/file/<job_id>")
@login_required
def api_file(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done" or not Path(job["file"]).is_file():
        return render_template("expired.html"), 404
    return send_file(
        job["file"],
        as_attachment=True,
        download_name=job["filename"],
        mimetype="video/mp4" if job["file"].endswith(".mp4") else None,
    )


@app.get("/api/history")
@login_required
def api_history():
    with closing(db()) as conn:
        rows = conn.execute("SELECT * FROM videos ORDER BY created_at DESC, id DESC").fetchall()
    grouped = {name: [] for name in PLATFORMS}
    for row in rows:
        grouped.setdefault(row["platform"], []).append(video_row(row))
    return jsonify(grouped)


@app.delete("/api/history/<int:video_id>")
@login_required
def api_history_delete(video_id):
    with closing(db()) as conn, conn:
        row = conn.execute("SELECT thumb FROM videos WHERE id = ?", (video_id,)).fetchone()
        if not row:
            return jsonify(error="Kayıt bulunamadı."), 404
        conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    if row["thumb"]:
        (THUMB_DIR / row["thumb"]).unlink(missing_ok=True)
    return jsonify(ok=True)


@app.get("/thumb/<name>")
@login_required
def thumb(name):
    return send_from_directory(THUMB_DIR, name, max_age=60 * 60 * 24 * 30)


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(
        app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json", max_age=3600
    )


@app.get("/sw.js")
def service_worker():
    resp = send_from_directory(app.static_folder, "sw.js", mimetype="text/javascript", max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/healthz")
def healthz():
    return "ok"


init_db()
threading.Thread(target=cleanup_loop, daemon=True).start()


def _lan_ip():
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "BILGISAYAR_IP"


if __name__ == "__main__":
    port = int(os.environ.get("PORT") or os.environ.get("APP_PORT") or "8000")
    print(
        f"\n  Bilgisayarda aç : http://localhost:{port}"
        f"\n  Telefonda aç    : http://{_lan_ip()}:{port}   (telefon aynı Wi-Fi'de olmalı)"
        f"\n  Kapatmak için bu pencereyi kapatın ya da Ctrl+C'ye basın.\n",
        flush=True,
    )
    app.run(host="0.0.0.0", port=port, threaded=True)
