# Video İndir

Instagram, TikTok ve YouTube videolarını Android telefona indiren küçük web uygulaması.

- Tek kullanıcı; kullanıcı adı ve şifre `.env` dosyasında belirlenir (repoya gitmez)
- Bir kere giriş yapılır, oturum o telefonda **hep açık kalır** (her açılışta kendini yeniler)
- İndirilen her videonun linki **Instagram Videoları / TikTok Videoları / YouTube Videoları** bölümlerinde kalıcı olarak saklanır
- Ana ekrana eklenebilir; alan adı + HTTPS ile kurulursa Instagram/TikTok/YouTube'daki **Paylaş** menüsünde de görünür

## VDS'e kurulum (Docker)

Sunucuda Docker kurulu değilse:

```bash
curl -fsSL https://get.docker.com | sh
```

Projeyi sunucuya kopyalayın (örnek: `/opt/video-indir`) ve çalıştırın:

```bash
cd /opt/video-indir
cp .env.example .env
nano .env                   # APP_PASSWORD satırına şifreyi yazın
docker compose up -d --build
```

Uygulama `http://SUNUCU_IP:8000` adresinde açılır. Güvenlik duvarı varsa portu açın: `ufw allow 8000`.

### Alan adınız varsa (önerilir): HTTPS

Alan adının A kaydını sunucu IP'sine yönlendirin, sonra `.env` içinde:

```
DOMAIN=video.ornekalanadi.com
TRUST_PROXY=1
COOKIE_SECURE=1
```

ve şu komutla başlatın (Caddy otomatik ücretsiz SSL sertifikası alır):

```bash
docker compose --profile https up -d --build
```

HTTPS ile gelen ekstralar:
- **Yapıştır** düğmesi çalışır (HTTP'de tarayıcı panoya erişim vermez; kutuya basılı tutup yapıştırmak gerekir)
- Uygulama gerçek bir uygulama gibi ana ekrana kurulur ve telefonun **Paylaş** menüsünde "Video İndir" çıkar: videoda Paylaş → Video İndir → indirme kendiliğinden başlar

## Annenin telefonunda ilk kurulum

1. Chrome'da (ya da Samsung Internet'te) sitenin adresini açın, `.env` dosyasındaki kullanıcı adı ve şifreyle giriş yapın. Tarayıcı şifreyi kaydetmeyi sorarsa kabul edin.
2. Menü (⋮) → **Ana ekrana ekle** / **Uygulamayı yükle**. Artık ana ekranda "Video İndir" simgesi var.
3. Kullanım: videoda **Paylaş → Bağlantıyı kopyala**, uygulamada **Yapıştır → İndir**. Video bittiğinde kendiliğinden telefona iner (İndirilenler klasörü, Galeri'de de görünür). İnmezse yeşil **Telefona kaydet** düğmesine basılır.

## Güncelleme ve bakım

- yt-dlp her konteyner açılışında kendini günceller. Bir platform indirmeyi bozarsa önce `docker compose restart` deneyin.
- Kod güncellemesi sonrası: `docker compose up -d --build`
- Loglar: `docker compose logs -f app`
- Tüm kalıcı veriler `./data` klasöründedir (link geçmişi `videos.db`, küçük resimler, oturum anahtarı). Yedeklemek için bu klasörü kopyalamak yeterli.
- İndirilen video dosyaları sunucuda sadece 1 saat tutulur, sonra silinir (disk dolmasın). Linkler kalıcıdır; listeden **İndir** ile tekrar indirilebilir.

## Instagram / YouTube "giriş gerekiyor" hatası verirse

Sunucu IP'leri bazen Instagram ve YouTube tarafından engellenir. Çözüm, kendi hesabınızın çerezlerini vermek:

1. Bilgisayarda tarayıcıya "Get cookies.txt LOCALLY" eklentisini kurun, instagram.com (veya youtube.com) açıkken çerezleri **Netscape** biçiminde dışa aktarın.
2. Dosyayı sunucuya şu adla koyun:
   - `data/cookies/instagram.txt`
   - `data/cookies/youtube.txt`
   - `data/cookies/tiktok.txt` (genelde gerekmez)
3. Yeniden başlatmaya gerek yok, bir sonraki indirmede kullanılır.

Bu dosyalar hesabınıza erişim sağlar; kimseyle paylaşmayın. Ana hesabınız yerine ikinci bir hesap kullanmak daha güvenlidir.

Hata durumunda uygulamadaki **Teknik ayrıntı** kısmı yt-dlp'nin gerçek hata mesajını gösterir.

## Ayarlar (`.env`)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `APP_USER` / `APP_PASSWORD` | vermilia / (zorunlu) | Giriş bilgileri. Şifre girilmezse uygulama açılmaz. Değiştirilirse açık oturumlar kapanır. |
| `APP_PORT` | 8000 | Dışarıya açılan port |
| `DOMAIN` | – | HTTPS profili için alan adı |
| `TRUST_PROXY` / `COOKIE_SECURE` | – | HTTPS profilinde `1` yapın |
| `FILE_TTL_MINUTES` | 60 | İndirilen dosyanın sunucuda kalma süresi |
| `MAX_PARALLEL_DOWNLOADS` | 2 | Aynı anda en fazla indirme |
| `MAX_HEIGHT` | 1080 | En yüksek çözünürlük |

## Windows'ta deneme

`calistir.bat` dosyasına çift tıklayın. İlk seferde gerekli paketleri kurar, sonra açılacak adresleri yazar (varsayılan port 8765). Pencere açık kaldığı sürece uygulama çalışır.

## Docker'sız çalıştırma (Linux)

Python 3.10+, `ffmpeg` ve (YouTube için) `deno` gerekir:

```bash
pip install -r requirements.txt
DATA_DIR=./data gunicorn app:app -b 0.0.0.0:8000 -w 1 --threads 16 --timeout 300
```

`-w 1` önemli: indirme durumları bellekte tutulduğu için tek işlem çalışmalı.
