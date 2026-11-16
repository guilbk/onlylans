(function (root) {
  const PG = root.PG = root.PG || {};

  const NAMES = ['menu', 'about', 'play', 'result'];
  const MEDAL_NAMES = ['без медалі', 'Бронза', 'Срібло', 'Золото', 'Легенда'];
  const MEDAL_COLORS = ['#8a96b3', '#cd7f32', '#c0c8d8', '#ffd700', '#b48cff'];
  const RESULT_DELAY_MS = 700;
  const MEDAL_DELAY_MS = 700;

  const HERO_SVG = '<svg viewBox="0 0 64 64" width="64" height="64" aria-hidden="true">' +
    '<circle cx="32" cy="32" r="31" fill="#0e1424" stroke="#3df5b0" stroke-width="2"/>' +
    '<path d="M12 56c2-12 10-17 20-17s18 5 20 17z" fill="#2a3350"/>' +
    '<circle cx="32" cy="30" r="11" fill="#f1c9a5"/>' +
    '<path d="M19 27c1-9 8-14 14-14s12 5 13 14z" fill="#3df5b0"/>' +
    '<rect x="17" y="25" width="30" height="5" rx="2.5" fill="#1fa97c"/>' +
    '<path d="M32 28h19c0 3-4 5-9 5h-10z" fill="#1fa97c"/>' +
    '<circle cx="28" cy="33" r="1.4" fill="#0e1424"/><circle cx="36" cy="33" r="1.4" fill="#0e1424"/>' +
    '<path d="M28 38c2 2 6 2 8 0" stroke="#0e1424" stroke-width="1.6" fill="none" stroke-linecap="round"/>' +
    '</svg>';

  const dom = {};
  const cards = {};
  const diffBtns = [];
  let resultToken = 0;
  let medalTimer = 0;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function btn(cls, label) {
    const b = el('button', cls, label);
    b.type = 'button';
    return b;
  }

  function screenEl(name) {
    return name === 'menu' ? dom.menu : name === 'about' ? dom.about : name === 'result' ? dom.result : null;
  }

  function isOpen(idx) {
    return !(PG.progress && PG.progress.isOpen) || PG.progress.isOpen(idx);
  }

  function bestMedal(idx) {
    const b = PG.progress && PG.progress.best ? PG.progress.best(idx) : null;
    return b && b.medal > 0 ? b.medal : 0;
  }

  function setScreen(name) {
    if (NAMES.indexOf(name) < 0) return;
    PG.screen = name;
    for (let i = 0; i < NAMES.length; i++) {
      const e = screenEl(NAMES[i]);
      if (!e) continue;
      const on = NAMES[i] === name;
      e.hidden = !on;
      e.classList.toggle('active', on);
      e.classList.toggle('hidden', !on);
    }
    document.body.setAttribute('data-screen', name);
    if (name !== 'result') {
      resultToken++;
      if (medalTimer) { clearTimeout(medalTimer); medalTimer = 0; }
    }
    PG.bus.emit('ui:screen', { name: name });
  }

  function start(idx) {
    if (!PG.engine || !PG.data || !PG.data.shifts[idx]) return;
    if (PG.progress && PG.progress.difficulty) PG.engine.config.difficulty = PG.progress.difficulty();
    resultToken++;
    PG.engine.newGame(idx);
    setScreen('play');
  }

  // First open shift without a medal; the last shift when all are medalled.
  function playIdx() {
    if (PG.progress && PG.progress.nextIdx) {
      const n = PG.progress.nextIdx();
      if (typeof n === 'number' && PG.data.shifts[n]) return n;
    }
    const n = PG.data.shifts.length;
    for (let i = 0; i < n; i++) if (isOpen(i) && bestMedal(i) < 1) return i;
    return 0;
  }

  function refreshMenu() {
    const shifts = PG.data.shifts;
    for (let i = 0; i < shifts.length; i++) {
      const c = cards[shifts[i].id];
      if (!c) continue;
      const open = isOpen(i);
      c.el.classList.toggle('locked', !open);
      c.el.disabled = !open;
      c.el.classList.toggle('next', PG.progress && PG.progress.nextIdx ? PG.progress.nextIdx() === i : false);
      const m = bestMedal(i);
      c.medal.textContent = m > 0 ? MEDAL_NAMES[m] : (open ? '' : 'закрито');
      c.medal.style.setProperty('--c', MEDAL_COLORS[m]);
      c.medal.classList.toggle('has', m > 0);
    }
  }

  function buildCard(sh, idx) {
    const b = btn('shift-card');
    b.id = 'shift-' + sh.id;
    const slot = PG.C.SLOTS[sh.slot];
    const ico = el('span', 'slot-ico');
    ico.setAttribute('data-slot', sh.slot);
    const info = el('span', 'shift-info');
    info.appendChild(el('span', 'shift-name', sh.name));
    info.appendChild(el('span', 'shift-time', slot ? slot.label : ''));
    const dots = el('span', 'diff-dots');
    dots.title = 'Складність ' + sh.difficulty + ' з 5';
    for (let i = 1; i <= 5; i++) dots.appendChild(el('i', i <= sh.difficulty ? 'on' : ''));
    const medal = el('span', 'shift-medal');
    b.appendChild(ico);
    b.appendChild(info);
    b.appendChild(dots);
    b.appendChild(medal);
    b.addEventListener('click', function () { if (isOpen(idx)) start(idx); });
    cards[sh.id] = { el: b, medal: medal };
    return b;
  }

  function buildMenu() {
    const m = dom.menu;
    m.textContent = '';
    const head = el('div', 'menu-head');
    const hero = el('div', 'hero-icon');
    hero.innerHTML = HERO_SVG;
    head.appendChild(hero);
    const tt = el('div', 'menu-titles');
    tt.appendChild(el('h1', 'menu-title', '7 ланосів'));
    tt.appendChild(el('div', 'menu-hero', 'Ріїн Гіслінг проти 7 ланосів'));
    head.appendChild(tt);
    m.appendChild(head);
    m.appendChild(el('p', 'menu-pitch',
      'Справжня зміна таксі в Порту, 2014. Обжени найкращого водія — його привид їде поруч.'));
    const play = btn('btn-big', 'Грати');
    play.id = 'btn-play';
    play.addEventListener('click', function () { start(playIdx()); });
    m.appendChild(play);
    buildDifficulty(m);
    buildHowTo(m);
    const about = btn('btn-link', 'Про дані');
    about.id = 'btn-about';
    about.addEventListener('click', function () { setScreen('about'); });
    m.appendChild(about);

    const list = el('div', 'shift-list');
    list.id = 'shiftList';
    const shifts = PG.data.shifts;
    let lastDay = null;
    let group = null;
    for (let i = 0; i < shifts.length; i++) {
      if (shifts[i].day !== lastDay) {
        lastDay = shifts[i].day;
        group = el('div', 'day-group');
        group.appendChild(el('h2', 'day-title', lastDay));
        list.appendChild(group);
      }
      group.appendChild(buildCard(shifts[i], i));
    }
    m.appendChild(list);
    refreshMenu();
  }

  function refreshDifficulty() {
    const d = PG.progress && PG.progress.difficulty ? PG.progress.difficulty() : 'normal';
    for (let i = 0; i < diffBtns.length; i++) {
      const on = diffBtns[i].getAttribute('data-diff') === d;
      diffBtns[i].classList.toggle('on', on);
      diffBtns[i].setAttribute('aria-pressed', on ? 'true' : 'false');
    }
  }

  function buildDifficulty(m) {
    const P = PG.progress;
    if (!P || !P.setDifficulty) return;
    const box = el('div', 'diff-choice');
    box.id = 'diff-choice';
    box.appendChild(el('span', 'diff-label', 'Складність'));
    diffBtns.length = 0;
    for (let i = 0; i < P.DIFFS.length; i++) {
      const b = btn('diff-btn', P.DIFF_LABEL[P.DIFFS[i]]);
      b.setAttribute('data-diff', P.DIFFS[i]);
      b.addEventListener('click', function () { P.setDifficulty(b.getAttribute('data-diff')); refreshDifficulty(); });
      diffBtns.push(b);
      box.appendChild(b);
    }
    m.appendChild(box);
    refreshDifficulty();
  }

  function buildHowTo(m) {
    const P = PG.progress;
    if (!P || !P.HOWTO) return;
    const box = el('div', 'howto');
    box.id = 'howto';
    box.appendChild(el('h2', null, 'Як грати'));
    for (let i = 0; i < P.HOWTO.length; i++) box.appendChild(el('p', null, P.HOWTO[i]));
    m.appendChild(box);
  }

  function listBlock(title, items, cls) {
    const box = el('div', 'about-block ' + cls);
    box.appendChild(el('h2', null, title));
    const ul = el('ul');
    for (let i = 0; i < items.length; i++) ul.appendChild(el('li', null, items[i]));
    box.appendChild(ul);
    return box;
  }

  function buildAbout() {
    const a = dom.about;
    a.textContent = '';
    a.appendChild(el('h1', 'about-title', 'Про дані'));
    a.appendChild(el('p', 'about-src',
      'Джерело: UCI Machine Learning Repository, набір 339 «Taxi Service Trajectory» (ECML PKDD 2015), ' +
      'ліцензія CC BY 4.0. Один тиждень травня 2014 року, Порту.'));
    a.appendChild(listBlock('Це дані (з архіву, обчислено нашим кодом)', [
      'поїздки: де й коли їх викликали', 'водії: скільки кожен заробив за зміну',
      'маршрути: реальні треки поїздок', 'привид: найкращий водій зміни та його маршрут',
      'рейтинг, медіана та верхні 10 %', 'гарячі точки та хвилі попиту', 'граф доріг',
    ], 'about-data'));
    a.appendChild(listBlock('Це ігрова модель (вигадана нами)', [
      'тариф: 3,25 + 0,50 €/км (×1,2 вночі)', 'час ×40: 2 години зміни за 3 хвилини',
      'видимість і радіус замовлень', 'чайові та комбо', 'типи пасажирів',
      '7 ланосів: суперники з ШІ', 'медалі',
    ], 'about-model'));
    const back = btn('btn-big', 'Назад');
    back.id = 'btn-about-back';
    back.addEventListener('click', function () { setScreen('menu'); });
    a.appendChild(back);
  }

  function stat(label, value, cls) {
    const s = el('div', 'res-stat' + (cls ? ' ' + cls : ''));
    s.appendChild(el('span', 'res-stat-val', value));
    s.appendChild(el('span', 'res-stat-label', label));
    return s;
  }

  function raceTable(rows) {
    const box = el('div', 'res-race');
    box.appendChild(el('h2', null, 'Перегони 7 ланосів'));
    for (let i = 0; i < rows.length; i++) {
      const row = el('div', 'race-row' + (rows[i].me ? ' me' : ''));
      const dot = el('i', 'race-dot');
      dot.style.background = rows[i].color;
      row.appendChild(dot);
      row.appendChild(el('span', 'race-name', rows[i].name + ' «' + rows[i].nick + '»'));
      row.appendChild(el('span', 'race-rides', String(rows[i].rides)));
      row.appendChild(el('span', 'race-total', PG.util.eur(rows[i].total)));
      box.appendChild(row);
    }
    return box;
  }

  function showResult(r) {
    const U = PG.util;
    const res = dom.result;
    const G = PG.engine && PG.engine.G;
    const view = PG.progress && PG.progress.resultView ? PG.progress.resultView(r, G) : {
      record: false, bestEarned: 0, placeText: '', race: [], unlockedNext: false };
    res.textContent = '';
    const hero = el('div', 'hero-icon small');
    hero.innerHTML = HERO_SVG;
    res.appendChild(hero);
    const title = el('h1', 'res-title', 'Ріїн Гіслінг заробив ' + U.eur(r.earned));
    title.id = 'res-earned';
    res.appendChild(title);
    res.appendChild(el('div', 'res-rank', '#' + r.rank + ' з ' + r.nDrivers + ' справжніх водіїв'));
    const medal = el('div', 'res-medal');
    medal.id = 'res-medal';
    res.appendChild(medal);
    if (view.record) res.appendChild(el('div', 'res-record', 'Новий рекорд!'));
    else if (view.bestEarned > 0) res.appendChild(el('div', 'res-best', 'Найкраще: ' + U.eur(view.bestEarned)));
    if (view.unlockedNext && r.medal >= 1) res.appendChild(el('div', 'res-unlock', 'Відкрито наступну зміну'));

    const stats = el('div', 'res-stats');
    stats.appendChild(stat(U.plural(r.rides, 'поїздка', 'поїздки', 'поїздок'), String(r.rides)));
    stats.appendChild(stat('простій', r.idlePct + ' %'));
    const vs = Math.round(r.vsGhost * 100) / 100;
    stats.appendChild(stat('до привида', (vs >= 0 ? '+' : '−') + U.eur(Math.abs(vs)), vs > 0 ? 'ahead' : 'behind'));
    if (r.tips > 0) stats.appendChild(stat('чайові', U.eur(r.tips)));
    if (r.bestCombo > 1) stats.appendChild(stat('найкраще комбо', '×' + r.bestCombo));
    res.appendChild(stats);

    if (view.placeText) res.appendChild(el('div', 'res-place', view.placeText));
    if (view.race.length) res.appendChild(raceTable(view.race));

    const row = el('div', 'res-buttons');
    const again = btn('btn-big', 'Ще раз');
    again.id = 'btn-again';
    again.addEventListener('click', function () { start(r.idx); });
    const next = btn('btn-big alt', 'Далі');
    next.id = 'btn-next';
    next.addEventListener('click', function () {
      const n = r.idx + 1;
      if (PG.data.shifts[n] && isOpen(n)) start(n); else PG.screens.showMenu();
    });
    const menu = btn('btn-big alt', 'Меню');
    menu.id = 'btn-result-menu';
    menu.addEventListener('click', function () { PG.screens.showMenu(); });
    row.appendChild(again);
    row.appendChild(next);
    row.appendChild(menu);
    res.appendChild(row);

    setScreen('result');
    const token = resultToken;
    medalTimer = setTimeout(function () {
      medalTimer = 0;
      if (token !== resultToken) return;
      medal.textContent = MEDAL_NAMES[r.medal];
      medal.style.setProperty('--c', MEDAL_COLORS[r.medal]);
      medal.classList.add('shown');
      PG.bus.emit('medal', { level: r.medal });
    }, MEDAL_DELAY_MS);
  }

  // ---- onboarding hints (first shift): wait for the subject to be on screen ----
  const hintOut = { x: 0, y: 0, hx: 0, hy: 0 };
  const hintCtx = { pin: false, ghost: false, bar: false };
  let hintEl = null;
  let hintUntil = 0;
  let hintNext = 0;
  let hintShown = 0;

  function onScreen(p, W, H) { return p.x > 20 && p.x < W - 20 && p.y > 90 && p.y < H - 70; }

  function hintTick(e) {
    if (!PG.progress || !PG.progress.hintDue || PG.screen !== 'play' || !hintEl) return;
    const now = e.now;
    if (hintShown && now >= hintUntil) { hintEl.classList.remove('on'); hintShown = 0; }
    if (hintShown || now < hintNext) return;
    hintNext = now + 0.4;
    const G = PG.engine && PG.engine.G;
    const R = PG.render;
    if (!G || G.over || G.paused || !R || !R.P) return;
    const stage = document.getElementById('stage');
    const W = stage ? stage.clientWidth : 0, H = stage ? stage.clientHeight : 0;
    hintCtx.pin = hintCtx.ghost = false;
    hintCtx.bar = G.t > 20;
    const os = G.sh.orders;
    for (let i = 0; i < os.length; i++) {
      const o = os[i];
      if (o.t < G.t || o.t - G.t > 800) continue;
      if (PG.engine.reachable(o) && onScreen(R.P(o.x0, o.y0), W, H)) { hintCtx.pin = true; break; }
    }
    if (PG.data.ghostAt) {
      PG.data.ghostAt(G.sh, G.t, hintOut);
      hintCtx.ghost = onScreen(R.P(hintOut.x, hintOut.y), W, H);
    }
    const h = PG.progress.hintDue(hintCtx);
    if (!h) return;
    hintEl.textContent = h.text;
    hintEl.classList.add('on');
    PG.progress.markHint(h.n);
    hintShown = h.n;
    hintUntil = now + 6;
    hintNext = now + 7;
  }

  function showMenu() {
    if (dom.menu) { refreshMenu(); refreshDifficulty(); }
    setScreen('menu');
  }

  function init() {
    dom.menu = document.getElementById('menu');
    dom.about = document.getElementById('about');
    dom.result = document.getElementById('result');
    if (!dom.menu || !PG.data) return;
    buildMenu();
    if (dom.about) buildAbout();
    const stage = document.getElementById('stage');
    if (stage && PG.progress && PG.progress.hintDue) {
      hintEl = el('div', 'hint-card');
      hintEl.id = 'hint-card';
      stage.appendChild(hintEl);
      PG.bus.on('frame', hintTick);
      PG.bus.on('shift:start', function () { hintShown = 0; hintEl.classList.remove('on'); hintNext = 0; });
      PG.bus.on('ui:screen', function (e) { if (e.name !== 'play') { hintEl.classList.remove('on'); hintShown = 0; } });
    }
    PG.bus.on('shift:end', function (e) {
      const r = e && e.result;
      if (!r) return;
      const token = ++resultToken;
      setTimeout(function () {
        if (token === resultToken && PG.screen === 'play') showResult(r);
      }, RESULT_DELAY_MS);
    });
    setScreen('menu');
  }

  PG.screen = 'menu';
  PG.screens = { init: init, setScreen: setScreen, showMenu: showMenu, start: start, showResult: showResult };
})(typeof window !== 'undefined' ? window : globalThis);
