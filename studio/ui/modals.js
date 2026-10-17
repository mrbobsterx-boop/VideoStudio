(() => {
'use strict';
const X = window.SX;
const { $, api, esc, toast, icon } = X;
const fmtDate = t => { const d = new Date(t * 1000); return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) + ', ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }); };
const el = (html) => { const d = document.createElement('div'); d.innerHTML = html; return d; };

// ================================================================== превью-плеер (кадры с сервера, ~10 к/с)
function previewPlayer(box, urlFor, dur, fps = 10) {
  const n = Math.max(1, Math.round(dur * fps));
  const imgs = new Array(n);
  let loaded = 0, i = 0, alive = true, timer = null;
  box.innerHTML = '<canvas width="640" height="360"></canvas><div class="pv-status">Готовлю превью…</div>';
  const cv = box.querySelector('canvas'), g = cv.getContext('2d'), st = box.querySelector('.pv-status');
  const order = [Math.floor(n / 2)].concat([...Array(n).keys()].filter(k => k !== Math.floor(n / 2)));
  let next = 0;
  async function worker() {
    while (alive && next < order.length) {
      const k = order[next++];
      try {
        const r = await fetch(urlFor(k / fps));
        if (!r.ok) continue;
        imgs[k] = await createImageBitmap(await r.blob());
        loaded++;
        if (loaded === 1) g.drawImage(imgs[k], 0, 0, 640, 360);
        st.textContent = loaded < n ? `Готовлю превью ${Math.round(loaded / n * 100)}%` : 'Превью';
      } catch (e) { /* пропустить */ }
    }
  }
  for (let w = 0; w < 3; w++) worker();
  timer = setInterval(() => {
    if (!alive) return;
    if (loaded < n) return;             // играть, когда готово всё
    st.hidden = true;
    const b = imgs[i]; if (b) g.drawImage(b, 0, 0, 640, 360);
    i = (i + 1) % n;
  }, 1000 / fps);
  return () => { alive = false; clearInterval(timer); };
}

// ================================================================== библиотека
let stopPreview = null;
async function openLibrary() {
  const res = await api.get('/api/library');
  const items = res.items || [];
  const body = X.openModal('Библиотека сцен', '', {
    tools: `<input class="search" id="libSearch" placeholder="Поиск…" style="width:220px"><button class="ghost small" id="libFolder">${icon('folder')}Папка</button>`,
    onClose: () => { if (stopPreview) stopPreview(); stopPreview = null; },
  });
  const render = () => {
    const q = ($('libSearch').value || '').toLowerCase();
    const list = items.filter(it => !q || (it.name + ' ' + it.desc + ' ' + it.category).toLowerCase().includes(q));
    const cats = [...new Set(list.map(i => i.category))];
    body.innerHTML = `<p class="mnote" style="margin:0 0 14px">Готовые сцены и те, что вы сохранили кнопкой «В библиотеку». Нажмите, чтобы посмотреть сцену до добавления.
      Добавленная сцена встанет после выбранной на таймлайне — дальше её можно менять как угодно.</p>
      <div class="lib-grid">${cats.map(c => `<div class="lib-cat">${esc(c)}</div>` + list.filter(i => i.category === c).map(it => `
        <div class="lcard2" data-id="${esc(it.id)}"><div class="lth" style="background-image:url('/api/library/thumb?id=${encodeURIComponent(it.id)}&v=${it.mtime}')"></div>
        <div class="linfo"><b>${esc(it.name)}</b><span>${esc(it.desc || '')}</span><span>${(+it.dur).toFixed(1)} с${it.layers ? ` · слоёв: ${it.layers}` : ''}${it.builtin ? '' : ' · ваша'}</span></div></div>`).join('')).join('')
        || '<div class="empty" style="grid-column:1/-1"><b>Ничего не найдено</b></div>'}</div>`;
  };
  render();
  $('libSearch').oninput = render;
  $('libFolder').onclick = () => api.post('/api/open', { what: 'library' }).then(r => toast(r.error ? esc(r.error) : 'Папка библиотеки:<div class="path">' + esc(r.path) + '</div>'));
  body.onclick = e => { const c = e.target.closest('.lcard2'); if (c) libDetail(items.find(i => i.id === c.dataset.id), body); };
}
async function libDetail(it, body) {
  const code = await api.get('/api/library/code?id=' + encodeURIComponent(it.id));
  body.onclick = null;
  body.innerHTML = `<div class="mgrid"><div class="mcol"><div class="preview-box" id="libPv"></div>
      <div class="mnote">Превью — примерно 10 кадров в секунду; в ролике будет плавно. Тексты можно поменять после добавления во вкладке «Тексты».</div></div>
    <div class="mcol"><div><button class="ghost small" id="libBack">${icon('prev')}Все сцены</button></div>
      <h2 style="margin:0;font-size:20px">${esc(it.name)}</h2>
      <div class="mnote">${esc(it.desc || '')}</div>
      <div class="mnote">${esc(it.category)} · ${(+it.dur).toFixed(1)} с${it.layers ? ` · слоёв: ${it.layers}` : ''}${it.fx.length ? ` · эффекты: ${esc(it.fx.join(', '))}` : ''}</div>
      <div class="mrow"><button class="solid-accent" id="libAdd" style="padding:9px 16px;border-radius:8px">${icon('plus')}Добавить в ролик</button>
        ${it.builtin ? '' : `<button class="ghost small danger" id="libDel">${icon('trash')}Удалить из библиотеки</button>`}</div>
      <h4>Код сцены</h4><textarea class="mcode" readonly>${esc(code.code || '')}</textarea></div></div>`;
  if (stopPreview) stopPreview();
  stopPreview = previewPlayer($('libPv'), t => `/api/library/frame?id=${encodeURIComponent(it.id)}&t=${t.toFixed(3)}&w=640`, it.dur);
  $('libBack').onclick = () => { if (stopPreview) stopPreview(); stopPreview = null; openLibrary(); };
  $('libAdd').onclick = async () => {
    await X.flushDraft();
    const r = await api.post('/api/library/insert', { id: it.id, after: X.sel });
    if (r.error) return toast('Ошибка: ' + esc(r.error));
    X.closeModal();
    await X.refresh();
    const s = X.sceneById(r.id);
    if (s) { await X.selectScene(r.id, false); X.setCur(s.f0 + Math.round(s.n * 0.5)); }
    toast(`Сцена «${esc(it.name)}» добавлена. Надписи меняются во вкладке «Тексты»${it.layers ? ', медиа — во вкладке «Слои»' : ''}.`, 5000);
  };
  const d = $('libDel');
  if (d) d.onclick = async () => {
    if (!confirm('Удалить сцену из библиотеки? (она переместится в library/_trash)')) return;
    await api.post('/api/library/delete', { id: it.id });
    openLibrary();
  };
}
X.openLibrary = openLibrary;
$('libBtn').onclick = openLibrary;

// ---------------- сохранить сцену в библиотеку
X.saveToLibrary = async () => {
  const s = X.sceneById(X.sel);
  if (!s) return toast('Выберите сцену');
  await X.flushDraft();
  const body = X.openModal('Сохранить сцену в библиотеку', '', { narrow: true });
  body.innerHTML = `<div class="mcol">
    <p class="mnote" style="margin:0">Сцена сохранится со всем: кодом, слоями, эффектами, текстами и нужными картинками/видео.
      Её можно будет добавить в любой ролик через «Библиотеку».</p>
    <div class="mrow"><label>Название<input class="mfield" id="slName" value="${esc(s.name)}"></label>
      <label>Раздел<input class="mfield" id="slCat" value="Мои сцены" list="slCats"></label></div>
    <datalist id="slCats"><option>Мои сцены</option><option>Титры</option><option>Медиа</option><option>Динамика</option><option>Текст</option></datalist>
    <label class="mnote">Описание<textarea class="mfield" id="slDesc" rows="2" placeholder="Что это за сцена"></textarea></label>
    <div class="mrow"><button class="solid-accent" id="slGo" style="padding:9px 16px;border-radius:8px">${icon('bookmark')}Сохранить</button></div></div>`;
  $('slGo').onclick = async () => {
    const r = await api.post('/api/library/save', { sid: s.id, name: $('slName').value, desc: $('slDesc').value, category: $('slCat').value });
    if (r.error) return toast('Ошибка: ' + esc(r.error));
    X.closeModal();
    toast('Сцена сохранена в библиотеку ✓');
  };
};

// ================================================================== сцена от ИИ
let aiState = { goal: '', name: '', dur: 4, style: '', brief: '', answer: '', check: null };
async function openAI() {
  await X.loadAssets();
  const body = X.openModal('Сцена от ИИ', '');
  const assets = X.assets();
  body.innerHTML = `<div class="mgrid">
   <div class="mcol">
    <h4>1 · Что должно быть в сцене</h4>
    <textarea class="mfield" id="aiGoal" rows="4" placeholder="Например: крупно название игры, по нему проходит блик; снизу мелко «скоро в Steam»; в фоне медленно летят искры. Холодные синие тона.">${esc(aiState.goal)}</textarea>
    <div class="mrow"><label>Название сцены<input class="mfield" id="aiName" value="${esc(aiState.name)}" placeholder="Например: Steam title"></label>
      <label style="max-width:120px">Длина, с<input class="mfield" id="aiDur" type="number" step="0.5" min="0.5" value="${aiState.dur}"></label></div>
    <label class="mnote">Стиль (необязательно)<input class="mfield" id="aiStyle" value="${esc(aiState.style)}" placeholder="мрачный кинотрейлер / яркий и быстрый / минимализм"></label>
    <label class="mnote">Картинки и видео, которые можно использовать (ничего не выбрано — все)
</label><div id="aiAssets"></div>
    <div class="mrow"><button class="solid-accent" id="aiMake" style="padding:9px 16px;border-radius:8px">${icon('ai')}Составить задание для ИИ</button></div>
    <div id="aiBriefBox" ${aiState.brief ? '' : 'hidden'}>
      <div class="mrow" style="justify-content:space-between;margin-bottom:6px"><span class="mnote">Задание готово — скопируйте его целиком и отправьте ИИ (ChatGPT, Claude и т.п.)</span>
        <span class="mrow"><button class="secondary small" id="aiCopy">${icon('copy')}Копировать</button><button class="ghost small" id="aiSave">${icon('export')}Скачать .md</button></span></div>
      <textarea class="mcode" id="aiBrief" readonly style="min-height:200px">${esc(aiState.brief)}</textarea>
      <p class="mnote">В задании есть всё нужное ИИ: правила файла сцены, справочник всех команд и эффектов, список ваших картинок и шрифтов, пример сцены из проекта.</p>
    </div>
   </div>
   <div class="mcol">
    <h4>2 · Ответ ИИ</h4>
    <textarea class="mcode" id="aiAnswer" placeholder="Вставьте сюда ответ ИИ (можно целиком, с текстом вокруг — код найдётся сам) или загрузите .py файл">${esc(aiState.answer)}</textarea>
    <div class="mrow"><button class="secondary" id="aiCheck">${icon('check')}Проверить и показать</button>
      <label class="ghost small filebtn">${icon('upload')}Загрузить .py<input type="file" id="aiFile" accept=".py,.txt,.md" hidden></label></div>
    <div id="aiResult"></div>
   </div></div>`;
  if (!aiState.sel) aiState.sel = new Set();
  const aiPick = X.mediaPicker($('aiAssets'), { mode: 'multi', selected: aiState.sel });
  const keep = () => { aiState.goal = $('aiGoal').value; aiState.name = $('aiName').value; aiState.dur = +$('aiDur').value || 4; aiState.style = $('aiStyle').value; aiState.answer = $('aiAnswer').value; };
  body.addEventListener('input', keep);
  $('aiMake').onclick = async () => {
    keep();
    const chosen = [...aiPick.selected()];
    const r = await api.post('/api/ai/brief', { goal: aiState.goal, name: aiState.name, dur: aiState.dur, style: aiState.style, assets: chosen, example: X.sel });
    if (r.error) return toast('Ошибка: ' + esc(r.error));
    aiState.brief = r.text;
    $('aiBrief').value = r.text; $('aiBriefBox').hidden = false;
  };
  $('aiCopy').onclick = async () => {
    const ta = $('aiBrief');
    try { await navigator.clipboard.writeText(ta.value); } catch (e) { ta.select(); document.execCommand('copy'); }
    toast('Задание скопировано — вставьте его в чат с ИИ', 2500);
  };
  $('aiSave').onclick = () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([$('aiBrief').value], { type: 'text/markdown' }));
    a.download = 'задание_для_ИИ_' + ((aiState.name || 'scene').replace(/[^\wа-яё]+/gi, '_')) + '.md';
    a.click();
  };
  $('aiFile').onchange = async e => { const f = e.target.files[0]; e.target.value = ''; if (!f) return; $('aiAnswer').value = await f.text(); keep(); if (!aiState.name) $('aiName').value = f.name.replace(/\.\w+$/, ''); };
  $('aiCheck').onclick = async () => {
    keep();
    if (!aiState.answer.trim()) return toast('Вставьте ответ ИИ');
    const out = $('aiResult');
    out.innerHTML = '<p class="mnote"><i class="spinner" style="display:inline-block;vertical-align:-2px"></i> Проверяю: разбор кода и пробный рендер пяти кадров…</p>';
    const r = await api.post('/api/ai/check', { code: aiState.answer, dur: aiState.dur });
    aiState.check = r;
    if (r.error) { out.innerHTML = `<p class="mnote bad">${esc(r.error)}</p>`; return; }
    const ok = !r.errors.length;
    out.innerHTML = `${r.errors.map(e => `<p class="mnote bad">✕ ${esc(e)}</p>`).join('')}
      ${r.warnings.map(w => `<p class="mnote warn">! ${esc(w)}</p>`).join('')}
      ${ok ? `<p class="mnote ok">✓ Код в порядке${r.doc ? ': ' + esc(r.doc) : ''}</p>` : '<p class="mnote">Отправьте ИИ текст ошибки — он исправит сцену. Потом вставьте новый ответ и проверьте снова.</p>'}
      ${r.frames.length ? `<div class="frames">${r.frames.map(f => `<figure><img src="${f.jpg}" alt=""><figcaption>${f.t.toFixed(2)} с · ${f.ms} мс</figcaption></figure>`).join('')}</div>` : ''}
      ${ok ? `<div class="mrow" style="margin-top:6px"><button class="solid-accent" id="aiAdd" style="padding:9px 16px;border-radius:8px">${icon('plus')}Добавить в ролик</button>
        <label class="chk"><input type="checkbox" id="aiLib"> и сохранить в библиотеку</label></div>` : ''}`;
    const add = $('aiAdd');
    if (add) add.onclick = async () => {
      await X.flushDraft();
      const res = await api.post('/api/ai/add', { code: r.code, name: aiState.name, dur: aiState.dur, after: X.sel, to_library: $('aiLib').checked });
      if (res.error || !res.ok) return toast('Ошибка: ' + esc(res.error || ''));
      aiState = { goal: '', name: '', dur: 4, style: '', brief: '', answer: '', check: null };
      X.closeModal();
      await X.refresh();
      const s = X.sceneById(res.id);
      if (s) { await X.selectScene(res.id, false); X.setCur(s.f0 + Math.round(s.n * 0.4)); X.switchTab('code'); }
      toast('Сцена от ИИ добавлена' + (res.lib ? ' и сохранена в библиотеку' : '') + '. Код можно править справа.', 4000);
    };
  };
}
X.openAI = openAI;
$('aiBtn').onclick = openAI;

