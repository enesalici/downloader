// Uygulamanın ana ekrana eklenebilmesi ve Android "Paylaş" menüsünde görünmesi için gerekli.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

const OFFLINE_HTML = `<!doctype html><html lang="tr"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Video İndir</title>
<body style="font:17px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;padding:16px;text-align:center">
<div><h1 style="font-size:1.4rem">İnternet bağlantısı yok</h1>
<p>Bağlantınızı kontrol edip sayfayı yenileyin.</p>
<button onclick="location.reload()" style="font:inherit;padding:12px 20px;border-radius:12px;border:0;background:#4F46E5;color:#fff">Yenile</button></div>`;

self.addEventListener('fetch', (event) => {
  if (event.request.mode !== 'navigate') return;
  event.respondWith(
    fetch(event.request).catch(
      () => new Response(OFFLINE_HTML, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })
    )
  );
});
