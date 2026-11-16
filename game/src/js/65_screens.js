(function (root) {
  const PG = root.PG = root.PG || {};

  const NAMES = ['menu', 'about', 'play', 'result'];
  const MEDAL_NAMES = ['Без медалі', 'Бронза', 'Срібло', 'Золото', 'Легенда'];
  const MEDAL_COLORS = ['var(--muted)', 'var(--bronze)', 'var(--silver)', 'var(--gold)', 'var(--legend)'];
  const PARTY_NOTE = 'Гра разом працює, коли гру відкрито з ноутбука ведучого';
  const RESULT_DELAY_MS = 700;
  const MEDAL_DELAY_MS = 700;

  const HERO_SVG = '<svg viewBox="0 0 64 64" width="64" height="64" aria-hidden="true">' +
    '<circle cx="32" cy="32" r="31" style="fill:var(--card);stroke:var(--acc)" stroke-width="2"/>' +
    '<path d="M12 56c2-12 10-17 20-17s18 5 20 17z" style="fill:var(--track)"/>' +
    '<circle cx="32" cy="30" r="11" fill="#f1c9a5"/>' +
    '<path d="M19 27c1-9 8-14 14-14s12 5 13 14z" fill="#3df5b0"/>' +
    '<rect x="17" y="25" width="30" height="5" rx="2.5" fill="#1fa97c"/>' +
    '<path d="M32 28h19c0 3-4 5-9 5h-10z" fill="#1fa97c"/>' +
    '<circle cx="28" cy="33" r="1.4" style="fill:var(--text)"/><circle cx="36" cy="33" r="1.4" style="fill:var(--text)"/>' +
    '<path d="M28 38c2 2 6 2 8 0" style="stroke:var(--text)" stroke-width="1.6" fill="none" stroke-linecap="round"/>' +
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

  // The party module (80_party.js) answers 'party:open'; from a file there is no server, so say so.
  function openParty() {
    const ok = root.location.protocol !== 'file:';
    dom.partyNote.hidden = ok;
    if (ok) PG.bus.emit('party:open');
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
    dom.hero = el('div', 'menu-hero', PG.util.playerName() + ' проти 7 ланосів');
    tt.appendChild(dom.hero);
    head.appendChild(tt);
    m.appendChild(head);
    const nm = el('label', 'menu-name', 'Твоє ім’я ');
    const inp = el('input', 'menu-name-in');
    inp.id = 'player-name';
    inp.maxLength = 20;
    inp.value = PG.util.playerName();
    inp.setAttribute('aria-label', 'Твоє ім’я');
    inp.addEventListener('input', function () {
      PG.util.setPlayerName(inp.value);
      dom.hero.textContent = PG.util.playerName() + ' проти 7 ланосів';
    });
    nm.appendChild(inp);
    m.appendChild(nm);
    m.appendChild(el('p', 'menu-pitch',
      'Справжня зміна таксі в Порту, 2014. Обжени найкращого водія — його привид їде поруч.'));
    const play = btn('btn-big', 'Грати');
    play.id = 'btn-play';
    play.addEventListener('click', function () { start(playIdx()); });
    m.appendChild(play);
    const together = btn('btn-big alt', 'Гра разом');
    together.id = 'btn-party';
    together.addEventListener('click', openParty);
    m.appendChild(together);
    dom.partyNote = el('p', 'party-note', PARTY_NOTE);
    dom.partyNote.id = 'party-note';
    dom.partyNote.hidden = true;
    m.appendChild(dom.partyNote);
    buildDifficulty(m);
    buildHowTo(m);
    const about = btn('btn-link', 'Про дані');
    about.id = 'btn-about';
    about.addEventListener('click', function () { setScreen('about'); });
    m.appendChild(about);

    m.appendChild(el('p', 'menu-note',
      'Крапки на картці — складність самої зміни (1–5). Рівень суперників обирай вище.'));
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
    if (PG.coach) {
      const again = btn('btn-link', 'Пройти підказки на мапі');
      again.id = 'btn-coach';
      again.addEventListener('click', function () { PG.coach.rearm(); start(playIdx()); });
      box.appendChild(again);
    }
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
      'Джерело: UCI, набір 339 «Taxi Service Trajectory» (ECML PKDD 2015), ' +
      'ліцензія CC BY 4.0. Один тиждень травня 2014 року, Порту.'));
    a.appendChild(listBlock('Це дані (з архіву, обчислено нашим кодом)', [
      'поїздки: де й коли їх викликали', 'водії: скільки поїздок; € — за нашим тарифом',
      'маршрути: реальні треки поїздок', 'привид: найкращий водій зміни та його маршрут',
      'рейтинг, медіана та верхні 10 %', 'гарячі точки та хвилі попиту', 'де заробляли справжні таксисти: теплова мапа', 'граф доріг',
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
    const head = el('div', 'race-row race-head');
    head.appendChild(el('i', 'race-dot'));
    head.appendChild(el('span', 'race-name', 'Водій'));
    head.appendChild(el('span', 'race-rides', 'поїздки'));
    head.appendChild(el('span', 'race-total', '€ за зміну'));
    box.appendChild(head);
    for (let i = 0; i < rows.length; i++) {
      const row = el('div', 'race-row' + (rows[i].player ? ' me' : ''));
      const dot = el('i', 'race-dot');
      dot.style.background = rows[i].color;
      row.appendChild(dot);
      row.appendChild(el('span', 'race-name', (rows[i].player ? PG.util.playerName() + ' «Ти»' : rows[i].name)));
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
    const title = el('h1', 'res-title', PG.util.playerName() + ': ' + U.eur(r.earned) + ' за зміну');
    title.id = 'res-earned';
    res.appendChild(title);
    res.appendChild(el('div', 'res-rank', '#' + Math.min(r.rank, r.nDrivers) + ' з ' + r.nDrivers + ' ' +
      U.plural(r.nDrivers, 'справжнього водія', 'справжніх водіїв', 'справжніх водіїв')));
    const medal = el('div', 'res-medal');
    medal.id = 'res-medal';
    res.appendChild(medal);
    if (view.record && r.earned > 0) res.appendChild(el('div', 'res-record', 'Новий рекорд!'));
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
    PG.bus.on('shift:end', function (e) {
      const r = e && e.result;
      if (!r) return;
      const token = ++resultToken;
      setTimeout(function () {
        if (token === resultToken && PG.screen === 'play') showResult(r);
      }, RESULT_DELAY_MS);
    });
    if (PG.coach) PG.coach.init();
    setScreen('menu');
  }

  PG.screen = 'menu';
  PG.screens = { init: init, setScreen: setScreen, showMenu: showMenu, start: start, showResult: showResult };
})(typeof window !== 'undefined' ? window : globalThis);