// ================================================================== версии
async function openVersions() {
  const body = X.openModal('Версии проекта', '', { narrow: true });
  const render = async () => {
    const r = await api.get('/api/versions');
    const items = r.items || [];
    body.innerHTML = `<div class="mcol">
      <p class="mnote" style="margin:0">Версия — снимок всего ролика: порядок и длины сцен, код, слои, эффекты, тексты и настройки.
        Программа сама сохраняет версию перед каждым экспортом, автомонтажом и восстановлением. Картинки и видео не копируются.</p>
      <div class="mrow"><input class="mfield" id="vName" placeholder="Название версии, например «до правок клиента»" style="flex:1">
        <button class="solid-accent" id="vSave" style="padding:9px 16px;border-radius:8px">${icon('save')}Сохранить версию</button></div>
      <div class="ver-list">${items.map(v => `<div class="ver" data-id="${esc(v.id)}">
        <div class="vinfo"><b>${esc(v.name)}</b> <span class="tag ${v.auto ? '' : 'man'}">${v.auto ? 'авто' : 'своя'}</span>
          <span>${fmtDate(v.created)} · сцен: ${v.scenes} · ${Math.floor(v.duration / 60)}:${String(Math.round(v.duration % 60)).padStart(2, '0')}</span></div>
        <button class="secondary small" data-act="restore">${icon('history')}Вернуть</button>
        <button class="ghost small" data-act="rename" title="Переименовать (и сделать постоянной)">Имя</button>
        <button class="icon" data-act="del" title="Удалить версию">${icon('trash')}</button></div>`).join('') || '<div class="empty"><b>Версий пока нет</b>Сохраните первую кнопкой выше</div>'}</div></div>`;
    $('vSave').onclick = async () => {
      const res = await api.post('/api/versions/create', { name: $('vName').value || 'Версия' });
      toast(res.error ? 'Ошибка: ' + esc(res.error) : 'Версия сохранена ✓'); render();
    };
  };
  body.onclick = async e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const v = b.closest('.ver').dataset.id;
    if (b.dataset.act === 'restore') {
      if (!confirm('Вернуть ролик к этой версии?\nТекущее состояние тоже сохранится как версия — его можно будет вернуть.')) return;
      await X.flushDraft();
      const r = await api.post('/api/versions/restore', { id: v });
      if (r.error) return toast('Ошибка: ' + esc(r.error));
      X.dropFrames();
      X.closeModal();
      location.reload();
    } else if (b.dataset.act === 'rename') {
      const n = prompt('Название версии:'); if (!n) return;
      await api.post('/api/versions/rename', { id: v, name: n }); render();
    } else if (b.dataset.act === 'del') {
      if (!confirm('Удалить эту версию?')) return;
      await api.post('/api/versions/delete', { id: v }); render();
    }
  };
  render();
}
$('verBtn').onclick = openVersions;

