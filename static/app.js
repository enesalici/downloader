(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const PLATFORMS = {
    instagram: 'Instagram',
    tiktok: 'TikTok',
    youtube: 'YouTube',
  };

  const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) {
      try { value == null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch { /* yok say */ }
    },
  };

  const state = { history: {}, jobId: null, lastUrl: '', pollTimer: null, autoSave: false };

  // ---------------------------------------------------------------- yardımcılar

  async function api(path, options = {}) {
    const headers = options.body ? { 'Content-Type': 'application/json' } : {};
    const res = await fetch(path, { credentials: 'same-origin', headers, ...options });
    if (res.status === 401) {
      location.href = '/login';
      throw new Error('Oturum kapandı.');
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || 'Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edin.');
      err.status = res.status;
      throw err;
    }
    return data;
  }

  let toastTimer;
  function toast(text) {
    const el = $('#toast');
    el.textContent = text;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 2400);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    toast('Link kopyalandı');
  }

  const dateFmt = new Intl.DateTimeFormat('tr-TR', { day: 'numeric', month: 'long', year: 'numeric' });

  function formatDuration(sec) {
    if (!sec) return '';
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = String(sec % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
  }

  function platformBadge(el, platform) {
    el.className = 'badge ' + platform;
    el.replaceChildren();
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'ico');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#i-' + platform);
    svg.appendChild(use);
    el.append(svg, PLATFORMS[platform] || '');
  }

  // ---------------------------------------------------------------- bölümler

  function show(view) {
    $$('.view').forEach((v) => v.classList.toggle('active', v.id === 'view-' + view));
    $$('.nav-btn').forEach((b) => b.setAttribute('aria-current', b.dataset.view === view ? 'page' : 'false'));
    window.scrollTo({ top: 0 });
  }

  $$('.nav-btn').forEach((btn) => btn.addEventListener('click', () => show(btn.dataset.view)));

  // ---------------------------------------------------------------- indirme

  const input = $('#url');
  const pasteBtn = $('#paste-btn');
  const canPaste = !!(navigator.clipboard && navigator.clipboard.readText && window.isSecureContext);

  function syncChip() {
    if (input.value) {
      pasteBtn.textContent = 'Temizle';
      pasteBtn.hidden = false;
    } else {
      pasteBtn.textContent = 'Yapıştır';
      pasteBtn.hidden = !canPaste;
    }
  }

  input.addEventListener('input', syncChip);

  pasteBtn.addEventListener('click', async () => {
    if (input.value) {
      input.value = '';
      syncChip();
      input.focus();
      return;
    }
    try {
      const text = await navigator.clipboard.readText();
      if (!text) { toast('Panoda link yok'); return; }
      input.value = text.trim();
      syncChip();
    } catch {
      toast('Yapıştırılamadı. Kutuya basılı tutup “Yapıştır”ı seçin.');
      input.focus();
    }
  });

  $('#dl-form').addEventListener('submit', (e) => {
    e.preventDefault();
    startDownload(input.value);
  });

  function shakeInput() {
    const wrap = $('.input-wrap');
    wrap.classList.remove('shake');
    void wrap.offsetWidth;
    wrap.classList.add('shake');
    input.focus();
  }

  async function startDownload(url) {
    url = (url || '').trim();
    if (!url) {
      toast('Önce videonun linkini yapıştırın');
      shakeInput();
      return;
    }
    show('download');
    state.lastUrl = url;
    $('#dl-btn').disabled = true;
    renderStatus({ status: 'queued', progress: 0, message: 'Başlatılıyor…' });
    try {
      const job = await api('/api/download', { method: 'POST', body: JSON.stringify({ url }) });
      track(job, true);
    } catch (err) {
      renderStatus({ status: 'error', message: err.message });
    }
  }

  function track(job, autoSave) {
    state.jobId = job.id;
    state.autoSave = autoSave;
    store.set('job', job.id);
    renderStatus(job);
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(poll, 800);
  }

  async function poll() {
    if (!state.jobId) return;
    try {
      const job = await api('/api/job/' + state.jobId);
      renderStatus(job);
      if (job.status === 'done') return onDone(job);
      if (job.status === 'error') { store.set('job', null); return; }
    } catch (err) {
      if (err.status === 404) {
        store.set('job', null);
        state.jobId = null;
        $('#status').hidden = true;
        $('#dl-btn').disabled = false;
        return;
      }
      // geçici ağ hatası: denemeye devam
    }
    state.pollTimer = setTimeout(poll, 1000);
  }

  function onDone(job) {
    store.set('job', null);
    if (state.autoSave) {
      state.autoSave = false;
      const a = document.createElement('a');
      a.href = job.file_url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      a.remove();
      toast('Video telefona kaydediliyor…');
    }
    loadHistory();
  }

  function renderStatus(job) {
    const box = $('#status');
    const busy = job.status === 'queued' || job.status === 'downloading';
    box.hidden = false;
    box.classList.toggle('is-done', job.status === 'done');
    box.classList.toggle('is-error', job.status === 'error');

    const badge = $('#st-platform');
    if (job.platform) { platformBadge(badge, job.platform); badge.hidden = false; } else { badge.hidden = true; }

    $('#st-state').textContent = busy && job.progress ? `%${job.progress}` : '';
    $('#st-title').textContent = job.title || '';
    $('#st-msg').textContent = job.message || '';

    const progress = $('#st-progress');
    progress.classList.toggle('indeterminate', busy && !job.progress);
    $('#st-bar').style.width = (job.status === 'done' ? 100 : job.progress || 0) + '%';

    const detail = $('#st-detail');
    detail.hidden = !(job.status === 'error' && job.detail);
    $('#st-detail-text').textContent = job.detail || '';

    $('#st-done').hidden = job.status !== 'done';
    $('#st-fail').hidden = job.status !== 'error';
    if (job.status === 'done') $('#st-save').href = job.file_url;
    if (job.url) state.lastUrl = job.url;

    $('#dl-btn').disabled = busy;
  }

  $('#st-new').addEventListener('click', () => {
    $('#status').hidden = true;
    state.jobId = null;
    input.value = '';
    syncChip();
    input.focus();
  });

  $('#st-retry').addEventListener('click', () => startDownload(state.lastUrl || input.value));

  // ---------------------------------------------------------------- geçmiş

  async function loadHistory() {
    try {
      state.history = await api('/api/history');
      renderHistory();
    } catch { /* sessizce geç */ }
  }

  function renderHistory() {
    const tpl = $('#item-tpl');
    for (const platform of Object.keys(PLATFORMS)) {
      const items = state.history[platform] || [];
      $('#count-' + platform).textContent = items.length || '';
      $('#empty-' + platform).hidden = items.length > 0;
      $('#list-' + platform).replaceChildren(...items.map((item) => {
        const li = tpl.content.firstElementChild.cloneNode(true);
        li.dataset.id = item.id;
        li.dataset.url = item.url;

        const thumb = $('.thumb', li);
        thumb.href = item.url;
        const img = $('img', thumb);
        if (item.thumb) img.src = item.thumb; else img.remove();
        $('.dur', li).textContent = formatDuration(item.duration);

        $('.title', li).textContent = item.title || 'Video';
        const sub = [item.uploader, dateFmt.format(new Date(item.created_at * 1000))].filter(Boolean);
        $('.sub', li).textContent = sub.join(' · ');
        $('[data-act="open"]', li).href = item.url;
        return li;
      }));
    }
  }

  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.item [data-act]');
    if (!btn) return;
    const li = btn.closest('.item');
    const url = li.dataset.url;
    switch (btn.dataset.act) {
      case 'download':
        input.value = url;
        syncChip();
        startDownload(url);
        break;
      case 'copy':
        copyText(url);
        break;
      case 'delete':
        if (!confirm('Bu video listeden silinsin mi?')) return;
        try {
          await api('/api/history/' + li.dataset.id, { method: 'DELETE' });
          li.remove();
          await loadHistory();
          toast('Listeden silindi');
        } catch (err) {
          toast(err.message);
        }
        break;
    }
  });

  // ---------------------------------------------------------------- açılış

  syncChip();
  loadHistory();

  const params = new URLSearchParams(location.search);
  const sharedUrl = params.get('url');
  if (sharedUrl) {
    // Paylaş menüsünden ya da ?url= ile gelindi: hemen indirmeye başla.
    history.replaceState(null, '', '/');
    input.value = sharedUrl;
    syncChip();
    startDownload(sharedUrl);
  } else {
    const pending = store.get('job');
    if (pending) track({ id: pending, status: 'queued', progress: 0, message: 'Kontrol ediliyor…' }, false);
  }

  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
})();
