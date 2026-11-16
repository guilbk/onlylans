(function (root) {
  const PG = root.PG = root.PG || {};
  const bus = PG.bus;
  if (!bus || typeof document === 'undefined') return;

  // First-encounter hints (once per player) and the «Як грати» sheet. Subscribes at load: boot has no slot for it.
  const KEY = 'porto-ghost-hints-v1';
  const SHOW_S = 5;
  const HINTS = {
    pin: 'Яскравий кружок із сумою — замовлення, яке можна взяти. Торкнись: побачиш маршрут. Ще раз — поїхали.',
    ring: 'Кільце навколо кружка — скільки лишилось часу. Згасло — замовлення пішло.',
    dot: 'Сіра крапка — замовлення ще далеко. Під’їдь ближче, і воно засвітиться.',
    ghost: 'Бузкова машина — привид, найкращий водій цієї зміни. Заробляй більше за нього.',
    speed: '×3 — гра швидше, «Пауза» — зупинка. Кнопки внизу.',
    combo: 'Комбо: замовлення поспіль дають бонус. Не барися між ними.',
    stars: 'Завдання зміни дають зірки. Тут — найближче.',
    next: 'Пасажир у машині. Наступне замовлення можна взяти вже зараз.'
  };
  let done = null, card = null, cur = '', timer = 0, queue = [], playT = 0, sheet = null, pausedBy = false;

  function load() {
    if (done) return;
    try { done = JSON.parse(root.localStorage.getItem(KEY)) || {}; } catch (e) { done = {}; }
  }
  function save() {
    try { root.localStorage.setItem(KEY, JSON.stringify(done)); } catch (e) { /* memory only */ }
  }
  function G() { return PG.engine && PG.engine.G; }
  function playing() { return PG.screen === 'play' && !!G() && !G().over; }
  function rect(sel, s) {
    const e = document.querySelector(sel);
    if (!e) return null;
    const r = e.getBoundingClientRect();
    return r.width ? { l: r.left - s.left, t: r.top - s.top, r: r.right - s.left, b: r.bottom - s.top } : null;
  }
  function hit(a, b) { return !!b && a.l < b.r && a.r > b.l && a.t < b.b && a.b > b.t; }

  // Near the thing it explains, never over the HUD, the dispatch bar or the order card.
  function place(id, s) {
    const w = card.offsetWidth, h = card.offsetHeight;
    const hud = rect('#hud', s), dsp = rect('#dispatch', s), oc = rect('#order-card', s);
    const zm = rect('#map-zoom', s), ct = rect('#map-center', s);
    const top = hud ? hud.b + 8 : 8, bot = dsp ? dsp.t - 8 : s.height - 8;
    let ax = s.width / 2, ay = top;
    const p = PG.render && PG.render.pins && PG.render.pins[0];
    if ((id === 'pin' || id === 'ring' || id === 'next') && p) { ax = p.px; ay = p.py + 36; }
    else if (id === 'stars') {
      const c = rect('#msn-chip', s);
      if (c) { ax = (c.l + c.r) / 2; ay = c.b + 8; }
    } else if (id === 'speed') ay = bot - h;
    const x = Math.max(8, Math.min(s.width - w - 8, ax - w / 2));
    const tries = [ay, ay - 72 - h, top, bot - h];
    let y = top;
    for (let i = 0; i < tries.length; i++) {
      const b = { l: x, t: tries[i], r: x + w, b: tries[i] + h };
      if (b.t >= top && b.b <= bot && !hit(b, oc) && !hit(b, zm) && !hit(b, ct)) { y = tries[i]; break; }
    }
    card.style.transform = 'translate(' + Math.round(x) + 'px,' + Math.round(y) + 'px)';
  }

  function hide() {
    root.clearTimeout(timer);
    if (card) card.classList.remove('on');
    cur = '';
    if (queue.length) root.setTimeout(next, 300);
  }
  function next() {
    if (cur || !queue.length || !playing() || (sheet && !sheet.hidden)) return;
    if (PG.overlay && PG.overlay.busy(card)) { root.setTimeout(next, 700); return; }   // one card at a time: wait for the other
    const id = queue.shift();
    const st = document.getElementById('stage');
    if (!st) return;
    if (!card) {
      card = document.createElement('div');
      card.className = 'hint-card';
      card.setAttribute('role', 'status');
      card.addEventListener('click', hide);
      st.appendChild(card);
    }
    card.textContent = HINTS[id];
    cur = id;
    place(id, st.getBoundingClientRect());
    card.classList.add('on');
    root.clearTimeout(timer);
    timer = root.setTimeout(hide, SHOW_S * 1000);
  }
  function want(id) {
    load();
    if (done[id] || !playing() || queue.indexOf(id) >= 0 || cur === id) return;
    if (PG.coach && PG.coach.active && PG.coach.active() && (id === 'pin' || id === 'ring' || id === 'next' || id === 'ghost' || id === 'stars')) return;   // the coach says it
    done[id] = 1;
    save();
    queue.push(id);
    next();
  }

  // ---- «Як грати» ----
  const RIV = [['#ff8a3d', 'Ашот'], ['#f4d03f', 'Тьотя Валя'], ['#4db8ff', 'Камран'], ['#ff4d6a', 'Зіна'],
    ['#ff6ec7', 'ОлеКсій'], ['#a0e85b', 'Люда'], ['#fff', 'Стьопа']];
  const GUIDE = [
    ['🎯', 'Мета', ['Заробити за зміну більше, ніж справжні водії Порту.', '<b>Бронза</b> — не гірше за середнього водія.',
      '<b>Срібло</b> — серед найкращих 10 %.', '<b>Золото</b> — більше за привид.', '<b>Легенда</b> — у 1,25 раза більше за привид.']],
    ['👆', 'Керування', ['Торкнись кружка (клік) — побачиш маршрут. Ще раз або «Беру» — береш замовлення.',
      'Колесо або щипок — масштаб. Тягни — рухаєш мапу.', '«×3» — швидше, «Пауза» — стоп (також пробіл).']],
    ['📍', 'Мапа', ['Яскравий кружок із кільцем — замовлення; кільце — скільки лишилось часу.', 'Сіра крапка — замовлення ще далеко.',
      'Золоте — плата ×2.', 'Бузкова машина — привид, найкращий водій зміни.', 'Сім суперників: §.']],
    ['💶', 'Гроші', ['Плата за поїздку: €3,25 + €0,50 за км.', 'Вночі плата ×1,2.', 'Чайові — за швидку подачу й приємну поїздку.',
      'Комбо: замовлення поспіль дають бонус — не барися між ними.']],
    ['👥', 'Гра разом', ['Хто завгодно створює кімнату й показує код для сканування та номер кімнати.', 'Решта сканує код телефоном або вводить номер.',
      'Одна мапа для всіх: замовлення бере хто встиг першим.']]
  ];
  function buildSheet() {
    sheet = document.createElement('div');
    sheet.className = 'help-sheet';
    sheet.hidden = true;
    sheet.addEventListener('click', function (e) { if (e.target === sheet) closeSheet(); });
    const dots = RIV.map(function (r) {
      return '<span class="help-dot" style="background:' + r[0] + '"></span>' + r[1];
    }).join(', ');
    const tabs = GUIDE.map(function (g, i) {
      return '<button type="button" class="g-tab' + (i ? '' : ' on') + '" data-i="' + i + '"><span aria-hidden="true">' + g[0] + '</span> ' + g[1] + '</button>';
    }).join('');
    const secs = GUIDE.map(function (g, i) {
      return '<section class="g-sec' + (i ? '' : ' on') + '" data-i="' + i + '"><h3><span class="g-ico" aria-hidden="true">' + g[0] + '</span>' + g[1] +
        '</h3><ul>' + g[2].map(function (t) { return '<li>' + t.replace('§', dots) + '</li>'; }).join('') + '</ul></section>';
    }).join('');
    sheet.innerHTML = '<div class="help-box" role="dialog" aria-modal="true" aria-label="Як грати">' +
      '<button type="button" class="help-x" aria-label="Закрити">✕</button><h2>Як грати</h2>' +
      '<div class="g-tabs" role="tablist">' + tabs + '</div><div class="g-body">' + secs + '</div>' +
      '<button type="button" class="help-reset">Скинути підказки</button></div>';
    sheet.querySelector('.help-x').addEventListener('click', closeSheet);
    sheet.querySelectorAll('.g-tab').forEach(function (t) {
      t.addEventListener('click', function () {
        sheet.querySelectorAll('.g-tab, .g-sec').forEach(function (n) { n.classList.toggle('on', n.getAttribute('data-i') === t.getAttribute('data-i')); });
      });
    });
    sheet.querySelector('.help-reset').addEventListener('click', function () {
      done = {}; queue = []; save(); bus.emit('note', { text: 'Підказки знову увімкнено', ms: 1800 });
    });
    document.body.appendChild(sheet);
  }
  function openSheet() {
    if (!sheet) buildSheet();
    if (cur) hide();
    sheet.hidden = false;
    const g = G();
    if (playing() && !g.paused && !g.party) { g.paused = true; pausedBy = true; bus.emit('pause', { paused: true }); }
    sheet.querySelector('.help-x').focus();
  }
  function closeSheet() {
    if (!sheet || sheet.hidden) return;
    sheet.hidden = true;
    const g = G();
    if (pausedBy && g && g.paused) { g.paused = false; bus.emit('pause', { paused: false }); }
    pausedBy = false;
    next();
  }
  function mkBtn(cls) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'help-btn ' + cls; b.id = 'help-' + cls;
    b.setAttribute('aria-label', 'Як грати'); b.textContent = '?';
    b.addEventListener('click', function (e) { e.stopPropagation(); openSheet(); });
    return b;
  }
  function mount() {
    const extra = document.getElementById('hud-extra') || document.getElementById('hud');
    if (extra && !document.getElementById('help-hud')) extra.appendChild(mkBtn('hud'));
  }

  root.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && sheet && !sheet.hidden) { e.stopImmediatePropagation(); closeSheet(); }
  }, true);
  bus.on('ui:screen', function (p) {
    mount();
    if (p.name !== 'play') { queue = []; if (cur) hide(); closeSheet(); } else playT = 0;
  });
  bus.on('shift:end', function () { queue = []; if (cur) hide(); });
  bus.on('pickup', function () { want('next'); });
  bus.on('combo', function () { want('combo'); });
  bus.on('ghost:overtake', function () { want('ghost'); });   // no event for the first sight of the ghost: also a timer below
  bus.on('frame', function (p) {
    const g = G();
    if (!playing() || g.paused) return;
    playT += p.dt;
    const pins = PG.render && PG.render.pins;
    if (pins && pins.length) { want('pin'); want('ring'); if (playT > 12) want('dot'); }
    if (playT > 10) want('ghost');
    if (playT > 20) want('speed');
    if (playT > 6 && document.getElementById('msn-chip')) want('stars');
  });
  PG.hints = { open: openSheet };
})(typeof window !== 'undefined' ? window : globalThis);
