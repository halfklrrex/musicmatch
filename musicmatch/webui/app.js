'use strict';

const $ = (s, r = document) => r.querySelector(s);
const api = () => window.pywebview.api;
const state = { rows: new Map(), fetching: 0, clip: [], fmt: 'mp3' };

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = n => `<svg class="i" aria-hidden="true"><use href="#i-${n}"/></svg>`;
const fmtDur = s => {
  if (!s) return '';
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `${m}:${String(x).padStart(2, '0')}`;
};

/* ------------------------------------------------------------ toast */
let toastTimer;
function toast(msg, level = 'info') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast ' + level;
  t.hidden = false;
  t.style.animation = 'none'; void t.offsetWidth; t.style.animation = '';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3800);
}

/* ------------------------------------------------------------ rows */
function segHtml(fmt) {
  return `<div class="seg" role="group" aria-label="Format">
    <button type="button" data-fmt="mp3" aria-pressed="${fmt === 'mp3'}">MP3</button>
    <button type="button" data-fmt="mp4" aria-pressed="${fmt === 'mp4'}">MP4</button></div>`;
}

function addRow(info, before) {
  const r = { id: info.id, title: info.title, song: info.song || info.title, artist: info.artist || '', state: 'idle', fmt: state.fmt, pct: 0, status: 'Ready', path: '' };
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
          <button class="btn danger sm" type="button" data-act="cancel" data-for="queued running">Cancel</button>
          <button class="btn tint sm" type="button" data-act="retry" data-for="error cancelled">${icon('refresh')}Retry</button>
          <button class="btn tint sm" type="button" data-act="open" data-for="done">${icon('open')}Open</button>
          <button class="btn quiet sm" type="button" data-act="show" data-for="done">${icon('folder')}Show</button>
          <button class="icon-btn" type="button" data-act="remove" aria-label="Remove">${icon('x')}</button>
        </div>
      </div>
      <div class="line tags">
        ${icon('note')}
        <input class="field" data-k="song" value="${esc(r.song)}" placeholder="Song title" aria-label="Song title" spellcheck="false">
        <input class="field" data-k="artist" value="${esc(r.artist)}" placeholder="Artist" aria-label="Artist" spellcheck="false">
        <span class="saveas" title="File name"></span>
      </div>
      <div class="line">
        <div class="trim">${icon('scissors')}Trim
          <input class="time" data-k="start" placeholder="0:00" aria-label="Trim start" spellcheck="false">to
          <input class="time" data-k="end" placeholder="end" aria-label="Trim end" spellcheck="false">
        </div>
        <label class="switch"><input type="checkbox" data-k="norm"><span class="tg"></span>Normalize</label>
        <div class="prog"><div class="bar-track"><div class="bar-fill"></div></div><span class="state"></span></div>
      </div>
    </div>`;
  $('#queue').insertBefore(el, before || null);
  r.el = el;
  if (info.error) setRow(r, 'error', info.error);
  else setRow(r, 'idle', 'Ready');
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
  $('.state', el).textContent = r.status;
  $('.state', el).title = r.status;
  el.querySelectorAll('.time, [data-k="norm"], .seg button').forEach(n => { n.disabled = locked; });
  el.querySelectorAll('.field').forEach(n => { n.disabled = locked || st === 'done'; });
  updateSaveAs(r);
  el.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.fmt === r.fmt)));
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
  if (!row) return;
  const r = state.rows.get(Number(row.dataset.id));
  const fmtBtn = e.target.closest('[data-fmt]');
  if (fmtBtn) { r.fmt = fmtBtn.dataset.fmt; setRow(r, r.state); return; }
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (!act) return;
  if (act === 'remove') removeRow(r);
  else if (act === 'cancel') api().cancel(r.id);
  else if (act === 'retry') api().start([collect(r)]);
  else if (act === 'open') api().open_path(r.path).then(ok => ok || toast('That file no longer exists.', 'err'));
  else if (act === 'show') api().show_in_folder(r.path).then(ok => ok || toast('That file no longer exists.', 'err'));
});

/* ------------------------------------------------------------ events from Python */
function onJob(e) {
  const r = state.rows.get(e.id);
  if (!r) return;
  switch (e.kind) {
    case 'queued': setRow(r, 'queued', 'Queued', 0); break;
    case 'status': setRow(r, 'running', e.data); break;
    case 'progress': setRow(r, 'running', e.data[1], e.data[0]); break;
    case 'done': r.path = e.data; setRow(r, 'done', 'Done', 100); break;
    case 'error': setRow(r, 'error', e.data, 0); break;
    case 'cancelled': setRow(r, 'cancelled', 'Cancelled', 0); break;
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
        toast(e.msg, e.ok ? 'ok' : 'err');
        break;
      }
    }
  },
};

function refresh() {
  const n = state.rows.size;
  const shown = n + pending.size;
  $('#empty').hidden = shown > 0;
  $('#queueHead').hidden = shown === 0;
  $('#count').textContent = n;
  const active = [...state.rows.values()].filter(r => r.state === 'queued' || r.state === 'running').length;
  const idle = [...state.rows.values()].filter(r => r.state === 'idle').length;
  const done = [...state.rows.values()].filter(r => r.state === 'done').length;
  const parts = [];
  if (state.fetching) parts.push(`Fetching ${state.fetching} link${state.fetching > 1 ? 's' : ''}…`);
  if (active) parts.push(`${active} downloading`);
  $('#status').textContent = parts.join('  ·  ');
  $('#downloadAll').disabled = idle === 0;
  $('#clearDone').disabled = done === 0;
}

/* ------------------------------------------------------------ adding links */
async function addUrls(text) {
  const res = await api().add_urls(text);
  if (!res.added) { toast('No YouTube links found in that text.', 'err'); return false; }
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
  if (!text.trim()) { toast('The clipboard has no text.', 'err'); return; }
  if (await addUrls(text)) $('#url').value = '';
  else $('#url').value = text.trim();
});

document.addEventListener('paste', async e => {
  if (e.target.matches('input')) return;
  const text = e.clipboardData?.getData('text') || '';
  if (text) { e.preventDefault(); await addUrls(text); }
});

/* clipboard banner */
async function checkClipboard() {
  if (!window.pywebview) return;
  const urls = await api().clipboard_urls();
  if (!urls.length) return;
  state.clip = urls;
  const first = urls[0].length > 70 ? urls[0].slice(0, 67) + '…' : urls[0];
  $('#bannerText').textContent = `YouTube link on clipboard: ${first}${urls.length > 1 ? `  (+${urls.length - 1} more)` : ''}`;
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
$('#updateBtn').addEventListener('click', () => {
  const b = $('#updateBtn');
  b.disabled = true; b.classList.add('spin');
  api().update_ytdlp();
  toast('Updating yt-dlp…');
});

/* ------------------------------------------------------------ history sheet */
async function openHistory() {
  const items = await api().history();
  const list = $('#historyList');
  list.innerHTML = items.length ? items.map((it, i) => `
    <div class="h-item" data-i="${i}">
      <div class="h-main">
        <div class="h-title" title="${esc(it.title)}">${esc(it.title)}</div>
        <div class="h-meta"><span class="tag">${esc(it.fmt)}</span>${esc(it.date)}${it.exists ? '' : '<span class="missing">· file moved</span>'}</div>
      </div>
      ${it.exists ? `<button class="btn tint sm" data-h="open">Open</button><button class="btn quiet sm" data-h="show">Show</button>` : ''}
    </div>`).join('') : '<div class="h-empty">No downloads yet.</div>';
  list._items = items;
  $('#historyClear').hidden = !items.length;
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
  const it = $('#historyList')._items[Number(b.closest('.h-item').dataset.i)];
  (b.dataset.h === 'open' ? api().open_path(it.path) : api().show_in_folder(it.path));
});
$('#historyClear').addEventListener('click', async () => { await api().history_clear(); openHistory(); });

/* ------------------------------------------------------------ boot */
async function boot() {
  const s = await api().init();
  setDefFmt(s.fmt);
  $('#kbps').value = s.kbps; $('#height').value = s.height; $('#parallel').value = s.parallel;
  $('#folder').textContent = s.folder;
  refresh();
  checkClipboard();
}
if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener('pywebviewready', boot);