// ================================================================== автомонтаж
let amState = { style: 'cinematic', picked: null, title: '', subtitle: '', end_title: '', end_sub: '', captions: '', duration: 0, order: 'as_is', replace: true, apply_look: true, video_volume: 0 };
async function openAutomontage() {
  const body = X.openModal('Автомонтаж', '');
  await X.loadAssets();
  body.innerHTML = '<p class="mnote">Загружаю список медиа и анализирую музыку…</p>';
  const info = await api.get('/api/automontage/info');
  const media = info.media || [];
  if (!amState.picked) amState.picked = new Set(media.map(m => m.name));
  const mus = info.music;
  body.innerHTML = `<div class="mgrid">
   <div class="mcol">
    <h4>Стиль</h4>
    <div class="style-cards">${info.styles.map(s => `<button class="style-card ${amState.style === s.id ? 'on' : ''}" data-style="${s.id}"><b>${esc(s.label)}</b><span>${esc(s.desc)}</span></button>`).join('')}</div>
    <h4>Что войдёт в ролик <span class="muted" id="amCount" style="text-transform:none;letter-spacing:0"></span></h4>
    ${media.length ? `<div class="mrow"><span class="mnote">Порядок:</span><select class="select" id="amOrder"><option value="as_is">как в списке</option><option value="shuffle">перемешать</option></select></div>
    <div id="amPick"></div>`
    : `<div class="empty"><b>Нет картинок и видео</b>Загрузите их во вкладке «Медиа» (крупные фото и видео — лучше всего).</div>`}
    <h4>Музыка</h4>
    ${mus ? `<p class="mnote ok">♪ ${esc(mus.file)} — ${Math.round(mus.dur)} с${mus.tempo ? `, темп ≈ ${Math.round(mus.tempo)} уд/мин. Склейки встанут в такт.` : '. Ритм не найден — склейки будут ровными.'}</p>`
      : `<p class="mnote">Своей музыки нет — сцены получат сгенерированный звук в стиле ролика. Загрузите трек, и склейки встанут точно в такт.</p>`}
    <div id="amMusicPick"></div>
    <div class="mrow"><label class="secondary small filebtn">${icon('upload')}Загрузить трек<input type="file" id="amMusic" accept="audio/*" hidden></label>
      ${mus ? `<button class="ghost small" id="amNoMusic">Без музыки</button>` : ''}</div>
   </div>
   <div class="mcol">
    <h4>Тексты</h4>
    <div class="mrow"><label>Заголовок в начале<input class="mfield" id="amTitle" value="${esc(amState.title)}" placeholder="пусто — без титра"></label>
      <label>Подзаголовок<input class="mfield" id="amSub" value="${esc(amState.subtitle)}"></label></div>
    <div class="mrow"><label>Финальный титр<input class="mfield" id="amEnd" value="${esc(amState.end_title)}" placeholder="пусто — без финала"></label>
      <label>Под ним<input class="mfield" id="amEndSub" value="${esc(amState.end_sub)}" placeholder="например: СКОРО · 2026"></label></div>
    <label class="mnote">Подписи к кадрам — по одной на строку, по порядку (необязательно)<textarea class="mfield" id="amCaps" rows="3">${esc(amState.captions)}</textarea></label>
    <h4>Параметры</h4>
    <div class="mrow"><label>Длина ролика, с<input class="mfield" id="amDur" type="number" min="0" step="1" value="${amState.duration || ''}" placeholder="авто${mus ? ' — по музыке' : ''}"></label>
      <label>Звук из видео<input class="mfield" id="amVV" type="number" min="0" max="2" step="0.1" value="${amState.video_volume}"></label></div>
    <label class="chk"><input type="checkbox" id="amReplace" ${amState.replace ? 'checked' : ''}> Заменить все сцены ролика (иначе — добавить в конец)</label>
    <label class="chk"><input type="checkbox" id="amLook" ${amState.apply_look ? 'checked' : ''}> Настроить кинополосы, зерно и виньетку под стиль</label>
    <p class="mnote">Перед сборкой текущий ролик сохранится в «Версиях» — всегда можно вернуть. Каждая сцена будет из слоёв и эффектов:
      после сборки любую можно поправить во вкладках «Слои» и «Эффекты».</p>
    <div class="mrow"><button class="solid-accent" id="amGo" style="padding:11px 20px;border-radius:9px;font-size:14px" ${media.length ? '' : 'disabled'}>${icon('spark')}Собрать ролик</button></div>
    <div id="amRes"></div>
   </div></div>`;
  const names = new Set(media.map(m => m.name));
  const count = () => { const c = $('amCount'); if (c) c.textContent = `— выбрано ${[...amState.picked].filter(n => names.has(n)).length} из ${media.length}`; };
  count();
  if ($('amPick')) X.mediaPicker($('amPick'), { mode: 'multi', kinds: ['video', 'image'], selected: amState.picked, filter: a => names.has(a.name), onChange: count });
  const musRef = (X.assets().find(a => a.kind === 'audio' && a.is_music) || {}).name;
  X.mediaPicker($('amMusicPick'), {
    mode: 'single', kinds: ['audio'], selected: new Set(musRef ? [musRef] : []),
    onChange: async (sel, item) => {
      const pick = [...sel][0] ? item : null;
      $('amRes').innerHTML = '<p class="mnote">Меняю музыку и ищу ритм…</p>';
      const r = await api.post('/api/audio', { music_file: pick ? pick.ref : null });
      if (r.error) return toast('Ошибка: ' + esc(r.error));
      await X.loadAssets(); keep(); openAutomontage();
    },
  });
  if ($('amNoMusic')) $('amNoMusic').onclick = async () => { await api.post('/api/audio', { music_file: null }); await X.loadAssets(); keep(); openAutomontage(); };
  const o = $('amOrder'); if (o) o.value = amState.order;
  body.onclick = e => {
    const st = e.target.closest('[data-style]');
    if (st) { amState.style = st.dataset.style; body.querySelectorAll('[data-style]').forEach(b => b.classList.toggle('on', b === st)); return; }
  };
  const keep = () => {
    amState.title = $('amTitle').value; amState.subtitle = $('amSub').value; amState.end_title = $('amEnd').value; amState.end_sub = $('amEndSub').value;
    amState.captions = $('amCaps').value; amState.duration = +$('amDur').value || 0; amState.video_volume = +$('amVV').value || 0;
    amState.replace = $('amReplace').checked; amState.apply_look = $('amLook').checked; if ($('amOrder')) amState.order = $('amOrder').value;
  };
  body.addEventListener('input', keep); body.addEventListener('change', keep);
  $('amMusic').onchange = async e => {
    const f = e.target.files[0]; e.target.value = ''; if (!f) return;
    $('amRes').innerHTML = '<p class="mnote">Загружаю и анализирую музыку…</p>';
    const r = await api.upload('/api/music/upload?name=' + encodeURIComponent(f.name), f);
    if (r.error) return toast('Ошибка: ' + esc(r.error));
    await X.loadAssets(); keep(); openAutomontage();
  };
  $('amGo').onclick = async () => {
    keep();
    const names = media.filter(m => amState.picked.has(m.name)).map(m => m.name);
    if (!names.length) return toast('Выберите хотя бы одну картинку или видео');
    if (amState.replace && X.ST.scenes.length && !confirm('Заменить все сцены ролика автомонтажом?\nТекущий ролик сохранится в «Версиях».')) return;
    await X.flushDraft();
    $('amGo').disabled = true;
    $('amRes').innerHTML = '<p class="mnote"><i class="spinner" style="display:inline-block;vertical-align:-2px"></i> Собираю ролик…</p>';
    const r = await api.post('/api/automontage', Object.assign({}, amState, { picked: undefined, media: names }));
    $('amGo').disabled = false;
    if (r.error || !r.ok) { $('amRes').innerHTML = `<p class="mnote bad">${esc(r.error || 'Не получилось')}</p>`; return; }
    X.closeModal();
    X.dropFrames();
    await X.refresh();
    const first = X.sceneById(r.added[0]);
    if (first) { await X.selectScene(first.id, false); X.setCur(first.f0); }
    toast(`<b>Ролик собран</b>: ${r.added.length} сцен, ${Math.round(r.duration)} с${r.tempo ? `, в ритм ${Math.round(r.tempo)} уд/мин` : ''}.
      Нажмите Пробел, чтобы посмотреть. Не понравилось — «Версии» → «Вернуть».`, 8000);
  };
}
$('amBtn').onclick = openAutomontage;

