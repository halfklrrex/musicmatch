'use strict';
/* MusicMatch interface logic. Text lives in i18n.js (English / Spanish). */

const $ = (s, r = document) => r.querySelector(s);
const api = () => window.pywebview.api;
const state = { rows: new Map(), fetching: 0, clip: [], fmt: 'mp3', lang: 'en', history: null };

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = n => `<svg class="i" aria-hidden="true"><use href="#i-${n}"/></svg>`;
const fmtDur = s => {
  if (!s) return '';
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `${m}:${String(x).padStart(2, '0')}`;
};

/* ------------------------------------------------------------ language */
function tr(key, vars) {
  let s = STRINGS[state.lang][key] ?? STRINGS.en[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  return s;
}

/* Row status/error text. The engine sends "@name" for its own messages,
   "@prog|pct|speed|eta" for progress, and raw yt-dlp text for other errors. */
function statusText(s) {
  if (!s) return '';
  if (s.startsWith('@prog|')) {
    const [, pct, speed, eta] = s.split('|');
    return [pct, speed, eta && `${tr('s.eta')} ${eta}`].filter(Boolean).join('  •  ');
  }
  if (s.startsWith('@')) {
    const [n, detail] = s.slice(1).split('|');
    const text = tr(STRINGS.en['s.' + n] ? 's.' + n : 'e.' + n);
    return detail ? `${text}: ${detail}` : text;
  }
  if (state.lang === 'es') {
    for (const [re, key] of YTDLP_PATTERNS) if (re.test(s)) return tr(key);
  }
  return s;
}

function applyLang(root = document) {
  document.documentElement.lang = state.lang;
  root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = tr(el.dataset.i18n); });
  root.querySelectorAll('[data-i18n-html]').forEach(el => { el.innerHTML = tr(el.dataset.i18nHtml); });
  root.querySelectorAll('[data-i18n-ph]').forEach(el => { el.placeholder = tr(el.dataset.i18nPh); });
  root.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = tr(el.dataset.i18nTitle); });
  root.querySelectorAll('[data-i18n-aria]').forEach(el => { el.setAttribute('aria-label', tr(el.dataset.i18nAria)); });
  if (root !== document) return;
  document.querySelectorAll('#lang button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.lang === state.lang)));
  state.rows.forEach(r => setRow(r, r.state));
  renderBanner();
  refresh();
  if ($('#sheet').classList.contains('open')) renderHistory();
}

function setLang(l) {
  if (!STRINGS[l] || l === state.lang) return;
  state.lang = l;
  applyLang();
  api().set_setting('lang', l);
}
$('#lang').addEventListener('click', e => { const b = e.target.closest('[data-lang]'); if (b) setLang(b.dataset.lang); });

/* ------------------------------------------------------------ toast */
let toastTimer;
function toast(msg, level = 'info') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast ' + level;
  t.hidden = false;
  t.style.animation = 'none'; void t.offsetWidth; t.style.animation = '';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 4200);
}

/* ------------------------------------------------------------ rows */
function segHtml(fmt) {
  return `<div class="seg" role="group" aria-label="Format">
    <button type="button" data-fmt="mp3" aria-pressed="${fmt === 'mp3'}">MP3</button>
    <button type="button" data-fmt="mp4" aria-pressed="${fmt === 'mp4'}">MP4</button></div>`;
}

