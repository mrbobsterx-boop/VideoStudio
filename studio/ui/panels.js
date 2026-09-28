(() => {
'use strict';
const X = window.SX;
const { $, api, esc, toast, debounce, icon } = X;

// ================================================================== общие поля форм
const num = (v, d) => (v === null || v === undefined || v === '' || isNaN(+v)) ? d : +v;
function fRange(k, label, v, min, max, step, fmt) {
  const f = fmt || (x => (+x).toFixed(step < 0.1 ? 2 : step < 1 ? 1 : 0));
  return `<label class="f"><span>${label}<i data-v="${k}">${f(v)}</i></span><input type="range" data-k="${k}" min="${min}" max="${max}" step="${step}" value="${v}" data-fmt="${step}"></label>`;
}
function fNum(k, label, v, step, ph) {
  return `<label class="f"><span>${label}</span><input type="number" data-k="${k}" step="${step || 0.1}" value="${v === null || v === undefined ? '' : v}" placeholder="${ph || ''}"></label>`;
}
function fSel(k, label, v, opts, wide) {
  return `<label class="f${wide ? ' wide' : ''}"><span>${label}</span><select data-k="${k}">${opts.map(o => {
    if (o.group) return `<optgroup label="${esc(o.group)}">${o.items.map(i => `<option value="${esc(i[0])}"${String(i[0]) === String(v) ? ' selected' : ''}>${esc(i[1])}</option>`).join('')}</optgroup>`;
    return `<option value="${esc(o[0])}"${String(o[0]) === String(v) ? ' selected' : ''}>${esc(o[1])}</option>`;
  }).join('')}</select></label>`;
}
function fChk(k, label, v) { return `<label class="f chkf"><input type="checkbox" data-k="${k}"${v ? ' checked' : ''}> ${label}</label>`; }
function readField(el) {
  if (el.type === 'checkbox') return el.checked;
  if (el.type === 'range' || el.type === 'number') return el.value === '' ? null : +el.value;
  return el.value;
}
function fmtVal(el) {
  const step = +el.dataset.fmt;
  return (+el.value).toFixed(step < 0.1 ? 2 : step < 1 ? 1 : 0);
}

// ================================================================== медиа (список файлов)
let ASSETS = [];
const KIND_LABEL = { video: 'видео', image: 'картинка', sprite: 'вырезанный', audio: 'музыка / звук' };
const KIND_TABS = [['all', 'Все'], ['video', 'Видео'], ['image', 'Картинки'], ['sprite', 'Вырезанные'], ['audio', 'Музыка']];
const fmtDur = d => d >= 60 ? `${Math.floor(d / 60)}:${String(Math.round(d % 60)).padStart(2, '0')}` : `${(+d).toFixed(1)} с`;
const baseName = n => n.split('/').pop();
async function loadAssets() {
  ASSETS = await api.get('/api/assets');
  if (!Array.isArray(ASSETS)) ASSETS = [];
  if (mediaTab) mediaTab.refresh();
  return ASSETS;
}
X.loadAssets = loadAssets;
X.assets = () => ASSETS;

// общий плеер для прослушивания треков в сетках
const pv = new Audio();
let pvRef = null;
function playAudio(ref, btn) {
  document.querySelectorAll('.mtile .playbtn.on').forEach(b => { b.classList.remove('on'); b.innerHTML = icon('play'); });
  if (pvRef === ref && !pv.paused) { pv.pause(); pvRef = null; return; }
  pv.src = '/api/audiofile?ref=' + encodeURIComponent(ref); pv.play().catch(() => {}); pvRef = ref;
  if (btn) { btn.classList.add('on'); btn.innerHTML = icon('pause'); }
}
pv.onended = () => { pvRef = null; document.querySelectorAll('.mtile .playbtn.on').forEach(b => { b.classList.remove('on'); b.innerHTML = icon('play'); }); };
X.stopAudioPreview = () => { pv.pause(); pvRef = null; };

/* Визуальный выбор медиа: папки, типы, поиск, сетка с превью.
   opts: kinds — какие типы показывать; mode: 'multi' | 'single' | 'action';
         selected — Set имён; filter(item) — доп. отбор; onChange(set); onAction(item, event) */
function mediaPicker(host, opts = {}) {
  const kinds = opts.kinds || ['video', 'image', 'sprite', 'audio'];
  const mode = opts.mode || 'multi';
  const sel = opts.selected || new Set();
  let folder = '*', kind = opts.kind || 'all', q = '';
  host.classList.add('mpicker');
  const items = () => (opts.items ? opts.items() : ASSETS).filter(a => kinds.includes(a.kind) && (!opts.filter || opts.filter(a)));
  function visible() {
    return items().filter(a => (folder === '*' || a.folder === folder) && (kind === 'all' || a.kind === kind) &&
      (!q || a.name.toLowerCase().includes(q)));
  }
  function render() {
    const all = items();
    const folders = [...new Set(all.map(a => a.folder))].sort((a, b) => (a === '') - (b === '') || a.localeCompare(b));
    const count = k => all.filter(a => (folder === '*' || a.folder === folder) && (k === 'all' || a.kind === k)).length;
    const tabs = KIND_TABS.filter(([k]) => k === 'all' || kinds.includes(k)).filter(([k]) => k === 'all' || count(k));
    const vis = visible();
    host.innerHTML = `<div class="mp-bar">
      ${folders.length > 1 || (folders[0] && folders[0] !== '') ? `<div class="chips">${[['*', 'Все папки']].concat(folders.map(f => [f, f || 'Без папки'])).map(([f, l]) =>
        `<button class="chip ${folder === f ? 'on' : ''}" data-folder="${esc(f)}">${f === '*' ? icon('lib') : icon('folder')}${esc(l)}</button>`).join('')}</div>` : ''}
      <div class="mp-row"><div class="seg-tabs flat">${tabs.map(([k, l]) => `<button data-kind="${k}" class="${kind === k ? 'on' : ''}">${l} <i>${count(k)}</i></button>`).join('')}</div>
        <input class="search mp-q" placeholder="Поиск по имени…" value="${esc(q)}">
        ${mode === 'multi' ? `<span class="mp-sel">выбрано <b>${[...sel].filter(n => all.some(a => a.name === n)).length}</b></span>
          <button class="ghost small" data-all="1">Выбрать видимые</button><button class="ghost small" data-all="0">Снять</button>` : ''}</div></div>
      <div class="asset-grid">${vis.map(tile).join('') || '<div class="empty" style="grid-column:1/-1"><b>Здесь пусто</b>Добавьте файлы или выберите другую папку</div>'}</div>`;
    const qi = host.querySelector('.mp-q');
    qi.oninput = () => { q = qi.value.trim().toLowerCase(); const pos = qi.selectionStart; render(); const n = host.querySelector('.mp-q'); n.focus(); n.setSelectionRange(pos, pos); };
  }
  function tile(a) {
    const on = mode !== 'action' && sel.has(a.name);
    const meta = a.kind === 'audio' ? fmtDur(a.dur || 0) : (a.w ? `${a.w}×${a.h}` : '');
    const th = a.kind === 'audio'
      ? `<div class="th audio">${icon('volume')}<button class="playbtn" data-play="${esc(a.ref)}" title="Послушать">${icon('play')}</button></div>`
      : `<div class="th"><img loading="lazy" src="/api/thumb?name=${encodeURIComponent(a.name)}&v=${a.mtime}" alt=""></div>`;
    return `<div class="asset mtile ${on ? 'on' : ''}" data-name="${esc(a.name)}" data-kind="${a.kind}" title="${esc(a.name)}">
      ${th}${a.kind === 'video' ? `<span class="dur">${fmtDur(a.dur || 0)}</span>` : ''}${mode !== 'action' ? `<span class="tick">${icon('check')}</span>` : ''}
      ${a.is_music ? '<span class="musictag">♪ в ролике</span>' : ''}
      <div class="nm">${esc(baseName(a.name))}</div><div class="kind"><b>${KIND_LABEL[a.kind]}</b>${meta}</div></div>`;
  }
  host.addEventListener('click', e => {
    const pb = e.target.closest('[data-play]');
    if (pb) { e.stopPropagation(); playAudio(pb.dataset.play, pb); return; }
    const f = e.target.closest('[data-folder]'); if (f) { folder = f.dataset.folder; render(); return; }
    const k = e.target.closest('[data-kind]'); if (k && k.tagName === 'BUTTON') { kind = k.dataset.kind; render(); return; }
    const all = e.target.closest('[data-all]');
    if (all) { visible().forEach(a => all.dataset.all === '1' ? sel.add(a.name) : sel.delete(a.name)); render(); opts.onChange && opts.onChange(sel); return; }
    const t = e.target.closest('.mtile'); if (!t) return;
    const item = items().find(a => a.name === t.dataset.name);
    if (!item) return;
    if (mode === 'action') { opts.onAction && opts.onAction(item, e); return; }
    if (mode === 'single') { const was = sel.has(item.name); sel.clear(); if (!was) sel.add(item.name); }
    else sel.has(item.name) ? sel.delete(item.name) : sel.add(item.name);
    render(); opts.onChange && opts.onChange(sel, item);
  });
  render();
  return { refresh: render, selected: () => sel };
}
X.mediaPicker = mediaPicker;

// ---------------- вкладка «Медиа»
let mediaTab = null;
function initMediaTab() {
  mediaTab = mediaPicker($('assetGrid'), {
    mode: 'action',
    onAction: async (a, e) => {
      if (a.kind === 'audio') {
        if (a.is_music) return toast('Этот трек уже звучит в ролике. Громкость и сдвиг — в «Настройках».');
        if (!confirm(`Сделать «${baseName(a.name)}» музыкой ролика?`)) return;
        const r = await api.post('/api/audio', { music_file: a.ref });
        toast(r.error ? 'Ошибка: ' + esc(r.error) : 'Музыка ролика заменена. Звук пересводится…');
        X.refresh(); loadAssets(); return;
      }
      if (e.altKey) {
        const snip = a.kind === 'video' ? `video('${a.name}', t)` : a.kind === 'sprite' ? `sprite('${a.name}')` : `image('${a.name}')`;
        X.switchTab('code'); X.ed.insert(snip);
        toast(`Вставлено в код: <code>${esc(snip)}</code>`, 2500);
        return;
      }
      if (!X.sel) return toast('Сначала выберите сцену на таймлайне');
      addLayer(a.kind === 'video' ? 'video' : 'image', a.name, a.kind === 'sprite');
    },
  });
}
const MEDIA_RE = /\.(mp4|mov|webm|mkv|m4v|avi|png|jpe?g|webp|mp3|wav|ogg|m4a|aac|flac)$/i;
async function uploadFiles(list) {
  // list: [{file, folder}]
  const cut = $('cutout').checked ? 1 : 0;
  const box = $('uploadProg'), bar = box.querySelector('i'), lab = box.querySelector('span');
  let n = 0, i = 0;
  const todo = list.filter(x => MEDIA_RE.test(x.file.name));
  const skipped = list.length - todo.length;
  for (const { file: f, folder } of todo) {
    i++;
    const isImg = /\.(png|jpe?g|webp)$/i.test(f.name);
    box.hidden = false; bar.style.width = '0%';
    const label = `${todo.length > 1 ? `(${i}/${todo.length}) ` : ''}${folder ? folder + '/' : ''}${f.name}`;
    lab.textContent = 'Загружаю ' + label;
    const r = await api.upload(`/api/assets/upload?name=${encodeURIComponent(f.name)}&cutout=${isImg ? cut : 0}&folder=${encodeURIComponent(folder || '')}`, f,
      p => { bar.style.width = Math.round(p * 100) + '%'; lab.textContent = `Загружаю ${label} — ${Math.round(p * 100)}%`; });
    if (r.error) toast('Ошибка: ' + esc(r.error)); else n++;
  }
  box.hidden = true;
  if (n) toast(`Добавлено файлов: ${n}${skipped ? ` (пропущено неподходящих: ${skipped})` : ''}. Нажмите на файл, чтобы поставить его в сцену.`);
  else if (skipped) toast('В папке нет картинок, видео или музыки');
  await loadAssets();
}
X.uploadFiles = uploadFiles;
$('assetFile').addEventListener('change', e => { uploadFiles([...e.target.files].map(file => ({ file, folder: '' }))); e.target.value = ''; });
$('assetDir').addEventListener('change', e => {
  const files = [...e.target.files]; e.target.value = '';
  uploadFiles(files.map(file => ({ file, folder: (file.webkitRelativePath || '').split('/')[0] || '' })));
});
// перетаскивание файлов и целых папок
async function readEntry(entry, folder, out) {
  if (entry.isFile) { await new Promise(res => entry.file(f => { out.push({ file: f, folder }); res(); }, res)); return; }
  if (entry.isDirectory) {
    const reader = entry.createReader();
    let batch;
    do {
      batch = await new Promise(res => reader.readEntries(res, () => res([])));
      for (const e of batch) await readEntry(e, folder || entry.name, out);
    } while (batch.length);
  }
}
const at = $('tab-assets');
at.addEventListener('dragover', e => { e.preventDefault(); at.classList.add('drop'); });
at.addEventListener('dragleave', () => at.classList.remove('drop'));
at.addEventListener('drop', async e => {
  e.preventDefault(); at.classList.remove('drop');
  const items = [...(e.dataTransfer.items || [])].map(it => it.webkitGetAsEntry && it.webkitGetAsEntry()).filter(Boolean);
  if (!items.length) return uploadFiles([...e.dataTransfer.files].map(file => ({ file, folder: '' })));
  const out = [];
  for (const en of items) await readEntry(en, en.isDirectory ? en.name : '', out);
  uploadFiles(out);
});
$('openAssets').onclick = () => api.post('/api/open', { what: 'assets' }).then(r => toast(r.error ? esc(r.error) : 'Папка открыта:<div class="path">' + esc(r.path) + '</div>'));

// ================================================================== шрифты
let FONTS = { fonts: [], roles: {} };
async function loadFonts() {
  FONTS = await api.get('/api/fonts');
  X.fonts = FONTS;
  const opts = FONTS.fonts.map(f => [f.name, `${f.family} ${f.style}`.trim() + ` (${f.name})`]);
  const roles = [['title', 'Заголовки'], ['serif', 'Курсив / цитаты'], ['text', 'Обычный текст']];
  const sample = { title: 'ЗАГОЛОВОК 2026', serif: 'Тихая строка истории', text: 'Обычный текст, подписи' };
  $('fontRoles').innerHTML = roles.map(([r, lab]) => `<div class="frole"><span>${lab}</span>
    <select class="select" data-role="${r}">${opts.map(o => `<option value="${esc(o[0])}"${FONTS.roles[r] === o[0] ? ' selected' : ''}>${esc(o[1])}</option>`).join('')}</select>
    <img alt="" src="/api/font/sample?name=${encodeURIComponent(FONTS.roles[r] || '')}&size=30&text=${encodeURIComponent(sample[r])}"></div>`).join('');
  $('fontList').innerHTML = FONTS.fonts.map(f => `<div class="fitem"><span class="fname" title="${esc(f.file)}">${esc(f.name)}${f.weights ? ` · ${f.weights[0]}–${f.weights[1]}` : ''}</span>
    <img alt="" loading="lazy" src="/api/font/sample?name=${encodeURIComponent(f.name)}&size=26&text=${encodeURIComponent('Съешь ещё этих булок · Shelter 123')}"></div>`).join('');
}
$('fontRoles').addEventListener('change', async e => {
  const s = e.target.closest('select[data-role]'); if (!s) return;
  const r = await api.post('/api/fonts', { [s.dataset.role]: s.value });
  if (r.error) toast('Ошибка: ' + esc(r.error)); else toast('Шрифт изменён во всём ролике. Превью пересчитывается…');
  loadFonts(); X.refresh();
});
$('fontFile').addEventListener('change', async e => {
  const files = [...e.target.files]; e.target.value = '';
  for (const f of files) {
    const r = await api.upload('/api/fonts/upload?name=' + encodeURIComponent(f.name), f);
    toast(r.error ? 'Ошибка: ' + esc(r.error) : `Шрифт «${esc(r.name)}» добавлен — выберите его для нужной роли`);
  }
  loadFonts();
});

// ================================================================== эффекты: каталог
let FX = [];
const fxByName = n => FX.find(e => e.name === n);
async function loadFx() {
  FX = (await api.get('/api/fx')).effects || [];
  X.fxCatalog = FX;
  const groups = {};
  FX.forEach(e => (groups[e.group] = groups[e.group] || []).push(e));
  $('fxAdd').innerHTML = '<option value="">+ Добавить эффект…</option>' +
    '<optgroup label="Наборы (несколько эффектов сразу)">' + PRESETS.map((p, i) => `<option value="preset:${i}">✦ ${esc(p.label)}</option>`).join('') + '</optgroup>' +
    Object.entries(groups).map(([g, list]) => `<optgroup label="${esc(g)}">${list.map(e => `<option value="${e.name}">${esc(e.label)}</option>`).join('')}</optgroup>`).join('');
}
const PRESETS = [
  { label: 'Кино: цвет + плавные вход и уход', fx: [{ name: 'grade', preset: 'teal_orange', strength: 0.75 }, { name: 'fade_in', dur: 0.4 }, { name: 'fade_out', dur: 0.4 }] },
  { label: 'Медленный наезд + пыль', fx: [{ name: 'zoom', amount: 0.08, ease: 'inout' }, { name: 'dust', amount: 0.35 }] },
  { label: 'Воспоминание: тёплый плёночный', fx: [{ name: 'grade', preset: 'faded', strength: 0.8 }, { name: 'light_leak', color: 'warm', amount: 0.5 }, { name: 'blur_in', dur: 0.6, amount: 10 }, { name: 'vignette', amount: 0.4 }] },
  { label: 'Нуар: ч/б + виньетка', fx: [{ name: 'grade', preset: 'noir', strength: 1 }, { name: 'vignette', amount: 0.55 }] },
  { label: 'Удар на входе: вспышка + наезд', fx: [{ name: 'flash_in', dur: 0.25, amount: 0.8 }, { name: 'punch_in', dur: 0.35, amount: 0.16 }] },
  { label: 'Кибер: глитч + RGB', fx: [{ name: 'grade', preset: 'night', strength: 0.6 }, { name: 'glitch', amount: 0.5, rate: 1.5 }, { name: 'rgb_split', amount: 3 }] },
  { label: 'Кассета VHS', fx: [{ name: 'grade', preset: 'faded', strength: 0.6 }, { name: 'vhs', amount: 0.6 }] },
  { label: 'Тревога: тряска + холод', fx: [{ name: 'grade', preset: 'cold', strength: 0.8 }, { name: 'handheld', amount: 1.4 }, { name: 'vignette', amount: 0.5 }] },
];
function fxDefaults(name) { const e = fxByName(name); const o = { name, on: true }; if (e) e.params.forEach(p => { o[p.k] = p.default; }); return o; }

// ================================================================== слои и эффекты выбранной сцены
let curSid = null;
let layers = [];          // локальная копия слоёв выбранной сцены
let effects = [];         // локальная копия эффектов
let openIds = new Set();
let fxOpen = new Set();
let structSig = '';
let seq = 0, acked = 0, sending = false;   // правки, ещё не подтверждённые сервером, не затираем
const push = debounce(async () => {
  if (!curSid) return;
  const sid = curSid, my = seq;
  sending = true;
  const r = await api.post('/api/scene/update', { id: sid, layers, fx: effects });
  sending = false;
  if (r.error) toast('Ошибка: ' + esc(r.error));
  acked = my;
  // сервер выдал новым слоям id и ключи текстов — подтянуть, не теряя открытых карточек
  const st = await api.get('/api/state');
  const s = st && st.scenes && st.scenes.find(x => x.id === sid);
  if (s && sid === curSid && seq === my) {
    s.layers.forEach((L, i) => {
      const loc = layers[i];
      if (loc && !loc.id && L.id) { if (openIds.has('new' + i)) { openIds.delete('new' + i); openIds.add(L.id); } loc.id = L.id; loc.key = L.key; }
    });
    renderLayers();
  }
  X.refresh();
}, 280);
const busy = () => seq !== acked || sending;

function syncFromState(force) {
  const s = X.sceneById(X.sel);
  if (!s) { curSid = null; layers = []; effects = []; renderLayers(); renderFx(); return; }
  if (s.id === curSid && busy()) return;                 // свои правки ещё в пути
  const sig = s.id + JSON.stringify(s.layers) + JSON.stringify(s.fx);
  if (!force && s.id === curSid && sig === structSig) return;
  if (s.id !== curSid) { openIds = new Set(); fxOpen = new Set(); }
  curSid = s.id; structSig = sig;
  layers = JSON.parse(JSON.stringify(s.layers));
  effects = JSON.parse(JSON.stringify(s.fx));
  renderLayers(); renderFx();
}
X.hooks.select.push(() => syncFromState(true));
X.hooks.state.push(() => {
  const act = document.activeElement;
  const editing = act && (act.closest('#layerList') || act.closest('#fxList'));
  if (!editing) syncFromState(false);
});
function changed() { seq++; push(); }

// ---------------- слои
const MOTIONS = [['none', 'нет'], ['zoom_in', 'наезд'], ['zoom_out', 'отъезд'], ['pan_left', 'панорама влево'], ['pan_right', 'панорама вправо'], ['pan_up', 'вверх'], ['pan_down', 'вниз']];
const FITS = [['cover', 'заполнить кадр (обрезать лишнее)'], ['contain', 'вписать целиком'], ['free', 'свободно (позиция и масштаб)']];
const BLENDS = [['normal', 'обычное'], ['screen', 'осветление (экран)'], ['add', 'сложение (свечение)'], ['multiply', 'умножение (затемнение)']];
const ANIMS = [['rise', 'всплывает'], ['fade', 'проявляется'], ['blur', 'из размытия'], ['scale', 'из масштаба'], ['slide', 'выезжает'], ['type', 'печатается'], ['none', 'без анимации']];
const POS = [['center', 'по центру'], ['lower', 'внизу (субтитр)'], ['upper', 'вверху'], ['left', 'слева'], ['right', 'справа'], ['custom', 'свои координаты']];
const TYPE_LABEL = { video: 'Видео', image: 'Картинка', text: 'Текст' };
function gradeOpts() {
  const g = (FX.find(e => e.name === 'grade') || { params: [{ options: [] }] }).params[0].options || [];
  return [['', 'нет']].concat(g);
}
function fontOpts() {
  const f = (X.fonts && X.fonts.fonts) || [];
  return [{ group: 'Роли (из настроек)', items: [['title', 'Заголовки'], ['serif', 'Курсив'], ['text', 'Обычный']] },
          { group: 'Файлы шрифтов', items: f.map(x => [x.name, x.name]) }];
}
function layerTitle(L) {
  if (L.type === 'text') return (L.text || '').split('\n')[0] || 'Текст';
  return L.src || (L.type === 'video' ? 'выберите видео' : 'выберите картинку');
}
function layerSub(L) {
  const s = X.sceneById(curSid);
  const end = L.end == null ? (s ? s.dur : '…') : L.end;
  return `${TYPE_LABEL[L.type]} · ${(+L.start || 0).toFixed(1)}–${(+end).toFixed(1)} с · ${L.z === 'bottom' ? 'под кодом' : 'над кодом'}`;
}
function mediaOptions(L) {
  const kinds = L.type === 'video' ? ['video'] : ['image', 'sprite'];
  const list = ASSETS.filter(a => kinds.includes(a.kind));
  return [['', '— выберите файл —']].concat(list.map(a => [a.name, a.name + (a.kind === 'video' ? ` (${(+a.dur).toFixed(1)} с)` : a.kind === 'sprite' ? ' (вырезанный)' : '')]));
}
function layerBody(L) {
  let h = '<div class="fgrid">';
  if (L.type === 'text') {
    h += `<label class="f wide"><span>Текст (Enter — новая строка)</span><textarea data-k="text" rows="2">${esc(L.text || '')}</textarea></label>`;
    h += fSel('font', 'Шрифт', L.font, fontOpts()) + fRange('weight', 'Толщина', L.weight, 100, 900, 50);
    h += fRange('size', 'Размер', L.size, 12, 400, 2) + `<label class="f"><span>Цвет</span><input type="color" data-k="color" value="${esc(L.color || '#ECE4D6')}"></label>`;
    h += fSel('pos', 'Положение', L.pos, POS) + fSel('anim', 'Анимация', L.anim, ANIMS);
    if (L.pos === 'custom') h += fNum('x', `X, px (0–${fw()})`, L.x, 10) + fNum('y', `Y, px (0–${fh()})`, L.y, 10) + fSel('align', 'Выравнивание', L.align, [['c', 'по центру'], ['l', 'от левого края'], ['r', 'к правому краю']]);
    h += fRange('track', 'Разрядка', L.track, -0.1, 1, 0.01) + fRange('line', 'Межстрочный', L.line, 0.7, 2.5, 0.05);
    h += fRange('plate', 'Плашка под текстом', L.plate, 0, 1, 0.05) + fChk('shadow', 'Тень', L.shadow);
  } else {
    h += fSel('src', L.type === 'video' ? 'Видеофайл' : 'Картинка', L.src, mediaOptions(L), true);
    if (L.type === 'video') {
      const a = ASSETS.find(x => x.name === L.src);
      const vd = a ? +a.dur : 0;
      h += fRange('trim', `Начать с секунды файла${vd ? ` (длина ${vd.toFixed(1)} с)` : ''}`, L.trim || 0, 0, Math.max(0.1, vd || 60), 0.05);
      h += fRange('speed', 'Скорость', L.speed, 0.1, 4, 0.05) + fRange('volume', 'Звук из видео', L.volume, 0, 2, 0.05);
      h += fChk('loop', 'Зациклить, если видео короче', L.loop);
    }
    h += fSel('fit', 'Подгонка', L.fit, FITS, true);
    h += fSel('motion', 'Движение камеры', L.motion, MOTIONS) + fRange('motion_amt', 'Сила движения', L.motion_amt, 0, 0.5, 0.01);
    if (L.fit === 'cover') h += fRange('focus_x', 'Фокус по X', L.focus_x, 0, 1, 0.01) + fRange('focus_y', 'Фокус по Y', L.focus_y, 0, 1, 0.01);
    if (L.fit === 'free') h += fNum('x', 'Центр X, px', L.x, 10) + fNum('y', 'Центр Y, px', L.y, 10);
    h += fRange('scale', 'Масштаб', L.scale, 0.05, L.fit === 'free' ? 6 : 3, 0.01) + fRange('rotate', 'Поворот, °', L.rotate, -180, 180, 1);
    h += fSel('area', 'Область', L.area, [['visible', 'видимая (между полосами)'], ['full', 'весь кадр']]) + fSel('blend', 'Смешивание', L.blend, BLENDS);
    h += fRange('radius', 'Скругление углов', L.radius, 0, 200, 2) + fSel('grade', 'Цветокоррекция', L.grade || '', gradeOpts());
    h += `</div><div class="sub-h">Цвет</div><div class="fgrid three">`;
    h += fRange('bright', 'Яркость', L.bright, 0, 2, 0.02) + fRange('con', 'Контраст', L.con, 0, 2, 0.02) + fRange('sat', 'Насыщенность', L.sat, 0, 2.5, 0.02);
    h += fRange('blur', 'Размытие', L.blur, 0, 40, 0.5) + fRange('gray', 'Ч/Б', L.gray, 0, 1, 0.05);
  }
  h += `</div><div class="sub-h">Время и прозрачность</div><div class="fgrid three">`;
  h += fNum('start', 'Начало, с', L.start, 0.1) + fNum('end', 'Конец, с', L.end, 0.1, 'до конца') + fRange('opacity', 'Прозрачность', L.opacity, 0, 1, 0.02);
  h += fNum('fade_in', 'Появление, с', L.fade_in, 0.1) + fNum('fade_out', 'Исчезание, с', L.fade_out, 0.1);
  h += fSel('z', 'Слой', L.z, [['top', 'над кодом сцены'], ['bottom', 'под кодом (фон)']]);
  h += `</div><div class="mrow" style="margin-top:10px"><button class="ghost small" data-act="here">${icon('check')}Начать с курсора</button>
    <button class="ghost small" data-act="dupl">${icon('copy')}Копия слоя</button>${L.type !== 'text' && L.src ? `<button class="ghost small" data-act="code">${icon('code')}Как это в коде</button>` : ''}</div>`;
  return h;
}
function layerThumb(L) {
  if (L.type !== 'text' && L.src) return `<img src="/api/thumb?name=${encodeURIComponent(L.src)}" alt="">`;
  return icon(L.type === 'video' ? 'film' : L.type === 'image' ? 'image' : 'type');
}
function renderLayers() {
  const box = $('layerList');
  if (!curSid) { box.innerHTML = '<div class="empty"><b>Нет выбранной сцены</b>Выберите сцену на таймлайне</div>'; return; }
  if (!layers.length) { box.innerHTML = '<div class="empty"><b>В этой сцене нет слоёв</b>Добавьте видео, картинку или текст кнопками выше<br>или просто нажмите на файл во вкладке «Медиа».</div>'; return; }
  const order = layers.map((L, i) => i).reverse();       // сверху — то, что поверх
  box.innerHTML = order.map(i => {
    const L = layers[i];
    const id = L.id || ('new' + i);
    return `<div class="lcard ${openIds.has(id) ? 'open' : ''} ${L.hidden ? 'off' : ''}" data-i="${i}" data-id="${esc(id)}">
      <div class="lhead"><div class="lic">${layerThumb(L)}</div>
        <div class="ltitle"><b>${esc(layerTitle(L))}</b><span>${esc(layerSub(L))}</span></div>
        <button class="icon" data-act="eye" title="${L.hidden ? 'Показать' : 'Скрыть'}">${icon(L.hidden ? 'eyeoff' : 'eye')}</button>
        <button class="icon" data-act="up" title="Выше (поверх)">${icon('up')}</button>
        <button class="icon" data-act="down" title="Ниже">${icon('down')}</button>
        <button class="icon" data-act="del" title="Удалить слой">${icon('trash')}</button></div>
      <div class="lbody">${openIds.has(id) ? layerBody(L) : ''}</div></div>`;
  }).join('');
}
function cardOf(el) { const c = el.closest('.lcard'); return c ? { c, i: +c.dataset.i, L: layers[+c.dataset.i] } : null; }
$('layerList').addEventListener('click', e => {
  const k = cardOf(e.target); if (!k) return;
  const act = e.target.closest('[data-act]');
  const id = k.c.dataset.id;
  if (!act) {
    if (e.target.closest('.lhead')) { openIds.has(id) ? openIds.delete(id) : openIds.add(id); renderLayers(); X.setSelLayer(k.L.id); X.drawTimeline(); }
    return;
  }
  const a = act.dataset.act;
  if (a === 'eye') { k.L.hidden = !k.L.hidden; }
  else if (a === 'up' && k.i < layers.length - 1) { [layers[k.i], layers[k.i + 1]] = [layers[k.i + 1], layers[k.i]]; }
  else if (a === 'down' && k.i > 0) { [layers[k.i], layers[k.i - 1]] = [layers[k.i - 1], layers[k.i]]; }
  else if (a === 'del') { if (!confirm('Удалить слой?')) return; layers.splice(k.i, 1); }
  else if (a === 'here') { const s = X.sceneById(curSid); if (s) { k.L.start = Math.max(0, +((X.cur - s.f0) / X.ST.fps).toFixed(2)); } }
  else if (a === 'dupl') { const c = JSON.parse(JSON.stringify(k.L)); c.id = ''; c.key = ''; layers.splice(k.i + 1, 0, c); }
  else if (a === 'code') { showLayerCode(k.L); return; }
  else return;
  renderLayers(); changed();
});
function onLayerField(e, live) {
  const el = e.target.closest('[data-k]'); if (!el) return;
  const k = cardOf(el); if (!k) return;
  const key = el.dataset.k;
  let v = readField(el);
  if (key === 'end' && v === null) v = null;
  else if (v === null) return;
  k.L[key] = v;
  if (el.type === 'range') { const lab = k.c.querySelector(`i[data-v="${key}"]`); if (lab) lab.textContent = fmtVal(el); }
  const head = k.c.querySelector('.ltitle');
  if (head) head.innerHTML = `<b>${esc(layerTitle(k.L))}</b><span>${esc(layerSub(k.L))}</span>`;
  if (!live && ['fit', 'pos', 'src', 'type'].includes(key)) { renderLayers(); }
  if (key === 'src') { const t = k.c.querySelector('.lic'); if (t) t.innerHTML = layerThumb(k.L); }
  changed();
}
$('layerList').addEventListener('input', e => { if (e.target.type === 'range' || e.target.tagName === 'TEXTAREA' || e.target.type === 'color') onLayerField(e, true); });
$('layerList').addEventListener('change', e => onLayerField(e, false));
const fw = () => (X.ST && X.ST.size ? X.ST.size[0] : 1920), fh = () => (X.ST && X.ST.size ? X.ST.size[1] : 1080);
function newLayer(type, src, sprite) {
  const base = { id: '', type, start: 0, end: null, z: 'top', opacity: 1, fade_in: 0.3, fade_out: 0.3, hidden: false };
  if (type === 'text') return Object.assign(base, { text: 'Новый текст', font: 'title', weight: 700, size: 110, color: '#ECE4D6', pos: 'center', anim: 'rise', track: 0.08, line: 1.15, plate: 0, shadow: true, align: 'c', x: fw() / 2, y: fh() / 2 });
  const L = Object.assign(base, { src: src || '', fit: sprite ? 'free' : 'cover', area: 'visible', x: fw() / 2, y: fh() / 2, scale: 1, rotate: 0, focus_x: 0.5, focus_y: 0.5,
    blend: 'normal', motion: sprite ? 'none' : 'zoom_in', motion_amt: 0.08, sat: 1, con: 1, bright: 1, blur: 0, gray: 0, grade: '', radius: 0 });
  if (type === 'video') Object.assign(L, { trim: 0, speed: 1, loop: true, volume: 0 });
  return L;
}
async function addLayer(type, src, sprite) {
  if (!X.sel) return toast('Сначала выберите сцену');
  if (curSid !== X.sel) syncFromState(true);
  if (type !== 'text' && !src) {
    if (!ASSETS.length) await loadAssets();
    const pick = ASSETS.find(a => type === 'video' ? a.kind === 'video' : a.kind === 'image');
    if (!pick) { toast(type === 'video' ? 'Сначала загрузите видео во вкладке «Медиа»' : 'Сначала загрузите картинку во вкладке «Медиа»'); X.switchTab('assets'); return; }
    src = pick.name;
  }
  X.switchTab('layers');
  const L = newLayer(type, src, sprite);
  // видео и картинки — под надписями, чтобы не закрыть их
  let at = layers.length;
  if (type !== 'text') { const ti = layers.findIndex(x => x.type === 'text'); if (ti >= 0) at = ti; }
  layers.splice(at, 0, L);
  openIds = new Set(['new' + at]);
  renderLayers(); changed();
  toast(`${TYPE_LABEL[type]} добавлен${type === 'image' ? 'а' : ''} в сцену «${esc(X.sceneById(X.sel).name)}»`, 2500);
}
X.addLayer = addLayer;
X.openLayer = id => { openIds.add(id); syncFromState(false); renderLayers(); const el = $('layerList').querySelector(`[data-id="${CSS.escape(id)}"]`); if (el) el.scrollIntoView({ block: 'nearest' }); };
document.querySelectorAll('[data-addlayer]').forEach(b => b.onclick = () => addLayer(b.dataset.addlayer));
function showLayerCode(L) {
  const fn = L.type === 'video' ? `video('${L.src}', t, start=${+L.trim || 0}, speed=${+L.speed || 1})` : `image('${L.src}')`;
  const code = `img = ${fn}\n${L.fit === 'contain' ? 'contain' : 'cover'}(fr, img, zoom=lerp(1.0, ${(1 + (+L.motion_amt || 0)).toFixed(2)}, t / dur))`;
  X.switchTab('code'); X.ed.insert('\n    ' + code.replace(/\n/g, '\n    ') + '\n');
  toast('Вставлено в код сцены — то же самое, но кодом', 2500);
}

// ---------------- эффекты
function fxBody(e, it) {
  let h = '<div class="fgrid">';
  e.params.forEach(p => {
    if (p.type === 'num') h += fRange(p.k, p.label, it[p.k] ?? p.default, p.min, p.max, p.step);
    else h += fSel(p.k, p.label, it[p.k] ?? p.default, p.options);
  });
  h += '</div><div class="fgrid">' + fNum('t0', 'С секунды', it.t0 ?? null, 0.1, 'с начала') + fNum('t1', 'По секунду', it.t1 ?? null, 0.1, 'до конца') + '</div>';
  return h;
}
function renderFx() {
  const box = $('fxList');
  if (!curSid) { box.innerHTML = ''; return; }
  if (!effects.length) {
    box.innerHTML = '<div class="empty"><b>Эффектов нет</b>Выберите эффект или готовый набор в списке выше — он применится ко всей сцене.<br>Параметры можно менять ползунками, превью обновится само.</div>';
  } else {
    box.innerHTML = effects.map((it, i) => {
      const e = fxByName(it.name) || { label: it.name, params: [], group: '' };
      const open = fxOpen.has(i);
      return `<div class="lcard ${open ? 'open' : ''} ${it.on === false ? 'off' : ''}" data-i="${i}">
        <div class="lhead"><div class="lic">${icon('fx')}</div><div class="ltitle"><b>${esc(e.label)}</b><span>${esc(e.group)}${it.t0 != null || it.t1 != null ? ` · ${it.t0 ?? 0}–${it.t1 ?? 'конец'} с` : ''}</span></div>
          <button class="icon" data-act="eye" title="${it.on === false ? 'Включить' : 'Выключить'}">${icon(it.on === false ? 'eyeoff' : 'eye')}</button>
          <button class="icon" data-act="up" title="Раньше">${icon('up')}</button>
          <button class="icon" data-act="down" title="Позже">${icon('down')}</button>
          <button class="icon" data-act="del" title="Убрать">${icon('trash')}</button></div>
        <div class="lbody">${open ? fxBody(e, it) : ''}</div></div>`;
    }).join('');
  }
  box.insertAdjacentHTML('beforeend', effects.length ? `<div class="mrow" style="margin-top:6px"><button class="ghost small" id="fxAll">${icon('copy')}Такие же эффекты — во все сцены</button><button class="ghost small danger" id="fxClear">${icon('trash')}Убрать все</button></div>` : '');
}
$('fxAdd').addEventListener('change', e => {
  const v = e.target.value; e.target.value = '';
  if (!v || !curSid) return;
  if (v.startsWith('preset:')) {
    PRESETS[+v.slice(7)].fx.forEach(f => effects.push(Object.assign(fxDefaults(f.name), f)));
  } else {
    effects.push(fxDefaults(v));
    fxOpen.add(effects.length - 1);
  }
  renderFx(); changed();
});
$('fxList').addEventListener('click', async e => {
  if (e.target.closest('#fxAll')) {
    if (!confirm('Поставить такой же набор эффектов во все сцены ролика? Их текущие эффекты заменятся (есть «Версии», чтобы откатить).')) return;
    for (const s of X.ST.scenes) await api.post('/api/scene/update', { id: s.id, fx: effects });
    toast('Эффекты применены ко всем сценам'); X.refresh(); return;
  }
  if (e.target.closest('#fxClear')) { effects = []; renderFx(); changed(); return; }
  const c = e.target.closest('.lcard'); if (!c) return;
  const i = +c.dataset.i;
  const act = e.target.closest('[data-act]');
  if (!act) { if (e.target.closest('.lhead')) { fxOpen.has(i) ? fxOpen.delete(i) : fxOpen.add(i); renderFx(); } return; }
  const a = act.dataset.act;
  if (a === 'eye') effects[i].on = effects[i].on === false;
  else if (a === 'up' && i > 0) { [effects[i], effects[i - 1]] = [effects[i - 1], effects[i]]; fxOpen = new Set(); }
  else if (a === 'down' && i < effects.length - 1) { [effects[i], effects[i + 1]] = [effects[i + 1], effects[i]]; fxOpen = new Set(); }
  else if (a === 'del') { effects.splice(i, 1); fxOpen = new Set(); }
  renderFx(); changed();
});
function onFxField(e) {
  const el = e.target.closest('[data-k]'); if (!el) return;
  const c = el.closest('.lcard'); if (!c) return;
  const it = effects[+c.dataset.i];
  const v = readField(el);
  if (el.dataset.k === 't0' || el.dataset.k === 't1') { if (v === null) delete it[el.dataset.k]; else it[el.dataset.k] = v; }
  else if (v !== null) it[el.dataset.k] = v;
  if (el.type === 'range') { const lab = c.querySelector(`i[data-v="${el.dataset.k}"]`); if (lab) lab.textContent = fmtVal(el); }
  changed();
}
$('fxList').addEventListener('input', e => { if (e.target.type === 'range') onFxField(e); });
$('fxList').addEventListener('change', onFxField);

// ================================================================== вкладки
X.hooks.tab.push(name => {
  if (name === 'assets') loadAssets();
  if (name === 'layers') { if (!ASSETS.length) loadAssets().then(() => renderLayers()); syncFromState(false); }
  if (name === 'fx') syncFromState(false);
  if (name === 'settings') loadFonts();
});
initMediaTab();
Promise.all([loadFx(), loadAssets(), loadFonts()]).then(() => syncFromState(true));
})();