// ================================================================== проекты
const FMT_LABEL = { '16:9': '16:9 горизонтальный', '9:16': '9:16 вертикальный', '1:1': '1:1 квадрат' };

// Открыть проект: для незнакомого проекта (zip, папка из другого места, первый раз) — предупреждение про код
async function confirmAndOpen(info, body) {
  if (!info || info.cancel) return;
  if (info.error) return toast('Ошибка: ' + esc(info.error));
  if (info.too_old) return toast(`Проекту нужна версия VideoStudio ${esc(info.editor_min)}, у вас ${esc(info.editor)}. Обновите программу и откройте снова.`, 9000);
  if (!info.known) {
    const lib = info.lib && info.lib.length ? `\nМодули стиля (папка lib): ${info.lib.join(', ')}` : '';
    const pre = info.prerender && info.prerender.length ? `\nСкрипты «Подготовки» (prerender/ — обычный Python, запускаются кнопкой «Подготовка» и перед экспортом): ${info.prerender.join(', ')}` : '';
    const where = (info.imported ? `\nРаспакован в: ${info.path}` : `\nПапка: ${info.path}`) + pre;
    const skipped = info.skipped ? `\nФайлов вне папки проекта пропущено: ${info.skipped}` : '';
    const ok = confirm(`Открыть проект «${info.title}»?\n\nСцен: ${info.scenes}, длина ${Math.floor(info.duration / 60)}:${String(Math.round(info.duration % 60)).padStart(2, '0')}` +
      `\nФайлов с кодом Python: ${info.py}${lib}${where}${skipped}` +
      `\n\nВНИМАНИЕ: код сцен выполняется на этом компьютере. Открывайте только свои проекты или проекты из надёжных источников.`);
    if (!ok) {
      if (info.imported) { await api.post('/api/projects/discard', { id: info.id }); toast('Отменено — распакованная папка удалена'); }
      return;
    }
  }
  await X.flushDraft();
  if (body) body.insertAdjacentHTML('beforeend', '<p class="mnote"><i class="spinner" style="display:inline-block;vertical-align:-2px"></i> Открываю проект…</p>');
  const res = await api.post('/api/projects/open', { id: info.id, trust: true });
  if (res.error) return toast('Ошибка: ' + esc(res.error));
  location.reload();
}