function addRow(info, before) {
  const r = { id: info.id, title: info.title, state: 'idle', fmt: state.fmt, pct: 0, status: '@ready', path: '' };
  state.rows.set(r.id, r);
  const el = document.createElement('article');
  el.className = 'row';
  el.dataset.id = r.id;
  el.dataset.state = 'idle';
  el.innerHTML = `
    <div class="thumb">${info.thumb ? `<img src="${esc(info.thumb)}" alt="" loading="lazy" onerror="this.remove()">` : ''}<span class="dur">${fmtDur(info.duration)}</span></div>
    <div class="body">
      <div class="line">
        <h3 class="title" title="${esc(info.title)}">${esc(info.title)}</h3>
        <div class="acts">
          ${segHtml(r.fmt)}
          <button class="btn danger sm" type="button" data-act="cancel" data-for="queued running" data-i18n="cancel"></button>
          <button class="btn tint sm" type="button" data-act="retry" data-for="error cancelled">${icon('refresh')}<span data-i18n="retry"></span></button>
          <button class="btn tint sm" type="button" data-act="open" data-for="done">${icon('open')}<span data-i18n="open"></span></button>
          <button class="btn quiet sm" type="button" data-act="show" data-for="done">${icon('folder')}<span data-i18n="show"></span></button>
          <button class="icon-btn" type="button" data-act="remove" data-i18n-aria="remove">${icon('x')}</button>
        </div>
      </div>
      <div class="line tags">
        ${icon('note')}
        <input class="field" data-k="song" value="${esc(info.song || info.title)}" data-i18n-ph="song_ph" data-i18n-aria="song_ph" spellcheck="false">
        <input class="field" data-k="artist" value="${esc(info.artist || '')}" data-i18n-ph="artist_ph" data-i18n-aria="artist_ph" spellcheck="false">
        <span class="saveas" title=""></span>
      </div>
      <div class="line">
        <div class="trim">${icon('scissors')}<span data-i18n="trim"></span>
          <input class="time" data-k="start" data-i18n-ph="start_ph" spellcheck="false">
          <span data-i18n="to"></span>
          <input class="time" data-k="end" data-i18n-ph="end_ph" spellcheck="false">
        </div>
        <label class="switch"><input type="checkbox" data-k="norm" checked><span class="tg"></span><span data-i18n="normalize"></span></label>
        <div class="prog"><div class="bar-track"><div class="bar-fill"></div></div><span class="state"></span></div>
      </div>
    </div>`;
  $('#queue').insertBefore(el, before || null);
  r.el = el;
  applyLang(el);
  setRow(r, info.error ? 'error' : 'idle', info.error ? info.error : '@ready');
  refresh();
}

/* skeleton shown while a link's details are fetched; keeps rows in pasted order */
const pending = new Map();
function addPlaceholder(ticket) {
  const el = document.createElement('div');
  el.className = 'row skeleton';
  el.innerHTML = '<div class="thumb"></div><div class="body"><div class="sk l1"></div><div class="sk l2"></div></div>';
  $('#queue').append(el);
  pending.set(ticket, el);
  refresh();
}
function fillPlaceholder(e) {
  const ph = pending.get(e.ticket);
  pending.delete(e.ticket);
  e.rows.forEach(info => addRow(info, ph));
  ph?.remove();
  state.fetching = e.n;
  refresh();
}

function setRow(r, st, status, pct) {
  r.state = st;
  if (status !== undefined) r.status = status;
  if (pct !== undefined) r.pct = pct;
  const el = r.el;
  el.dataset.state = st;
  const locked = st === 'queued' || st === 'running';
  el.dataset.locked = locked ? '1' : '0';
  el.style.setProperty('--pct', r.pct);
  const text = statusText(r.status);
  $('.state', el).textContent = text;
  $('.state', el).title = text;
  el.querySelectorAll('.time, [data-k="norm"], .seg button').forEach(n => { n.disabled = locked; });
  el.querySelectorAll('.field').forEach(n => { n.disabled = locked || st === 'done'; });
  el.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.fmt === r.fmt)));
  updateSaveAs(r);
}

