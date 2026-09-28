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
  if (!X.assets().length) await X.loadAssets();
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
      <select class="mfield" id="aiAssets" multiple size="4">${assets.map(a => `<option value="${esc(a.name)}">${esc(a.name)} — ${a.kind === 'video' ? 'видео' : a.kind === 'sprite' ? 'вырезанный' : 'картинка'}</option>`).join('')}</select></label>
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
  const keep = () => { aiState.goal = $('aiGoal').value; aiState.name = $('aiName').value; aiState.dur = +$('aiDur').value || 4; aiState.style = $('aiStyle').value; aiState.answer = $('aiAnswer').value; };
  body.addEventListener('input', keep);
  $('aiMake').onclick = async () => {
    keep();
    const chosen = [...$('aiAssets').selectedOptions].map(o => o.value);
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
    ${media.length ? `<div class="mrow"><button class="ghost small" id="amAll">Выбрать все</button><button class="ghost small" id="amNone">Снять все</button>
      <span class="mnote">Порядок:</span><select class="select" id="amOrder"><option value="as_is">как в списке</option><option value="shuffle">перемешать</option></select></div>
    <div class="media-pick">${media.map(m => `<div class="mp ${amState.picked.has(m.name) ? 'on' : ''}" data-n="${esc(m.name)}" title="${esc(m.name)}"><img loading="lazy" src="/api/thumb?name=${encodeURIComponent(m.name)}" alt=""><i>${m.kind === 'video' ? '▶ ' + (+m.dur).toFixed(1) + ' с' : esc(m.name.slice(0, 14))}</i></div>`).join('')}</div>`
    : `<div class="empty"><b>Нет картинок и видео</b>Загрузите их во вкладке «Медиа» (крупные фото и видео — лучше всего).</div>`}
    <h4>Музыка</h4>
    ${mus ? `<p class="mnote ok">♪ ${esc(mus.file)} — ${Math.round(mus.dur)} с${mus.tempo ? `, темп ≈ ${Math.round(mus.tempo)} уд/мин. Склейки встанут в такт.` : '. Ритм не найден — склейки будут ровными.'}</p>`
      : `<p class="mnote">Своей музыки нет — сцены получат сгенерированный звук в стиле ролика. Загрузите трек, и склейки встанут точно в такт.</p>`}
    <div class="mrow"><label class="secondary small filebtn">${icon('upload')}${mus ? 'Заменить музыку' : 'Загрузить музыку'}<input type="file" id="amMusic" accept="audio/*" hidden></label></div>
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
  const count = () => { const c = $('amCount'); if (c) c.textContent = `— выбрано ${amState.picked.size} из ${media.length}`; };
  count();
  const o = $('amOrder'); if (o) o.value = amState.order;
  body.onclick = e => {
    const st = e.target.closest('[data-style]');
    if (st) { amState.style = st.dataset.style; body.querySelectorAll('[data-style]').forEach(b => b.classList.toggle('on', b === st)); return; }
    const mp = e.target.closest('.mp');
    if (mp) { const n = mp.dataset.n; amState.picked.has(n) ? amState.picked.delete(n) : amState.picked.add(n); mp.classList.toggle('on'); count(); return; }
    if (e.target.closest('#amAll')) { amState.picked = new Set(media.map(m => m.name)); body.querySelectorAll('.mp').forEach(m => m.classList.add('on')); count(); }
    if (e.target.closest('#amNone')) { amState.picked = new Set(); body.querySelectorAll('.mp').forEach(m => m.classList.remove('on')); count(); }
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
    keep(); openAutomontage();
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
})();