async function openProjects() {
  const body = X.openModal('Проекты', '');
  body.innerHTML = '<p class="mnote">Загружаю список…</p>';
  const r = await api.get('/api/projects');
  const items = r.items || [];
  let fmt = '16:9';
  const card = p => p.kind === 'zip'
    ? `<div class="lcard2 proj zip" data-id="${esc(p.id)}">
      <div class="lth"><span class="nocover">${icon('folder')}</span></div>
      <div class="linfo"><b>${esc(p.title)}</b><span>zip-архив · ${(p.size / 1048576).toFixed(1)} МБ</span>
        <span><b class="curtag">нажмите — распаковать и открыть</b></span></div></div>`
    : `<div class="lcard2 proj ${p.current ? 'cur' : ''}" data-id="${esc(p.id)}">
      <div class="lth" style="${p.cover ? `background-image:url('/api/projects/cover?id=${encodeURIComponent(p.id)}&v=${p.mtime}')` : ''}">${p.cover ? '' : '<span class="nocover">' + icon('film') + '</span>'}</div>
      <div class="linfo"><b>${esc(p.title)}</b>
        <span>${esc(FMT_LABEL[p.format] || p.format)} · сцен: ${p.scenes} · ${Math.floor(p.duration / 60)}:${String(Math.round(p.duration % 60)).padStart(2, '0')}</span>
        <span>${p.current ? '<b class="curtag">открыт сейчас</b>' : (p.known ? 'изменён ' + fmtDate(p.mtime) : 'ещё не открывали')}</span>
        <span class="ppath">${esc(p.id)}</span></div></div>`;
  body.innerHTML = `<div class="mgrid" style="grid-template-columns:1.4fr 1fr">
   <div class="mcol"><h4>Ваши ролики</h4>
    <div class="lib-grid">${items.map(card).join('')}</div>
    <p class="mnote">Сюда попадают проекты из папки <b>projects</b> рядом с программой. Положили туда папку проекта или
      zip-архив — он появится в этом списке.</p>
   </div>
   <div class="mcol">
    <h4>Открыть проект</h4>
    <p class="mnote" style="margin:0">Папка проекта (где лежит project.json) или zip-архив с проектом. Zip распаковывается в папку
      <b>projects</b> и сразу открывается. Можно перетащить zip в это окно.</p>
    <div class="mrow"><button class="secondary" id="opDir">${icon('folder')}Папка…</button>
      <button class="secondary" id="opZip">${icon('folder')}Zip-архив…</button>
      <input type="file" id="opZipFile" accept=".zip,application/zip" style="display:none"></div>
    <div class="mrow"><input class="mfield" id="opPath" placeholder="или вставьте путь: D:\\Видео\\мой-проект или …\\проект.zip" style="flex:1">
      <button class="secondary" id="opPathGo">Открыть</button></div>
    <p class="mnote" id="opStatus"></p>
    <h4>Новый проект</h4>
    <label class="mnote">Название<input class="mfield" id="npTitle" placeholder="Например: Трейлер для Steam"></label>
    <div class="mnote">Формат кадра</div>
    <div class="style-cards" id="npFmt" style="grid-template-columns:repeat(3,1fr)">
      <button class="style-card on" data-fmt="16:9"><b>16:9</b><span>YouTube, трейлер</span></button>
      <button class="style-card" data-fmt="9:16"><b>9:16</b><span>Reels, Shorts, TikTok</span></button>
      <button class="style-card" data-fmt="1:1"><b>1:1</b><span>квадрат, лента</span></button></div>
    <div class="mrow"><button class="solid-accent" id="npGo" style="padding:9px 16px;border-radius:8px">${icon('plus')}Создать и открыть</button></div>
    <p class="mnote">Новый проект — пустой ролик с одной сценой-титром, без кинополос, виньетки и фонового гула (включаются в «Настройках»).
      Шрифты копируются, картинки и видео добавьте во вкладке «Медиа». Свои общие модули стиля кладите в папку <b>lib</b> проекта.</p>
    <h4>Копия текущего</h4>
    <p class="mnote" style="margin:0">Скопировать весь открытый ролик (сцены, слои, медиа) в новый проект — удобно, чтобы сделать другую версию.</p>
    <div class="mrow"><button class="secondary" id="npDup">${icon('copy')}Сделать копию и открыть</button></div>
    <p class="mnote">Все проекты сохраняются сами. При следующем запуске программы откроется последний проект.</p>
   </div></div>`;
  const status = t => { $('opStatus').innerHTML = t ? `<i class="spinner" style="display:inline-block;vertical-align:-2px"></i> ${t}` : ''; };
  const run = async (promise, msg) => { status(msg); const info = await promise; status(''); await confirmAndOpen(info, body); };
  $('npFmt').onclick = e => { const b = e.target.closest('[data-fmt]'); if (!b) return; fmt = b.dataset.fmt; $('npFmt').querySelectorAll('[data-fmt]').forEach(x => x.classList.toggle('on', x === b)); };
  const go = async (url, payload, msg) => {
    await X.flushDraft();
    body.insertAdjacentHTML('beforeend', `<p class="mnote"><i class="spinner" style="display:inline-block;vertical-align:-2px"></i> ${msg}</p>`);
    const res = await api.post(url, payload);
    if (res.error) return toast('Ошибка: ' + esc(res.error));
    location.reload();
  };
  $('npGo').onclick = () => go('/api/projects/new', { title: $('npTitle').value || 'Новый ролик', format: fmt }, 'Создаю проект…');
  $('npDup').onclick = () => go('/api/projects/duplicate', {}, 'Копирую проект…');
  $('opDir').onclick = () => run(api.post('/api/projects/pick', { kind: 'dir' }), 'Выберите папку в открывшемся окне (оно может быть за браузером)…');
  $('opZip').onclick = () => $('opZipFile').click();
  const uploadZip = f => {
    if (!f) return;
    if (!/\.zip$/i.test(f.name)) return toast('Нужен zip-архив');
    run(api.upload('/api/projects/upload?name=' + encodeURIComponent(f.name), f,
      k => status(`Загружаю и распаковываю ${esc(f.name)}… ${Math.round(k * 100)}%`)), 'Загружаю ' + esc(f.name) + '…');
  };
  $('opZipFile').onchange = e => uploadZip(e.target.files[0]);
  $('opPathGo').onclick = () => run(api.post('/api/projects/inspect', { path: $('opPath').value }), 'Открываю…');
  body.ondragover = e => { e.preventDefault(); };
  body.ondrop = e => { e.preventDefault(); const f = e.dataTransfer.files && e.dataTransfer.files[0]; uploadZip(f); };
  body.querySelector('.lib-grid').onclick = async e => {
    const c = e.target.closest('.proj'); if (!c || c.classList.contains('cur')) return;
    if (c.classList.contains('zip')) return run(api.post('/api/projects/unzip', { id: c.dataset.id }), 'Распаковываю…');
    await X.flushDraft();
    const res = await api.post('/api/projects/open', { id: c.dataset.id });
    if (res.error) return toast('Ошибка: ' + esc(res.error));
    if (res.need_confirm) return confirmAndOpen(res, body);
    location.reload();
  };
}
$('projBtn').onclick = openProjects;

// ================================================================== звук
let sndTab = 'auto';
const sndMoods = {};          // выбор настроения в этом окне: sid -> mood
async function openSound() {
  await X.flushDraft();
  const body = X.openModal('Звук ролика', '', {
    tools: `<div class="seg-tabs flat" id="sndTabs"><button data-t="auto" class="${sndTab === 'auto' ? 'on' : ''}">Автоматически</button><button data-t="ai" class="${sndTab === 'ai' ? 'on' : ''}">Через ИИ</button></div>`,
  });
  $('sndTabs').onclick = e => { const b = e.target.closest('[data-t]'); if (!b) return; sndTab = b.dataset.t; openSound(); };
  if (sndTab === 'auto') return soundAuto(body);
  return soundAI(body);
}
$('sndBtn').onclick = openSound;

