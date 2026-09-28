(() => {
'use strict';
const $ = id => document.getElementById(id);
const api = {
  get: u => fetch(u).then(r => r.json()),
  post: (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then(r => r.json()),
  raw: (u, blob) => fetch(u, { method: 'POST', body: blob }).then(r => r.json()),
};
const PAD = 28;                       // left gutter of the timeline (track labels)
const COLORS = ['#4b3a2b', '#3a3f31', '#46333a', '#2f403f', '#4a4029', '#3c3549', '#3f3a33', '#2e3a48'];

let ST = null;                        // server state
let sel = null;                       // selected scene id
let cur = 0;                          // current frame
let playing = false;
let buffering = false;
let pxs = 0;                          // pixels per second on the timeline
let userZoom = false;
let lastTotal = -1;
let cacheStr = '';
let painted = -1;
let audioVer = -1;
let lastSig = '';
let lastTextSig = '';
let lastExportSeen = null;
const frames = new Map();             // fi -> {gen, blob}
const pending = new Set();
const drafts = new Map();             // sid -> {code, dirty}

// ------------------------------------------------------------------ helpers
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
function tc(f) {
  if (!ST) return '00:00:00';
  const fps = ST.fps, s = Math.floor(f / fps), m = Math.floor(s / 60);
  return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}:${String(f % fps).padStart(2, '0')}`;
}
function sceneAt(f) {
  if (!ST || !ST.scenes.length) return null;
  let lo = 0, hi = ST.scenes.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ST.scenes[mid].f0 <= f) lo = mid; else hi = mid - 1;
  }
  return ST.scenes[lo];
}
const sceneById = id => ST && ST.scenes.find(s => s.id === id);
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
let toastTimer = null;
function toast(html, ms = 3500) {
  const t = $('toast');
  t.innerHTML = html; t.hidden = false;
  clearTimeout(toastTimer);
  if (ms) toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}
function debounce(fn, ms) { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; }

// ------------------------------------------------------------------ editor
function makeEditor(host) {
  if (window.CodeMirror) {
    const cm = CodeMirror(host, {
      mode: 'python', theme: 'shelter', lineNumbers: true, indentUnit: 4, tabSize: 4, indentWithTabs: false,
      matchBrackets: true, styleActiveLine: true, lineWrapping: false,
      extraKeys: {
        Tab: c => c.somethingSelected() ? c.indentSelection('add') : c.replaceSelection('    ', 'end'),
        'Shift-Tab': c => c.indentSelection('subtract'),
        'Ctrl-/': 'toggleComment', 'Cmd-/': 'toggleComment',
        'Ctrl-S': () => saveCode(), 'Cmd-S': () => saveCode(),
      },
    });
    let mark = null;
    return {
      get: () => cm.getValue(),
      set: v => { cm.setValue(v); cm.clearHistory(); },
      onChange: fn => cm.on('change', (c, ch) => { if (ch.origin !== 'setValue') fn(); }),
      insert: s => { cm.replaceSelection(s); cm.focus(); },
      mark: ln => {
        if (mark) cm.removeLineClass(mark, 'background', 'err-line');
        mark = null;
        if (ln && ln <= cm.lineCount()) mark = cm.addLineClass(ln - 1, 'background', 'err-line');
      },
      goto: ln => { cm.setCursor({ line: ln - 1, ch: 0 }); cm.scrollIntoView(null, 120); cm.focus(); },
      refresh: () => cm.refresh(),
      focused: () => cm.hasFocus(),
    };
  }
  // offline fallback: plain textarea
  const ta = document.createElement('textarea');
  ta.className = 'fallback'; ta.spellcheck = false;
  host.appendChild(ta);
  ta.addEventListener('keydown', e => {
    if (e.key === 'Tab') { e.preventDefault(); document.execCommand('insertText', false, '    '); }
  });
  return {
    get: () => ta.value, set: v => { ta.value = v; },
    onChange: fn => ta.addEventListener('input', fn),
    insert: s => { ta.focus(); document.execCommand('insertText', false, s); },
    mark: () => {}, goto: ln => { const lines = ta.value.split('\n'); let p = 0; for (let i = 0; i < ln - 1; i++) p += lines[i].length + 1; ta.focus(); ta.setSelectionRange(p, p); },
    refresh: () => {}, focused: () => document.activeElement === ta,
  };
}
const ed = makeEditor($('editor'));
let loadingCode = false;

// ------------------------------------------------------------------ state
async function refresh() {
  let s;
  try { s = await api.get('/api/state'); } catch (e) { $('status').innerHTML = '<b style="color:var(--red)">Нет связи с программой.</b> Запущена ли она?'; return; }
  const old = ST;
  ST = s;
  if (!old) init();
  if (document.activeElement !== $('title')) $('title').value = ST.title;
  $('tcTotal').textContent = tc(ST.total);
  // structure / gens changed?
  const sig = JSON.stringify(ST.scenes.map(x => [x.id, x.name, x.dur, x.n, x.gen, !!x.error, x.hits]));
  if (ST.total !== lastTotal) { lastTotal = ST.total; if (!userZoom) fitZoom(); lastSig = ''; }
  if (sig !== lastSig) { lastSig = sig; drawTimeline(); }
  if (!sel || !sceneById(sel)) { if (ST.scenes.length) selectScene(ST.scenes[0].id, false); }
  // current frame became stale?
  const sc = sceneAt(cur);
  if (sc && !playing) {
    const e = frames.get(cur);
    if (!e || e.gen !== sc.gen) show(cur, true);
  }
  updateInspector();
  updateErrors();
  renderTexts();
  updateSettings();
  updateStatus();
  updateExport();
  if (ST.audio_ver !== audioVer && ST.audio_state === 'ready') loadAudio();
}

function updateStatus() {
  const done = cacheStr ? (cacheStr.split('1').length - 1) : 0;
  const pct = ST.total ? Math.round(done / ST.total * 100) : 0;
  const a = ST.audio_state === 'ready' ? 'готов' : ST.audio_state === 'mixing' ? 'сводится…' : ST.audio_state;
  const errs = ST.scenes.filter(s => s.error).length;
  $('status').innerHTML = `<b>${ST.scenes.length}</b> сцен · <b>${tc(ST.total).slice(0, 5)}</b> · превью готово <b>${pct}%</b> · звук: ${a}` +
    (errs ? ` · <b style="color:var(--red)">ошибки в сценах: ${errs}</b>` : '');
}

// ------------------------------------------------------------------ viewer
const cv = $('screen'), ctx = cv.getContext('2d');
let paintTok = 0;
async function paint(blob, f) {
  const tok = ++paintTok;
  try {
    const bm = await createImageBitmap(blob);
    if (tok !== paintTok) { bm.close && bm.close(); return; }
    ctx.drawImage(bm, 0, 0, cv.width, cv.height);
    bm.close && bm.close();
    painted = f;
  } catch (e) { /* ignore */ }
}
async function fetchFrame(f, wait) {
  const sc = sceneAt(f);
  if (!sc) return null;
  const gen = sc.gen;
  pending.add(f);
  try {
    const r = await fetch(`/api/frame?f=${f}${wait ? '' : '&nowait=1'}`);
    if (r.status !== 200) return null;
    const b = await r.blob();
    frames.set(f, { gen, blob: b });
    if (frames.size > 2600) {           // простая очистка памяти
      let k = 0;
      for (const key of frames.keys()) { if (Math.abs(key - cur) > 600) { frames.delete(key); if (++k > 400) break; } }
    }
    return b;
  } finally { pending.delete(f); }
}
let showTok = 0;
async function show(f, wait) {
  const sc = sceneAt(f);
  if (!sc) { ctx.fillStyle = '#000'; ctx.fillRect(0, 0, cv.width, cv.height); return; }
  const e = frames.get(f);
  if (e && e.gen === sc.gen) return paint(e.blob, f);
  const tok = ++showTok;
  const b = await fetchFrame(f, wait);
  if (b && tok === showTok && f === cur) paint(b, f);
}

function setCur(f, fromPlay) {
  if (!ST) return;
  cur = clamp(Math.round(f), 0, Math.max(0, ST.total - 1));
  $('tcCur').textContent = tc(cur);
  const sc = sceneAt(cur);
  $('sceneNow').textContent = sc ? sc.name : '';
  placePlayhead();
  if (!fromPlay) { show(cur, true); postPlayhead(); followPlayhead(); if (playing) startClock(); }
}
const postPlayhead = (() => { let last = 0, h = null; return () => {
  const go = () => { last = performance.now(); fetch('/api/playhead', { method: 'POST', body: JSON.stringify({ f: cur }), headers: { 'Content-Type': 'application/json' } }); };
  clearTimeout(h);
  if (performance.now() - last > 250) go(); else h = setTimeout(go, 250);
}; })();

// ---- playback
const au = $('audio');
let clock = { t0: 0, f0: 0 };
function startClock() {
  clock = { t0: performance.now(), f0: cur };
  syncAudio(true);
}
function syncAudio(force) {
  if (!ST || !au.src) return;
  const want = cur / ST.fps;
  if (playing && !buffering) {
    if (force || Math.abs(au.currentTime - want) > 0.12) { try { au.currentTime = want; } catch (e) {} }
    if (au.paused) au.play().catch(() => {});
  } else if (!au.paused) au.pause();
}
function play() {
  if (!ST || !ST.total) return;
  if (cur >= ST.total - 1) setCur(0);
  playing = true; buffering = false;
  $('bPlay').textContent = '❚❚';
  startClock();
  requestAnimationFrame(tick);
}
function pause() {
  playing = false; setBuffering(false);
  $('bPlay').textContent = '▶';
  au.pause();
  show(cur, true);
  postPlayhead();
}
function setBuffering(b) {
  if (b === buffering) return;
  buffering = b;
  $('buffering').hidden = !b;
  syncAudio(true);
}
function haveFrame(f) {
  const sc = sceneAt(f), e = frames.get(f);
  return sc && e && e.gen === sc.gen;
}
function tick() {
  if (!playing) return;
  let f = clock.f0 + Math.floor((performance.now() - clock.t0) / 1000 * ST.fps);
  if (f >= ST.total) {
    if ($('loop').checked) { setCur(0, true); startClock(); f = 0; }
    else { setCur(ST.total - 1, true); pause(); return; }
  }
  if (haveFrame(f)) {
    if (f !== painted) paint(frames.get(f).blob, f);
    if (buffering) { cur = f; setBuffering(false); clock = { t0: performance.now(), f0: f }; }
    setCur(f, true);
  } else {
    // кадр ещё не у нас: держим время и ждём
    clock = { t0: performance.now(), f0: f };
    if (cacheStr[f] === '1') { if (!pending.has(f)) fetchFrame(f, false); }
    else setBuffering(true);
    if (cur !== f) setCur(f, true);
    postPlayhead();
  }
  prefetch(f);
  if (playing) { syncAudio(false); followPlayhead(); }
  requestAnimationFrame(tick);
}
function prefetch(f) {
  for (let i = f; i < Math.min(ST.total, f + 60) && pending.size < 6; i++) {
    if (!haveFrame(i) && !pending.has(i) && cacheStr[i] === '1') fetchFrame(i, false);
  }
}
async function pollCache() {
  try {
    const r = await fetch('/api/cache');
    cacheStr = await r.text();
    drawCacheBar();
  } catch (e) {}
  setTimeout(pollCache, playing ? 350 : 900);
}
function loadAudio() {
  audioVer = ST.audio_ver;
  const wasPlaying = playing && !au.paused;
  au.src = '/api/audio.wav?v=' + audioVer;
  au.volume = +$('vol').value;
  au.load();
  if (wasPlaying) au.addEventListener('canplay', () => syncAudio(true), { once: true });
  api.get('/api/waveform').then(drawWave);
}

// ------------------------------------------------------------------ timeline
const content = $('tlContent'), scroller = $('tlScroll'), vtrack = $('vtrack');
let wave = null;
function secToX(s) { return PAD + s * pxs; }
function xToFrame(clientX) {
  const r = content.getBoundingClientRect();
  return Math.round((clientX - r.left - PAD) / pxs * ST.fps);
}
function fitZoom() {
  if (!ST || !ST.total) return;
  pxs = clamp((scroller.clientWidth - PAD - 40) / (ST.total / ST.fps), 8, 240);
  $('zoom').value = pxs;
}
function drawTimeline() {
  if (!ST) return;
  if (!pxs) fitZoom();
  const totalSec = ST.total / ST.fps;
  const width = Math.max(scroller.clientWidth, PAD + totalSec * pxs + 240);
  content.style.width = width + 'px';
  // ruler
  const ruler = $('ruler');
  let html = '';
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120];
  const major = steps.find(s => s * pxs >= 70) || 120;
  const minor = major / 5;
  for (let s = 0; s <= totalSec + major; s += minor) {
    const isMajor = Math.abs(s / major - Math.round(s / major)) < 1e-6;
    const x = secToX(s);
    if (isMajor) html += `<div class="tick" style="left:${x}px">${fmtSec(s)}</div>`;
    else if (minor * pxs >= 10) html += `<div class="tick minor" style="left:${x}px"></div>`;
  }
  ruler.innerHTML = html;
  // blocks
  vtrack.querySelectorAll('.block').forEach(b => b.remove());
  ST.scenes.forEach((s, i) => {
    const b = document.createElement('div');
    b.className = 'block' + (s.id === sel ? ' sel' : '') + (s.error ? ' err' : '');
    b.dataset.id = s.id;
    b.style.left = secToX(s.f0 / ST.fps) + 'px';
    b.style.width = Math.max(4, s.n / ST.fps * pxs - 2) + 'px';
    b.style.setProperty('--c', COLORS[i % COLORS.length]);
    const d = drafts.get(s.id);
    b.title = (s.doc || s.name) + (s.error ? '\n⚠ В сцене ошибка' : '');
    b.innerHTML = `<div class="bn">${s.error ? '⚠ ' : ''}${esc(s.name)}${d && d.dirty ? '<span class="dirty">●</span>' : ''}</div>` +
      `<div class="bd">${+(+s.dur).toFixed(2)} с</div>` +
      s.hits.filter(h => h < s.dur).map(h => `<i class="hit" style="left:${h * pxs}px"></i>`).join('') +
      `<div class="grip" title="Тяните, чтобы изменить длину"></div>`;
    vtrack.appendChild(b);
  });
  $('cacheCv').width = width; $('cacheCv').style.width = width + 'px';
  drawCacheBar();
  drawWave(wave);
  placePlayhead();
}
function fmtSec(s) {
  if (s >= 60) return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
  return (Math.round(s * 10) / 10) + 's';
}
function drawCacheBar() {
  if (!ST) return;
  const c = $('cacheCv'), g = c.getContext('2d');
  g.clearRect(0, 0, c.width, 4);
  g.fillStyle = '#2d2a26';
  g.fillRect(PAD, 0, ST.total / ST.fps * pxs, 4);
  g.fillStyle = '#86b56c';
  let run = -1;
  for (let i = 0; i <= cacheStr.length; i++) {
    if (cacheStr[i] === '1') { if (run < 0) run = i; }
    else if (run >= 0) { g.fillRect(PAD + run / ST.fps * pxs, 0, Math.max(1, (i - run) / ST.fps * pxs), 4); run = -1; }
  }
}
function drawWave(w) {
  if (w) wave = w;
  const c = $('waveCv');
  if (!ST) return;
  const width = parseFloat(content.style.width) || scroller.clientWidth;
  c.width = width; c.height = 48; c.style.width = width + 'px';
  const g = c.getContext('2d');
  g.clearRect(0, 0, c.width, c.height);
  if (!wave || !wave.peaks || !wave.peaks.length) return;
  g.fillStyle = '#6c8f5a';
  const pk = wave.peaks, rate = wave.rate, n = Math.floor(ST.total / ST.fps * pxs);
  for (let x = 0; x < n; x++) {
    const a = Math.floor(x / pxs * rate), b = Math.max(a + 1, Math.floor((x + 1) / pxs * rate));
    let m = 0;
    for (let i = a; i < b && i < pk.length; i++) m = Math.max(m, pk[i]);
    const h = Math.max(1, m * 22);
    g.fillRect(PAD + x, 24 - h, 1, h * 2);
  }
}
function placePlayhead() {
  if (!ST) return;
  $('playhead').style.left = secToX(cur / ST.fps) + 'px';
}
function followPlayhead() {
  if (!ST) return;
  const x = secToX(cur / ST.fps);
  if (x < scroller.scrollLeft + 40 || x > scroller.scrollLeft + scroller.clientWidth - 60) scroller.scrollLeft = x - 80;
}

// pointer interactions on the timeline
let drag = null;
content.addEventListener('pointerdown', e => {
  if (!ST || e.button !== 0) return;
  const blk = e.target.closest('.block');
  if (e.target.classList.contains('grip') && blk) {
    const s = sceneById(blk.dataset.id);
    drag = { kind: 'resize', el: blk, s, x0: e.clientX, dur: +s.dur };
    blk.classList.add('resizing');
    selectScene(s.id, false);
  } else if (blk) {
    drag = { kind: 'maybe-move', el: blk, id: blk.dataset.id, x0: e.clientX };
  } else {
    drag = { kind: 'scrub' };
    setCur(xToFrame(e.clientX));
  }
  content.setPointerCapture(e.pointerId);
});
content.addEventListener('pointermove', e => {
  if (!drag) return;
  if (drag.kind === 'scrub') { setCur(xToFrame(e.clientX)); return; }
  if (drag.kind === 'resize') {
    const d = Math.max(0.2, Math.round((drag.dur + (e.clientX - drag.x0) / pxs) * 10) / 10);
    drag.newDur = d;
    drag.el.style.width = Math.max(4, d * pxs - 2) + 'px';
    tip(e, d.toFixed(1) + ' с');
    return;
  }
  if (drag.kind === 'maybe-move' && Math.abs(e.clientX - drag.x0) > 6) {
    drag.kind = 'move';
    drag.el.classList.add('dragging');
    drag.mark = document.createElement('div');
    drag.mark.className = 'dropmark';
    vtrack.appendChild(drag.mark);
  }
  if (drag.kind === 'move') {
    const r = content.getBoundingClientRect();
    const x = e.clientX - r.left;
    const others = ST.scenes.filter(s => s.id !== drag.id);
    let idx = others.length;
    for (let i = 0; i < others.length; i++) {
      const s = others[i];
      const el = vtrack.querySelector(`.block[data-id="${s.id}"]`);
      const mid = el.offsetLeft + el.offsetWidth / 2;
      if (x < mid) { idx = i; break; }
    }
    drag.index = idx;
    const ref = others[idx] ? vtrack.querySelector(`.block[data-id="${others[idx].id}"]`) : null;
    const last = others[others.length - 1];
    const lx = ref ? ref.offsetLeft - 1 : (last ? (() => { const el = vtrack.querySelector(`.block[data-id="${last.id}"]`); return el.offsetLeft + el.offsetWidth + 1; })() : PAD);
    drag.mark.style.left = lx + 'px';
  }
});
content.addEventListener('pointerup', async e => {
  const d = drag; drag = null;
  hideTip();
  if (!d) return;
  if (d.kind === 'resize') {
    d.el.classList.remove('resizing');
    if (d.newDur && d.newDur !== d.dur) {
      await api.post('/api/scene/update', { id: d.s.id, dur: d.newDur });
      $('scDur').value = d.newDur;
      await refresh();
    }
  } else if (d.kind === 'move') {
    d.el.classList.remove('dragging'); d.mark.remove();
    const oldIdx = ST.scenes.findIndex(s => s.id === d.id);
    if (d.index !== undefined && d.index !== oldIdx) {
      await api.post('/api/scene/move', { id: d.id, index: d.index });
      frames.clear();
      await refresh();
      const s = sceneById(d.id); if (s) setCur(s.f0);
    }
  } else if (d.kind === 'maybe-move') {
    selectScene(d.id, true);
  }
});
content.addEventListener('dblclick', e => {
  const blk = e.target.closest('.block');
  if (blk) { const s = sceneById(blk.dataset.id); if (s) setCur(s.f0); }
});
scroller.addEventListener('wheel', e => {
  if (!e.ctrlKey && !e.metaKey) return;
  e.preventDefault();
  const r = content.getBoundingClientRect();
  const sec = (e.clientX - r.left - PAD) / pxs;
  pxs = clamp(pxs * (e.deltaY < 0 ? 1.15 : 1 / 1.15), 8, 240);
  userZoom = true;
  $('zoom').value = pxs;
  drawTimeline();
  scroller.scrollLeft = PAD + sec * pxs - (e.clientX - scroller.getBoundingClientRect().left);
}, { passive: false });
$('zoom').addEventListener('input', () => { pxs = +$('zoom').value; userZoom = true; drawTimeline(); });
$('zoom').addEventListener('dblclick', () => { userZoom = false; fitZoom(); drawTimeline(); });
let tipEl = null;
function tip(e, s) {
  if (!tipEl) { tipEl = document.createElement('div'); tipEl.className = 'durtip'; document.body.appendChild(tipEl); }
  tipEl.textContent = s; tipEl.style.left = (e.clientX + 12) + 'px'; tipEl.style.top = (e.clientY - 28) + 'px';
}
function hideTip() { if (tipEl) { tipEl.remove(); tipEl = null; } }

// ------------------------------------------------------------------ scenes / code
async function selectScene(id, seek) {
  if (sel && sel !== id) await flushDraft();
  sel = id;
  vtrack.querySelectorAll('.block').forEach(b => b.classList.toggle('sel', b.dataset.id === id));
  const s = sceneById(id);
  if (!s) return;
  if (seek && !playing && (cur < s.f0 || cur >= s.f0 + s.n)) setCur(s.f0);
  loadingCode = true;
  const d = drafts.get(id);
  if (d) ed.set(d.code);
  else {
    const r = await api.get('/api/scene?id=' + encodeURIComponent(id));
    if (sel !== id) { loadingCode = false; return; }
    drafts.set(id, { code: r.code, dirty: false });
    ed.set(r.code);
  }
  loadingCode = false;
  saveErr = null; shownErr = null;
  setSaveState('');
  updateInspector(true);
  updateErrors();
}
function updateInspector(force) {
  const s = sceneById(sel);
  if (!s) return;
  if (force || document.activeElement !== $('scName')) $('scName').value = s.name;
  if (force || document.activeElement !== $('scDur')) $('scDur').value = s.dur;
  $('scFile').textContent = 'scenes/' + s.file;
}
function setSaveState(t, cls) { const el = $('saveState'); el.textContent = t; el.className = 'save-state ' + (cls || ''); }
ed.onChange(() => {
  if (loadingCode || !sel) return;
  const d = drafts.get(sel) || {};
  const wasDirty = d.dirty;
  drafts.set(sel, { code: ed.get(), dirty: true });
  setSaveState('Изменено');
  if (!wasDirty) markDirtyBlock(sel, true);
  if ($('autoSave').checked) autoSave();
});
const autoSave = debounce(() => saveCode(), 900);
function markDirtyBlock(id, on) {
  const b = vtrack.querySelector(`.block[data-id="${id}"] .bn`);
  if (!b) return;
  const dot = b.querySelector('.dirty');
  if (on && !dot) b.insertAdjacentHTML('beforeend', '<span class="dirty">●</span>');
  if (!on && dot) dot.remove();
}
async function flushDraft() {
  const d = drafts.get(sel);
  if (d && d.dirty) await saveCode();
}
let saving = false, saveAgain = false;
async function saveCode() {
  if (!sel) return;
  if (saving) { saveAgain = true; return; }
  const id = sel, code = ed.get();
  saving = true;
  setSaveState('Сохраняю…');
  try {
    const r = await api.post('/api/scene/save', { id, code });
    const d = drafts.get(id);
    if (d && d.code === code) d.dirty = false;
    markDirtyBlock(id, false);
    saveErr = r.syntax ? { msg: r.syntax.msg, line: r.syntax.line } : null;
    shownErr = null;
    if (r.syntax) setSaveState('Ошибка в коде — см. ниже', 'bad');
    else if (r.error) setSaveState('Ошибка — см. ниже', 'bad');
    else setSaveState('Сохранено ✓', 'ok');
    await refresh();
    updateErrors();
    const s = sceneById(id);
    if (s && !playing && (cur < s.f0 || cur >= s.f0 + s.n)) setCur(s.f0 + Math.min(s.n - 1, Math.round(s.n * 0.4)));
    else if (!playing) show(cur, true);
  } catch (e) { setSaveState('Не удалось сохранить', 'bad'); }
  saving = false;
  if (saveAgain) { saveAgain = false; saveCode(); }
}
$('saveBtn').onclick = () => saveCode();
function showError(msg, line) {
  const box = $('errBox');
  if (!msg) { box.hidden = true; ed.mark(null); return; }
  box.hidden = false;
  const s = sceneById(sel);
  const fname = s ? s.file : '';
  box.innerHTML = esc(msg).replace(/line (\d+)/g, (m, n) => `<span class="ln" data-ln="${n}">line ${n}</span>`)
    .replace(/\(строка (\d+)\)/g, (m, n) => `(<span class="ln" data-ln="${n}">строка ${n}</span>)`);
  let ln = line;
  if (!ln && fname) {
    const re = new RegExp(fname.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '", line (\\d+)', 'g');
    let m, lastLn = null;
    while ((m = re.exec(msg))) lastLn = +m[1];
    ln = lastLn;
  }
  ed.mark(ln);
}
$('errBox').addEventListener('click', e => { const t = e.target.closest('.ln'); if (t) ed.goto(+t.dataset.ln); });
let saveErr = null, shownErr = null;
function updateErrors() {
  const s = sceneById(sel);
  if (!s) return;
  const msg = saveErr ? saveErr.msg : (s.error || '');
  const st = $('saveState');
  if (!saveErr) {
    if (s.error && !st.classList.contains('bad')) setSaveState('Ошибка при рендере — см. ниже', 'bad');
    if (!s.error && st.classList.contains('bad')) setSaveState('Исправлено ✓', 'ok');
  }
  if (msg === shownErr) return;
  shownErr = msg;
  showError(msg || null, saveErr ? saveErr.line : null);
}
$('scName').addEventListener('change', async () => { await api.post('/api/scene/update', { id: sel, name: $('scName').value }); refresh(); });
$('scDur').addEventListener('change', async () => {
  const v = parseFloat($('scDur').value);
  if (!(v > 0)) return;
  await api.post('/api/scene/update', { id: sel, dur: v }); refresh();
});

// add / duplicate / delete
$('addBtn').onclick = e => { e.stopPropagation(); const m = $('addMenu'); m.hidden = !m.hidden; if (!m.hidden) $('newName').select(); };
document.addEventListener('click', e => { if (!e.target.closest('.add-wrap')) $('addMenu').hidden = true; });
$('addMenu').querySelectorAll('button[data-tpl]').forEach(b => b.onclick = async () => {
  $('addMenu').hidden = true;
  await flushDraft();
  const r = await api.post('/api/scene/add', { after: sel, template: b.dataset.tpl, name: $('newName').value.trim() || 'New scene' });
  await refresh();
  const s = sceneById(r.id);
  if (s) { await selectScene(r.id, false); setCur(s.f0 + Math.round(s.n * 0.5)); switchTab('code'); }
  toast('Сцена добавлена. Меняйте код справа — превью обновится само.');
});
$('dupBtn').onclick = async () => {
  if (!sel) return;
  await flushDraft();
  const r = await api.post('/api/scene/duplicate', { id: sel });
  await refresh();
  await selectScene(r.id, true);
};
$('delBtn').onclick = async () => {
  const s = sceneById(sel);
  if (!s) return;
  if (!confirm(`Удалить сцену «${s.name}»?\nФайл переместится в папку scenes/_trash — его можно будет вернуть.`)) return;
  const idx = ST.scenes.indexOf(s);
  drafts.delete(s.id);
  await api.post('/api/scene/delete', { id: s.id });
  sel = null;
  frames.clear();
  await refresh();
  const next = ST.scenes[Math.min(idx, ST.scenes.length - 1)];
  if (next) selectScene(next.id, true);
};

// ------------------------------------------------------------------ texts
const pushText = debounce(async (k, v, row) => {
  await api.post('/api/texts', { [k]: v });
  row.classList.add('saved');
  setTimeout(() => row.classList.remove('saved'), 700);
  refresh();
}, 450);
function renderTexts(force) {
  if (!ST) return;
  const list = $('textsList');
  const q = $('textSearch').value.trim().toLowerCase();
  const sig = JSON.stringify([ST.scenes.map(s => [s.id, s.name, s.used]), Object.keys(ST.texts), q]);
  if (!force && sig === lastTextSig) {
    // только обновить значения в полях, не трогая активное
    list.querySelectorAll('input[data-k]').forEach(inp => {
      if (document.activeElement !== inp && ST.texts[inp.dataset.k] !== undefined && inp.value !== ST.texts[inp.dataset.k]) inp.value = ST.texts[inp.dataset.k];
    });
    return;
  }
  if (list.contains(document.activeElement)) return;
  lastTextSig = sig;
  const seen = new Set();
  let html = '';
  const match = k => !q || k.toLowerCase().includes(q) || String(ST.texts[k]).toLowerCase().includes(q);
  const row = k => `<div class="trow"><span title="${esc(k)}">${esc(k)}</span><input data-k="${esc(k)}" value="${esc(ST.texts[k])}" spellcheck="false"></div>`;
  for (const s of ST.scenes) {
    const keys = (s.used || []).filter(k => k in ST.texts && match(k));
    if (!keys.length) continue;
    html += `<div class="tgroup"><h4>${esc(s.name)} <button class="ghost" data-go="${s.id}">показать</button></h4>` + keys.map(k => { seen.add(k); return row(k); }).join('') + '</div>';
  }
  const rest = Object.keys(ST.texts).filter(k => !seen.has(k) && match(k));
  if (rest.length) html += `<div class="tgroup"><h4>Другие</h4>${rest.map(row).join('')}</div>`;
  if (!html) html = '<p class="hint">Ничего не найдено.</p>';
  list.innerHTML = html;
}
$('textsList').addEventListener('input', e => {
  const inp = e.target.closest('input[data-k]');
  if (inp) { ST.texts[inp.dataset.k] = inp.value; pushText(inp.dataset.k, inp.value, inp.parentElement); }
});
$('textsList').addEventListener('click', e => {
  const b = e.target.closest('[data-go]');
  if (b) { const s = sceneById(b.dataset.go); if (s) { selectScene(s.id, false); setCur(s.f0 + Math.round(s.n * 0.6)); } }
});
$('textSearch').addEventListener('input', () => renderTexts(true));

// ------------------------------------------------------------------ assets
async function loadAssets() {
  const list = await api.get('/api/assets');
  $('assetGrid').innerHTML = list.map(a => `<div class="asset" data-name="${esc(a.name)}" data-alpha="${a.alpha ? 1 : 0}" title="${esc(a.file)}">
    <div class="th"><img loading="lazy" src="/api/thumb?name=${encodeURIComponent(a.name)}&v=${a.mtime}" alt=""></div>
    <div class="nm">${esc(a.name)}</div><div class="kind">${a.alpha ? 'sprite' : 'image'}</div></div>`).join('');
}
$('assetGrid').addEventListener('click', e => {
  const a = e.target.closest('.asset');
  if (!a) return;
  const snip = a.dataset.alpha === '1' ? `sprite('${a.dataset.name}')` : `image('${a.dataset.name}')`;
  switchTab('code');
  ed.insert(snip);
  toast(`Вставлено в код: <code>${esc(snip)}</code>`, 2500);
});
async function uploadImages(files) {
  const cut = $('cutout').checked ? 1 : 0;
  let n = 0;
  for (const f of files) {
    if (!/^image\//.test(f.type)) continue;
    const r = await api.raw(`/api/assets/upload?name=${encodeURIComponent(f.name)}&cutout=${cut}`, f);
    if (r.error) toast('Ошибка: ' + esc(r.error)); else n++;
  }
  if (n) toast(`Добавлено картинок: ${n}`);
  loadAssets();
}
$('assetFile').addEventListener('change', e => { uploadImages([...e.target.files]); e.target.value = ''; });
const at = $('tab-assets');
at.addEventListener('dragover', e => { e.preventDefault(); at.classList.add('drop'); });
at.addEventListener('dragleave', () => at.classList.remove('drop'));
at.addEventListener('drop', e => { e.preventDefault(); at.classList.remove('drop'); uploadImages([...e.dataTransfer.files]); });
$('openAssets').onclick = () => api.post('/api/open', { what: 'assets' });

// ------------------------------------------------------------------ settings
let settingsInit = false;
function updateSettings() {
  const L = ST.look, A = ST.audio;
  const act = document.activeElement;
  const setv = (id, v) => { if (act !== $(id)) $(id).value = v; };
  $('lkLetter').checked = L.letterbox !== false;
  $('lkVig').checked = L.vignette !== false;
  $('lkHits').checked = L.hits !== false;
  setv('lkGrain', L.grain ?? 0.07); $('lkGrainV').textContent = (+(L.grain ?? 0.07)).toFixed(2);
  $('auGen').checked = A.generated !== false;
  setv('auGenVol', A.generated_volume ?? 1); $('auGenVolV').textContent = (+(A.generated_volume ?? 1)).toFixed(2);
  setv('auMusVol', A.music_volume ?? 0.8); $('auMusVolV').textContent = (+(A.music_volume ?? 0.8)).toFixed(2);
  setv('auMusOff', A.music_offset ?? 0);
  setv('auFade', A.fade_out ?? 1.5);
  $('musicName').textContent = A.music_file || 'нет';
  setv('fps', ST.fps);
  $('projDir').textContent = ST.dir;
  if (!settingsInit) {
    settingsInit = true;
    const look = (k, v) => api.post('/api/look', { [k]: v }).then(refresh);
    const aud = (k, v) => api.post('/api/audio', { [k]: v }).then(refresh);
    $('lkLetter').onchange = e => look('letterbox', e.target.checked);
    $('lkVig').onchange = e => look('vignette', e.target.checked);
    $('lkHits').onchange = e => look('hits', e.target.checked);
    $('lkGrain').onchange = e => look('grain', +e.target.value);
    $('lkGrain').oninput = e => { $('lkGrainV').textContent = (+e.target.value).toFixed(2); };
    $('auGen').onchange = e => aud('generated', e.target.checked);
    $('auGenVol').onchange = e => aud('generated_volume', +e.target.value);
    $('auGenVol').oninput = e => { $('auGenVolV').textContent = (+e.target.value).toFixed(2); };
    $('auMusVol').onchange = e => aud('music_volume', +e.target.value);
    $('auMusVol').oninput = e => { $('auMusVolV').textContent = (+e.target.value).toFixed(2); };
    $('auMusOff').onchange = e => aud('music_offset', +e.target.value || 0);
    $('auFade').onchange = e => aud('fade_out', Math.max(0, +e.target.value || 0));
    $('musicFile').onchange = async e => {
      const f = e.target.files[0]; e.target.value = '';
      if (!f) return;
      toast('Загружаю музыку…', 0);
      const r = await api.raw('/api/music/upload?name=' + encodeURIComponent(f.name), f);
      toast(r.error ? 'Ошибка: ' + esc(r.error) : 'Музыка добавлена. Звук пересводится…');
      refresh();
    };
    $('musicRemove').onclick = () => aud('music_file', null);
    $('fps').onchange = async e => { await api.post('/api/project', { fps: +e.target.value }); frames.clear(); pxs = 0; lastSig = ''; await refresh(); };
    document.querySelectorAll('[data-open]').forEach(b => b.onclick = () => api.post('/api/open', { what: b.dataset.open }));
  }
}
$('title').addEventListener('change', () => api.post('/api/project', { title: $('title').value }));

// ------------------------------------------------------------------ export
$('exportBtn').onclick = async () => {
  await flushDraft();
  const r = await api.post('/api/export', { crf: 18 });
  if (r.ok) toast('Экспорт начался. Превью на это время приостановлено.');
  refresh();
};
$('xcancel').onclick = () => api.post('/api/export/cancel').then(refresh);
function updateExport() {
  const x = ST.export || {};
  const running = x.state === 'running';
  $('exportProgress').hidden = !running;
  $('exportBtn').disabled = running;
  if (running) {
    $('xfill').style.width = Math.round((x.progress || 0) * 100) + '%';
    const eta = x.eta ? ` · осталось ~${Math.ceil(x.eta / 60) > 1 ? Math.ceil(x.eta / 60) + ' мин' : Math.ceil(x.eta) + ' с'}` : '';
    $('xtext').textContent = `${x.msg || ''} ${Math.round((x.progress || 0) * 100)}%${eta}`;
  }
  const key = x.state + (x.file || x.msg || '');
  if (lastExportSeen === null) { lastExportSeen = key; return; }
  if (key === lastExportSeen) return;
  lastExportSeen = key;
  if (x.state === 'done') {
    toast(`<b>Видео готово</b> за ${x.seconds} с: ${esc(x.file)}
      <div class="acts"><a href="/exports/${encodeURIComponent(x.file)}" target="_blank">Смотреть</a>
      <a href="/exports/${encodeURIComponent(x.file)}?dl=1">Скачать</a>
      <a href="#" id="openEx">Открыть папку</a></div>`, 0);
    const o = $('openEx'); if (o) o.onclick = ev => { ev.preventDefault(); api.post('/api/open', { what: 'exports' }); };
  } else if (x.state === 'error') {
    toast(`<b style="color:var(--red)">Экспорт не удался</b><pre class="err" style="max-height:200px">${esc(x.msg)}</pre>`, 0);
  }
}
$('toast').addEventListener('dblclick', () => { $('toast').hidden = true; });

// ------------------------------------------------------------------ tabs, keys, transport
function switchTab(name) {
  document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.id === 'tab-' + name));
  if (name === 'code') setTimeout(() => ed.refresh(), 0);
  if (name === 'assets') loadAssets();
  if (name === 'texts') renderTexts(true);
}
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => switchTab(b.dataset.tab));
$('helpBody').innerHTML = window.HELP_HTML || '';

$('bPlay').onclick = () => playing ? pause() : play();
$('bStart').onclick = () => setCur(0);
$('bEnd').onclick = () => setCur(ST.total - 1);
$('bPrev').onclick = () => { if (playing) pause(); setCur(cur - 1); };
$('bNext').onclick = () => { if (playing) pause(); setCur(cur + 1); };
$('vol').oninput = () => { au.volume = +$('vol').value; };

document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveCode(); return; }
  const t = e.target;
  const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable || (t.closest && t.closest('.CodeMirror')));
  if (typing || !ST) return;
  if (e.code === 'Space') { e.preventDefault(); playing ? pause() : play(); }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); if (playing) pause(); setCur(cur - (e.shiftKey ? ST.fps : 1)); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); if (playing) pause(); setCur(cur + (e.shiftKey ? ST.fps : 1)); }
  else if (e.key === 'Home') setCur(0);
  else if (e.key === 'End') setCur(ST.total - 1);
});
window.addEventListener('resize', () => { if (!userZoom) fitZoom(); drawTimeline(); });
window.addEventListener('beforeunload', () => { const d = drafts.get(sel); if (d && d.dirty) navigator.sendBeacon && fetch('/api/scene/save', { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: sel, code: d.code }) }); });

function init() {
  fitZoom();
  setCur(0);
  pollCache();
  if (!window.CodeMirror) toast('Редактор кода работает в простом режиме (нет интернета для подсветки).', 5000);
}
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 800);
})();