const illegal = /[<>:"\/\\|?*\x00-\x1f]/g;
function updateSaveAs(r) {
  const song = $('[data-k="song"]', r.el).value.trim() || r.title;
  const artist = $('[data-k="artist"]', r.el).value.trim();
  const base = (artist ? `${song} - ${artist}` : song).replace(illegal, '_').trim();
  const name = `${base}.${r.fmt}`;
  const out = $('.saveas', r.el);
  out.textContent = name;
  out.title = name;
  out.dataset.pre = tr('saves_as') + '  ';
}

function collect(r) {
  const el = r.el;
  return {
    id: r.id, fmt: r.fmt,
    song: $('[data-k="song"]', el).value, artist: $('[data-k="artist"]', el).value,
    trim_start: $('[data-k="start"]', el).value, trim_end: $('[data-k="end"]', el).value,
    normalize: $('[data-k="norm"]', el).checked,
  };
}

function removeRow(r) {
  api().remove(r.id);
  state.rows.delete(r.id);
  r.el.classList.add('leaving');
  setTimeout(() => { r.el.remove(); refresh(); }, 240);
  refresh();
}

$('#queue').addEventListener('input', e => {
  const row = e.target.closest('.row');
  if (row && e.target.classList.contains('field')) updateSaveAs(state.rows.get(Number(row.dataset.id)));
});

$('#queue').addEventListener('click', e => {
  const row = e.target.closest('.row');
  if (!row || row.classList.contains('skeleton')) return;
  const r = state.rows.get(Number(row.dataset.id));
  const fmtBtn = e.target.closest('[data-fmt]');
  if (fmtBtn) { r.fmt = fmtBtn.dataset.fmt; setRow(r, r.state); return; }
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (!act) return;
  if (act === 'remove') removeRow(r);
  else if (act === 'cancel') api().cancel(r.id);
  else if (act === 'retry') api().start([collect(r)]);
  else if (act === 'open') api().open_path(r.path).then(ok => ok || toast(tr('t_file_gone'), 'err'));
  else if (act === 'show') api().show_in_folder(r.path).then(ok => ok || toast(tr('t_file_gone'), 'err'));
});

/* ------------------------------------------------------------ events from Python */
function onJob(e) {
  const r = state.rows.get(e.id);
  if (!r) return;
  switch (e.kind) {
    case 'queued': setRow(r, 'queued', '@queued', 0); break;
    case 'status': setRow(r, 'running', e.data); break;
    case 'progress': setRow(r, 'running', e.data[1], e.data[0]); break;
    case 'done': r.path = e.data; setRow(r, 'done', '@done', 100); break;
    case 'error': setRow(r, 'error', e.data, 0); break;
    case 'cancelled': setRow(r, 'cancelled', '@cancelled', 0); break;
  }
  refresh();
}

window.mm = {
  onEvent(e) {
    switch (e.t) {
      case 'rows': fillPlaceholder(e); break;
      case 'job': onJob(e); break;
      case 'updated': {
        const b = $('#updateBtn');
        b.classList.remove('spin'); b.disabled = false;
        toast(e.ok ? e.msg : tr('t_update_failed', { msg: e.msg }), e.ok ? 'ok' : 'err');
        break;
      }
    }
  },
};

function refresh() {
  const rows = [...state.rows.values()];
  const shown = rows.length + pending.size;
  $('#empty').hidden = shown > 0;
  $('#queueHead').hidden = shown === 0;
  $('#count').textContent = rows.length;
  const active = rows.filter(r => r.state === 'queued' || r.state === 'running').length;
  const idle = rows.filter(r => r.state === 'idle').length;
  const done = rows.filter(r => r.state === 'done').length;
  const parts = [];
  if (state.fetching) parts.push(state.fetching === 1 ? tr('fetching_one') : tr('fetching_many', { n: state.fetching }));
  if (active) parts.push(tr('downloading', { n: active }));
  $('#status').textContent = parts.join('  ·  ');
  $('#downloadAll').disabled = idle === 0;
  $('#clearDone').disabled = done === 0;
  $('#clearAll').disabled = shown === 0;
}

/* ------------------------------------------------------------ adding links */
async function addUrls(text) {
  const res = await api().add_urls(text);
  if (!res.added) {
    toast(res.skipped ? tr('t_playlist') : tr('t_no_links'), 'err');
    return false;
  }
  if (res.skipped) toast(tr('t_added_skipped', { n: res.added, s: res.skipped }));
  state.fetching += res.added;
  res.tickets.forEach(addPlaceholder);
  return true;
}

$('#addForm').addEventListener('submit', async e => {
  e.preventDefault();
  const input = $('#url');
  if (!input.value.trim()) return;
  if (await addUrls(input.value)) input.value = '';
});

$('#pasteBtn').addEventListener('click', async () => {
  const text = await api().clipboard_text();
  if (!text.trim()) { toast(tr('t_clipboard_empty'), 'err'); return; }
  if (await addUrls(text)) $('#url').value = '';
  else $('#url').value = text.trim();
});

document.addEventListener('paste', async e => {
  if (e.target.matches('input')) return;
  const text = e.clipboardData?.getData('text') || '';
  if (text) { e.preventDefault(); await addUrls(text); }
});

/* clipboard banner */
function renderBanner() {
  const urls = state.clip;
  if (!urls.length) return;
  const first = urls[0].length > 70 ? urls[0].slice(0, 67) + '…' : urls[0];
  $('#bannerText').textContent = tr('clipboard_banner', { url: first }) + (urls.length > 1 ? '  ' + tr('clipboard_more', { n: urls.length - 1 }) : '');
}
async function checkClipboard() {
  if (!window.pywebview) return;
  const urls = await api().clipboard_urls();
  if (!urls.length) return;
  state.clip = urls;
  renderBanner();
  $('#banner').hidden = false;
}
$('#bannerAdd').addEventListener('click', () => { addUrls(state.clip.join(' ')); $('#banner').hidden = true; });
$('#bannerDismiss').addEventListener('click', () => { $('#banner').hidden = true; });
window.addEventListener('focus', checkClipboard);

/* ------------------------------------------------------------ options */
function setDefFmt(v) {
  state.fmt = v;
  document.querySelectorAll('#defFmt button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === v)));
}
$('#defFmt').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  setDefFmt(b.dataset.v); api().set_setting('fmt', b.dataset.v);
});
for (const id of ['kbps', 'height', 'parallel']) $('#' + id).addEventListener('change', e => api().set_setting(id, e.target.value));