async function soundAuto(body) {
  body.innerHTML = '<p class="mnote">Читаю сцены…</p>';
  const q = Object.keys(sndMoods).length ? '?moods=' + encodeURIComponent(JSON.stringify(sndMoods)) : '';
  const r = await api.get('/api/sound/plan' + q);
  const sc = r.scenes || [];
  const only = new Set(sc.map(x => x.id));
  let cur = sc[0] ? sc[0].id : null;
  const srcLabel = { code: 'из кода (MOOD)', set: 'выбрано', auto: 'угадано' };
  body.innerHTML = `<div class="mgrid" style="grid-template-columns:1.25fr 1fr">
   <div class="mcol">
    <p class="mnote" style="margin:0">Редактор сам расставит звук по таймингу каждой сцены: удары на HITS и склейках, акценты на появлении надписей,
      подложки и ритм по длине сцены, нарастание перед сильной склейкой. Смысл сцены программа не понимает — поэтому
      <b>настроение</b> выберите сами (или напишите в коде сцены <code>MOOD = 'tragic'</code>).</p>
    ${r.music ? `<p class="mnote warn">В проекте есть своя музыка — звук сцен будет сдержанным: только удары и акценты, без подложек.</p>` : ''}
    <div class="snd-list">${sc.map((x, i) => `<div class="snd-row ${x.id === cur ? 'on' : ''}" data-id="${x.id}">
      <label class="chk" title="Генерировать для этой сцены"><input type="checkbox" data-only="${x.id}" checked></label>
      <span class="snd-n">${i + 1}</span>
      <span class="snd-name"><b>${esc(x.name)}</b><i>${x.dur.toFixed(1)} с · удары ${x.hits.length} · надписи ${x.accents.length}${x.has_sound ? ' · есть звук' : ''}</i></span>
      <select class="select" data-mood="${x.id}" ${x.mood_src === 'code' ? 'disabled title="Задано в коде сцены: MOOD = …"' : ''}>${(r.moods || []).map(m => `<option value="${m.id}" ${m.id === x.mood ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}</select>
      <span class="snd-src ${x.mood_src}">${srcLabel[x.mood_src]}</span></div>`).join('')}</div>
   </div>
   <div class="mcol">
    <h4>Звук сцены <span id="sndName" class="muted" style="text-transform:none;letter-spacing:0"></span></h4>
    <textarea class="mcode" id="sndCode" readonly style="min-height:260px"></textarea>
    <p class="mnote" style="margin:0">Так будет выглядеть функция <code>sound()</code>. После генерации её можно поправить во вкладке «Код».</p>
    <label class="chk"><input type="checkbox" id="sndLevels" checked> Фоновый гул и ветер — по настроению (AMBIENCE / WIND)</label>
    ${r.generated === false ? '<label class="chk"><input type="checkbox" id="sndEnable" checked> Включить сгенерированный звук (сейчас выключен в настройках)</label>' : ''}
    <div class="mrow"><button class="solid-accent" id="sndGo" style="padding:10px 18px;border-radius:9px">${icon('spark')}Сгенерировать звук</button>
      <button class="ghost small" id="sndNone">Снять все</button><button class="ghost small" id="sndAll">Отметить все</button></div>
    <p class="mnote">Заменится функция <code>sound()</code> в отмеченных сценах (картинка не меняется). Перед этим сохранится версия проекта.</p>
    <div id="sndRes"></div>
   </div></div>`;
  const show = id => {
    cur = id; const x = sc.find(y => y.id === id); if (!x) return;
    body.querySelectorAll('.snd-row').forEach(rw => rw.classList.toggle('on', rw.dataset.id === id));
    $('sndName').textContent = '— ' + x.name; $('sndCode').value = x.code;
  };
  if (cur) show(cur);
  body.onclick = e => {
    if (e.target.closest('select, input, label')) return;
    const rw = e.target.closest('.snd-row'); if (rw) show(rw.dataset.id);
    if (e.target.closest('#sndNone')) body.querySelectorAll('[data-only]').forEach(c => { c.checked = false; });
    if (e.target.closest('#sndAll')) body.querySelectorAll('[data-only]').forEach(c => { c.checked = true; });
  };
  body.onchange = async e => {
    const m = e.target.closest('[data-mood]');
    if (m) {
      sndMoods[m.dataset.mood] = m.value;
      await api.post('/api/sound/mood', { id: m.dataset.mood, mood: m.value });
      const rr = await api.get('/api/sound/plan?moods=' + encodeURIComponent(JSON.stringify(sndMoods)));
      (rr.scenes || []).forEach(n => { const o = sc.find(y => y.id === n.id); if (o) Object.assign(o, n); });
      const src = m.closest('.snd-row').querySelector('.snd-src'); src.textContent = srcLabel.set; src.className = 'snd-src set';
      show(m.dataset.mood);
    }
  };
  $('sndGo').onclick = async () => {
    const onlyIds = [...body.querySelectorAll('[data-only]')].filter(c => c.checked).map(c => c.dataset.only);
    if (!onlyIds.length) return toast('Отметьте хотя бы одну сцену');
    const moods = {}; sc.forEach(x => { moods[x.id] = sndMoods[x.id] || x.mood; });
    $('sndGo').disabled = true;
    $('sndRes').innerHTML = '<p class="mnote"><i class="spinner" style="display:inline-block;vertical-align:-2px"></i> Пишу звук…</p>';
    const res = await api.post('/api/sound/generate', { moods, only: onlyIds, levels: $('sndLevels').checked, enable: !!($('sndEnable') && $('sndEnable').checked) });
    $('sndGo').disabled = false;
    if (res.error) { $('sndRes').innerHTML = `<p class="mnote bad">${esc(res.error)}</p>`; return; }
    X.closeModal(); await X.refresh();
    toast(`<b>Звук готов</b>: изменено сцен — ${res.changed}. Звук пересводится, нажмите Пробел, чтобы послушать. Не понравилось — «Версии» → «Вернуть».`, 7000);
  };
}

async function soundAI(body) {
  body.innerHTML = `<div class="mgrid">
   <div class="mcol">
    <h4>1 · Задание для ИИ</h4>
    <p class="mnote" style="margin:0">В задании весь ролик по порядку: код каждой сцены, её время в ролике, удары и надписи, тексты,
      справочник звуков и правила общего стиля. ИИ вернёт новую <code>sound()</code> для каждой сцены.</p>
    <div class="mrow"><button class="solid-accent" id="sbMake" style="padding:9px 16px;border-radius:8px">${icon('ai')}Составить задание</button></div>
    <div id="sbBox" hidden>
      <div class="mrow" style="justify-content:space-between;margin-bottom:6px"><span class="mnote">Скопируйте целиком и отправьте ИИ</span>
        <span class="mrow"><button class="secondary small" id="sbCopy">${icon('copy')}Копировать</button><button class="ghost small" id="sbSave">${icon('export')}Скачать .md</button></span></div>
      <textarea class="mcode" id="sbText" readonly style="min-height:300px"></textarea>
    </div>
   </div>
   <div class="mcol">
    <h4>2 · Ответ ИИ</h4>
    <textarea class="mcode" id="saAns" placeholder="Вставьте сюда ответ ИИ целиком — блоки «# === scene: файл.py ===» найдутся сами"></textarea>
    <div class="mrow"><button class="secondary" id="saCheck">${icon('check')}Проверить</button>
      <label class="ghost small filebtn">${icon('upload')}Загрузить файл<input type="file" id="saFile" accept=".py,.txt,.md" hidden></label></div>
    <div id="saRes"></div>
   </div></div>`;
  $('sbMake').onclick = async () => {
    const r = await api.get('/api/sound/brief');
    if (r.error) return toast('Ошибка: ' + esc(r.error));
    $('sbText').value = r.text; $('sbBox').hidden = false;
  };
  $('sbCopy').onclick = async () => {
    const ta = $('sbText');
    try { await navigator.clipboard.writeText(ta.value); } catch (e) { ta.select(); document.execCommand('copy'); }
    toast('Задание скопировано — вставьте его в чат с ИИ', 2500);
  };
  $('sbSave').onclick = () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([$('sbText').value], { type: 'text/markdown' }));
    a.download = 'звук_задание_для_ИИ.md'; a.click();
  };
  $('saFile').onchange = async e => { const f = e.target.files[0]; e.target.value = ''; if (f) $('saAns').value = await f.text(); };
  $('saCheck').onclick = async () => {
    const text = $('saAns').value;
    if (!text.trim()) return toast('Вставьте ответ ИИ');
    const r = await api.post('/api/sound/ai_check', { text });
    const rows = r.rows || [];
    const good = rows.filter(x => x.ok);
    const st = X.ST;
    const missing = st.scenes.filter(s => !rows.some(x => x.id === s.id));
    $('saRes').innerHTML = !rows.length ? '<p class="mnote bad">Не нашёл ни одного блока «# === scene: файл.py ===». Попросите ИИ ответить строго в формате из задания.</p>' :
      `<div class="snd-list">${rows.map(x => `<div class="snd-row"><span class="snd-n">${x.ok ? '<b style="color:var(--ok)">✓</b>' : '<b style="color:var(--bad)">✕</b>'}</span>
        <span class="snd-name"><b>${esc(x.name)}</b><i>${x.ok ? `событий: ${x.events}` : esc(x.error)}</i></span></div>`).join('')}</div>
      ${missing.length ? `<p class="mnote warn">Без звука от ИИ (останется как есть): ${missing.map(s => esc(s.name)).join(', ')}</p>` : ''}
      ${good.length ? `${X.ST.audio.generated === false ? '<label class="chk"><input type="checkbox" id="saEnable" checked> Включить сгенерированный звук</label>' : ''}
        <div class="mrow"><button class="solid-accent" id="saApply" style="padding:9px 16px;border-radius:8px">${icon('check')}Применить к ${good.length} сценам</button></div>
        <p class="mnote">Заменится только sound() (и AMBIENCE / WIND, если ИИ их прислал). Перед этим сохранится версия.</p>` : ''}`;
    const ap = $('saApply');
    if (ap) ap.onclick = async () => {
      const res = await api.post('/api/sound/ai_apply', { text, enable: !!($('saEnable') && $('saEnable').checked) });
      if (res.error) return toast('Ошибка: ' + esc(res.error));
      X.closeModal(); await X.refresh();
      toast(`<b>Звук от ИИ применён</b> к ${res.rows.filter(x => x.ok).length} сценам. Нажмите Пробел, чтобы послушать.`, 6000);
    };
  };
}

// ================================================================== «Подготовка» (3D, Manim, тяжёлые эффекты → cache/)
let prepTimer = null;
async function openPrerender() {
  const body = X.openModal('Подготовка', '', { narrow: true, onClose: () => { clearInterval(prepTimer); prepTimer = null; } });
  let lastLen = -1;
  const render = async () => {
    const r = await api.get('/api/prerender');
    if (!r || r.error && !r.scripts) { body.innerHTML = `<p class="mnote bad">${esc((r && r.error) || 'Нет ответа')}</p>`; return; }
    const running = r.state === 'running';
    const libs = r.libs || {};
    const miss = Object.keys(libs).filter(k => !libs[k]);
    const models = (r.models || []).map(m => `<div class="prep-row">${icon('cube')}<b>${esc(m.file)}</b><span>${m.views} ракурс(ов) ещё не посчитано</span></div>`).join('');
    const scripts = (r.scripts || []).map(s => `<div class="prep-row">${icon(s.manim ? 'spark' : 'code')}<b>prerender/${esc(s.file)}</b>
        <span>${s.manim ? 'Manim: ' + esc(s.scenes.join(', ') || '—') + ' · ' : ''}${s.error ? '<em class="bad">ошибка</em>' : s.stale ? 'нужно посчитать' : 'готово ✓'}</span></div>`).join('');
    const head = `<div class="mcol">
      <p class="mnote" style="margin:0">Тяжёлое считается <b>один раз</b> и кладётся в папку <code>cache/</code> проекта, а кадр сцены только читает готовое:
        ракурсы 3D-моделей (<code>model(...)</code>), графики и схемы Manim и другие скрипты из папки <code>prerender/</code>.
        Перед экспортом «Подготовка» запускается сама — только для того, что изменилось.</p>
      <p class="mnote warn" style="margin:0">Скрипты <code>prerender/*.py</code> — обычный Python с полным доступом к компьютеру (это не сцены).
        Запускайте только свои проекты или те, которым доверяете.</p>
      ${miss.length ? `<p class="mnote warn" style="margin:0">Не установлено: ${miss.map(esc).join(', ')}. ${miss.includes('manim') ? 'Manim нужен только для графиков: <code>pip install -r requirements-manim.txt</code> (см. README). ' : ''}${miss.includes('pyvista') ? '3D: перезапустите start_… — библиотеки доустановятся.' : ''}</p>` : ''}
      <h4>Что нужно посчитать</h4>
      <div class="prep-list">${models + scripts || '<div class="empty"><b>Всё готово</b>Сцены с model(...) и папка prerender/ — посчитаны</div>'}</div>
      <div class="mrow">
        <button class="solid-accent" id="prepRun" style="padding:9px 16px;border-radius:8px" ${running ? 'disabled' : ''}>${icon('cube')}${running ? 'Считается…' : 'Запустить'}</button>
        <button class="ghost small" id="prepForce" ${running ? 'disabled' : ''} title="Пересчитать все скрипты prerender/ заново">Всё заново</button>
        ${running ? '<button class="ghost small" id="prepStop">Остановить</button>' : ''}
        <span class="mnote">${r.result ? (r.result.ok ? `Готово за ${r.result.seconds} с` : 'Были ошибки — см. журнал') : ''}</span>
      </div>
      <h4>Журнал</h4><pre class="prep-log" id="prepLog"></pre></div>`;
    const keepScroll = $('prepLog') && ($('prepLog').scrollTop + $('prepLog').clientHeight >= $('prepLog').scrollHeight - 8);
    body.innerHTML = head;
    const lg = $('prepLog');
    lg.textContent = (r.log || []).join('\n') || '—';
    if (keepScroll || lastLen !== (r.log || []).length) lg.scrollTop = lg.scrollHeight;
    lastLen = (r.log || []).length;
    $('prepRun').onclick = () => api.post('/api/prerender', {}).then(render);
    $('prepForce').onclick = () => api.post('/api/prerender', { force: true }).then(render);
    if ($('prepStop')) $('prepStop').onclick = () => api.post('/api/prerender/cancel').then(render);
    $('prepDot').hidden = !(r.todo > 0);
    if (!running && r.state === 'done' && !render.reloaded) { render.reloaded = true; X.dropFrames && X.dropFrames(); X.loadAssets && X.loadAssets(); }
    if (running) render.reloaded = false;
  };
  clearInterval(prepTimer);
  prepTimer = setInterval(render, 1200);
  render();
}
$('prepBtn').onclick = openPrerender;
async function checkPrerender() {
  try { const r = await api.get('/api/prerender'); $('prepDot').hidden = !(r && r.todo > 0); } catch (e) { /* сервер занят */ }
}
setInterval(checkPrerender, 15000);
setTimeout(checkPrerender, 3000);

// ================================================================== голос из Glimpsy: подогнать сцены под озвучку
const vAudio = new Audio();
let vStop = null;
function playVoice(at, btn) {
  clearTimeout(vStop);
  if (btn && btn.classList.contains('on')) { vAudio.pause(); btn.classList.remove('on'); return; }
  document.querySelectorAll('.vplay.on').forEach(b => b.classList.remove('on'));
  if (!vAudio.src) vAudio.src = '/api/voicefile?v=' + Date.now();
  const go = () => { vAudio.currentTime = Math.max(0, at - 0.5); vAudio.play().catch(() => {}); };
  if (vAudio.readyState >= 1) go(); else vAudio.addEventListener('loadedmetadata', go, { once: true });
  if (btn) btn.classList.add('on');
  vStop = setTimeout(() => { vAudio.pause(); if (btn) btn.classList.remove('on'); }, 7000);
}
const fmtT = s => { s = Math.round(s * 10) / 10; return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`; };

async function openVoice() {
  const body = X.openModal('Голос из Glimpsy', '', { onClose: () => { vAudio.pause(); vAudio.removeAttribute('src'); } });
  let plan = null;
  const render = async () => {
    const st = await api.get('/api/voice/status');
    const pk = st.words && st.audio;
    const fitted = st.fitted > 0;
    body.innerHTML = `<div class="mcol">
      <p class="mnote" style="margin:0">Запишите голос в <b>Glimpsy</b> в своём темпе — он положит в папку проекта <code>voice/</code>
        чистый голос и время каждого слова. Здесь сцены подстроятся под голос: длина сцены = её кусок речи, а плашки, мемы и схемы
        внутри сцены попадут на свои слова. Код сцен не меняется.</p>
      <h4>1. Пакет озвучки</h4>
      <div class="prep-list">
        <div class="prep-row">${icon('mic')}<b>${st.audio ? esc(st.audio) : 'voice/voice.wav'}</b><span>${st.audio ? 'есть' : '<em class="bad">нет</em>'}</span></div>
        <div class="prep-row">${icon('code')}<b>voice/words.json</b><span>${st.error ? '<em class="bad">' + esc(st.error) + '</em>' : st.words ? `${st.n} слов · ${fmtT(st.duration || 0)}${st.language ? ' · ' + esc(st.language) : ''}` : '<em class="bad">нет</em>'}</span></div>
        <div class="prep-row">${icon('lib')}<b>scenes.md</b><span>${st.has_md ? 'текст сцен и якоря битов' : 'нет — текст из script.md по порядку, без якорей'}</span></div>
      </div>
      <div class="mrow"><label class="secondary small filebtn">${icon('upload')}Загрузить voice.wav и words.json<input type="file" id="vUp" accept=".wav,.flac,.json,audio/*,application/json" multiple hidden></label>
        <span class="mnote">или Glimpsy сам кладёт их в папку <code>voice/</code> проекта</span></div>
      <h4>2. Подогнать сцены</h4>
      <div class="mrow">
        <button class="solid-accent" id="vPlan" style="padding:9px 16px;border-radius:8px" ${pk ? '' : 'disabled'}>${icon('mic')}Подогнать под голос</button>
        <span class="mnote">${fitted ? `Сейчас подогнано сцен: ${st.fitted} из ${st.scenes}. Повторная подгонка считает от исходных длин.` : 'Сначала только расчёт и отчёт — проект изменится после «Применить».'}</span>
      </div>
      <div id="vReport"></div>
      <h4>3. Видео</h4>
      <div class="mrow">
        <button class="secondary small" id="vExp">${icon('export')}Экспорт для Glimpsy (MP4 с голосом)</button>
        <button class="ghost small" id="vDraft" title="Быстро, без звука — смотреть во время записи голоса">Черновик без звука 960×540</button>
      </div></div>`;
    $('vUp').onchange = async e => {
      const files = [...e.target.files]; e.target.value = '';
      files.sort((a, b) => a.name.endsWith('.json') - b.name.endsWith('.json'));
      for (const f of files) {
        toast('Загружаю ' + esc(f.name) + '…', 0);
        const r = await api.upload('/api/voice/upload?name=' + encodeURIComponent(f.name), f);
        if (r.error) { toast('Ошибка: ' + esc(r.error)); return render(); }
      }
      toast('Пакет озвучки загружен ✓'); render();
    };
    $('vPlan').onclick = async () => {
      $('vReport').innerHTML = '<p class="mnote">Сопоставляю текст сценария со словами голоса…</p>';
      plan = await api.post('/api/voice/plan', {});
      if (plan.error) { $('vReport').innerHTML = `<p class="mnote bad">${esc(plan.error)}</p>`; return; }
      showReport();
    };
    $('vExp').onclick = async () => {
      await X.flushDraft();
      const r = await api.post('/api/export', { mode: 'glimpsy' });
      toast(r.ok ? 'Экспорт с голосом начался — когда будет готов, откроется папка с файлом.' : esc(r.error || 'Экспорт не начался'));
      X.refresh();
    };
    $('vDraft').onclick = async () => {
      await X.flushDraft();
      const r = await api.post('/api/export', { mode: 'draft' });
      toast(r.ok ? 'Черновик 960×540 без звука считается…' : esc(r.error || 'Экспорт не начался'));
      X.refresh();
    };
  };
  const showReport = () => {
    const p = plan;
    const rows = p.scenes.map(r => {
      const d = r.dur - r.dur_old;
      const pct = r.matched == null ? '—' : Math.round(r.matched * 100) + ' %';
      return `<tr class="${r.weak ? 'weak' : ''}"><td><b>${esc(r.id)}</b> ${esc(r.name)}</td>
        <td class="n">${r.dur_old.toFixed(1)} → <b>${r.dur.toFixed(1)}</b> <span class="${d >= 0 ? 'up' : 'dn'}">${d >= 0 ? '+' : ''}${d.toFixed(1)}</span></td>
        <td class="n">${r.anchors ? `${r.used} из ${r.anchors}` : '—'}</td>
        <td class="n">${pct}</td>
        <td>${r.first_word != null ? `<button class="icon vplay" data-at="${r.first_word - p.voice_offset}" title="Прослушать начало сцены">${icon('play')}</button>` : ''}</td></tr>`;
    }).join('');
    const weak = p.weak.length ? `<p class="mnote warn" style="margin:0">Слабое сопоставление (≤ 60 % слов совпало) — проверьте на слух: ${p.weak.map(w =>
      `<a href="#" class="vweak" data-at="${w.at - p.voice_offset}">${esc(w.id)}</a>`).join(', ')}</p>` : '';
    $('vReport').innerHTML = `<p class="mnote" style="margin:0">Совпало слов: <b>${Math.round(p.matched * 100)} %</b> из ${p.script_words} ·
      голос ${fmtT(p.voice_end)}${p.voice_offset ? ` (сдвинут на ${p.voice_offset.toFixed(1)} с — заставка без слов)` : ''} ·
      ролик станет <b>${fmtT(p.total)}</b> (хвост ${p.tail.toFixed(1)} с)</p>${weak}
      <div class="vtable"><table><thead><tr><th>Сцена</th><th>Длина, с</th><th>Якоря</th><th>Слов</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="mrow"><button class="solid-accent" id="vApply" style="padding:9px 16px;border-radius:8px">Применить</button>
        <span class="mnote">Перед применением сохранится версия проекта — подгонку можно отменить одной кнопкой.</span></div>`;
    $('vApply').onclick = async () => {
      await X.flushDraft();
      const r = await api.post('/api/voice/apply', {});
      if (!r.ok) return toast('Ошибка: ' + esc(r.error || ''));
      X.dropFrames && X.dropFrames();
      await X.refresh();
      toast(`Сцены подогнаны под голос ✓ <div class="acts"><a href="#" id="vUndo">Отменить</a></div>`, 12000);
      const u = $('vUndo'); if (u) u.onclick = async ev => {
        ev.preventDefault();
        await api.post('/api/voice/undo', { version: r.version });
        X.dropFrames && X.dropFrames(); location.reload();
      };
      render();
    };
  };
  body.addEventListener('click', e => {
    const b = e.target.closest('.vplay'); if (b) { playVoice(+b.dataset.at, b); return; }
    const w = e.target.closest('.vweak'); if (w) { e.preventDefault(); playVoice(+w.dataset.at); }
  });
  render();
}
X.openVoice = openVoice;
$('voiceBtn').onclick = openVoice;
})();