$('#browseBtn').addEventListener('click', async () => { const f = await api().browse_folder(); if (f) $('#folder').textContent = f; });
$('#openFolderBtn').addEventListener('click', () => api().open_folder());

/* ------------------------------------------------------------ footer */
$('#downloadAll').addEventListener('click', () => {
  const items = [...state.rows.values()].filter(r => r.state === 'idle').map(collect);
  if (items.length) api().start(items);
});
$('#clearDone').addEventListener('click', () => {
  [...state.rows.values()].filter(r => r.state === 'done').forEach(removeRow);
});

let clearArmed = 0;
function disarmClear() {
  clearTimeout(clearArmed); clearArmed = 0;
  $('#clearAll').textContent = tr('clear_queue');
}
$('#clearAll').addEventListener('click', async () => {
  const busy = [...state.rows.values()].some(r => r.state === 'queued' || r.state === 'running');
  if (busy && !clearArmed) {  // downloads are running: ask for a second click
    clearArmed = setTimeout(disarmClear, 3000);
    $('#clearAll').textContent = tr('clear_confirm');
    return;
  }
  disarmClear();
  await api().clear_all();
  state.rows.clear(); pending.clear(); state.fetching = 0;
  $('#queue').textContent = '';
  refresh();
});

$('#updateBtn').addEventListener('click', () => {
  const b = $('#updateBtn');
  b.disabled = true; b.classList.add('spin');
  api().update_ytdlp();
  toast(tr('t_updating'));
});

/* ------------------------------------------------------------ history sheet */
function renderHistory() {
  const items = state.history || [];
  const list = $('#historyList');
  list.innerHTML = items.length ? items.map((it, i) => `
    <div class="h-item" data-i="${i}">
      <div class="h-main">
        <div class="h-title" title="${esc(it.title)}">${esc(it.title)}</div>
        <div class="h-meta"><span class="tag">${esc(it.fmt)}</span>${esc(it.date)}${it.exists ? '' : `<span class="missing">· ${esc(tr('file_moved'))}</span>`}</div>
      </div>
      ${it.exists ? `<button class="btn tint sm" data-h="open">${esc(tr('open'))}</button><button class="btn quiet sm" data-h="show">${esc(tr('show'))}</button>` : ''}
    </div>`).join('') : `<div class="h-empty">${esc(tr('no_history'))}</div>`;
  $('#historyClear').hidden = !items.length;
}
async function openHistory() {
  state.history = await api().history();
  renderHistory();
  $('#scrim').hidden = false;
  const s = $('#sheet'); s.classList.add('open'); s.setAttribute('aria-hidden', 'false');
}
function closeHistory() {
  $('#sheet').classList.remove('open'); $('#sheet').setAttribute('aria-hidden', 'true');
  $('#scrim').hidden = true;
}
$('#historyBtn').addEventListener('click', openHistory);
$('#sheetClose').addEventListener('click', closeHistory);
$('#scrim').addEventListener('click', closeHistory);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeHistory(); });
$('#historyList').addEventListener('click', e => {
  const b = e.target.closest('[data-h]'); if (!b) return;
  const it = state.history[Number(b.closest('.h-item').dataset.i)];
  (b.dataset.h === 'open' ? api().open_path(it.path) : api().show_in_folder(it.path));
});
$('#historyClear').addEventListener('click', async () => { await api().history_clear(); openHistory(); });

/* ------------------------------------------------------------ boot */
async function boot() {
  const s = await api().init();
  state.lang = STRINGS[s.lang] ? s.lang : (navigator.language || 'en').toLowerCase().startsWith('es') ? 'es' : 'en';
  setDefFmt(s.fmt);
  $('#kbps').value = s.kbps; $('#height').value = s.height; $('#parallel').value = s.parallel;
  $('#folder').textContent = s.folder;
  applyLang();
  checkClipboard();
}
if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener('pywebviewready', boot);
