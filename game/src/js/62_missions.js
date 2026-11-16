(function (root) {
  const PG = root.PG = root.PG || {};

  // Missions of a shift (CONTRACT §16): three goals computed by Python from the shift's data.
  // They give stars, never money. Progress comes only from PG.bus events and read-only G.
  const KEY = 'porto-lanosiv-missions-v1';
  const CARD_MS = 8000;
  const TICK_S = 0.25;      // real s between two checks of the money and rival missions
  const DONE_TEXT = '★ Завдання виконано';

  let doc = null;           // parsed missions.json (null = no missions in this build)
  let loaded = false;
  let items = [];           // [{m, got, done, fail}] of the running shift
  let sid = null;
  let acc = 0;
  let chipText = '';
  let cardTimer = 0;
  let saved = { v: 1, best: {} };
  let chip = null;
  let card = null;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function stars(n, of) { return '★'.repeat(n) + '☆'.repeat(Math.max(0, of - n)); }
  function curG() { return PG.engine && PG.engine.G ? PG.engine.G : null; }
  function hasDom() { return typeof document !== 'undefined' && !!document.getElementById('stage'); }

  // ---- stars saved per shift (best of all tries); blocked storage = memory only ----
  function store() {
    try { return typeof window !== 'undefined' ? window.localStorage : null; } catch (e) { return null; }
  }
  function load() {
    try {
      const ls = store();
      const raw = ls ? ls.getItem(KEY) : null;
      const o = raw ? JSON.parse(raw) : null;
      if (o && o.best && typeof o.best === 'object') {
        Object.keys(o.best).forEach(function (id) {
          const n = o.best[id] | 0;
          if (n > 0 && n <= 3) saved.best[id] = n;
        });
      }
    } catch (e) { saved = { v: 1, best: {} }; }
  }
  function save() {
    try { const ls = store(); if (ls) ls.setItem(KEY, JSON.stringify(saved)); } catch (e) { /* kept in memory */ }
  }
  function best(id) { return saved.best[id] | 0; }

  function readDoc() {
    if (loaded) return;
    loaded = true;
    load();
    if (PG.MISSIONS) { doc = PG.MISSIONS; return; }
    try {
      const e = typeof document !== 'undefined' ? document.getElementById('missions-data') : null;
      if (e) doc = JSON.parse(e.textContent);
    } catch (err) { doc = null; }
  }

  function doneCount() { return items.filter(function (it) { return it.done; }).length; }

  // ---- progress ----
  function complete(it) {
    if (it.done || it.fail) return;
    it.done = true;
    it.got = it.m.n;
    if (PG.bus) PG.bus.emit('note', { text: DONE_TEXT, ms: 2400 });
    refresh();
  }
  function step(it, add) {
    if (it.done || it.fail) return;
    it.got += add;
    if (it.got >= it.m.n) complete(it); else refresh();
  }
  function near(m, x, y) { return Math.hypot(x - m.x, y - m.y) <= m.r; }

  function onDropoff(p) {
    const o = p && p.o;
    if (!o) return;
    items.forEach(function (it) {
      const m = it.m;
      if (m.kind === 'airport' && (near(m, o.x0, o.y0) || near(m, o.x1, o.y1))) step(it, 1);
      else if (m.kind === 'district' && near(m, o.x0, o.y0)) step(it, 1);
      else if (m.kind === 'long' && o.km >= m.km) step(it, 1);
    });
  }
  function onCombo(p) {
    items.forEach(function (it) { if (it.m.kind === 'combo' && p && p.n >= it.m.n) complete(it); });
  }
  function rivalOf(G, id) {
    const rv = G && G.rivals ? G.rivals : [];
    for (let i = 0; i < rv.length; i++) if (rv[i].id === id) return rv[i];
    return null;
  }

  // «earn X before the deadline»: checked at every pickup (exact time) and every tick
  function checkMoney(G, t) {
    items.forEach(function (it) {
      if (it.m.kind !== 'median' || it.done || it.fail) return;
      if (G.tot >= it.m.eur && t <= it.m.by) complete(it);
      else if (t > it.m.by) { it.fail = true; refresh(); }
    });
  }
  function onPickup() {
    const G = curG();
    if (G && items.length) checkMoney(G, G.leg && G.leg.t0 != null ? G.leg.t0 : G.t);
  }

  // text of the chip follows the rival and the money
  function tick(dt) {
    acc += dt;
    if (acc < TICK_S) return;
    acc = 0;
    const G = curG();
    if (!G || !items.length) return;
    checkMoney(G, G.t);
    paintChip();
  }

  function onEnd(p) {
    const G = curG();
    const r = p && p.result;
    items.forEach(function (it) {
      if (it.done || it.fail) return;
      if (it.m.kind === 'rival') {
        const rv = rivalOf(G, it.m.rival);
        if (rv && r && r.earned > rv.total) complete(it); else it.fail = true;
      } else if (it.m.kind === 'median' && G && G.tot >= it.m.eur && G.t <= it.m.by) {
        complete(it);
      } else {
        it.fail = true;
      }
    });
    const n = doneCount();
    if (sid && n > best(sid)) { saved.best[sid] = n; save(); }
    refresh();
  }

  function onStart(p) {
    readDoc();
    items = [];
    sid = null;
    acc = 0;
    const sh = p && p.sh;
    const list = doc && sh && doc.shifts ? doc.shifts[sh.id] : null;
    const party = PG.engine && PG.engine.party;
    if (list && !party) {
      sid = sh.id;
      items = list.map(function (m) { return { m: m, got: 0, done: false, fail: false }; });
    }
    hideCard();
    refresh();
    if (items.length) showCard(true);
  }

  // ---- interface ----
  function label(it) {
    const m = it.m;
    const G = curG();
    if (m.kind === 'rival') {
      const rv = rivalOf(G, m.rival);
      if (!rv || !G) return m.short;
      const d = Math.round((G.tot - rv.total) * 100) / 100;
      return m.short + ' ' + (d >= 0 ? '+' : '−') + PG.util.eur(Math.abs(d));
    }
    if (m.kind === 'median') return (G ? PG.util.eur(G.tot) + ' / ' : '') + m.short;
    return m.n > 1 ? m.short + ' ' + it.got + '/' + m.n : m.short;
  }

  function paintChip() {
    if (!chip) return;
    const n = doneCount();
    const next = items.filter(function (it) { return !it.done && !it.fail; })[0];
    const text = stars(n, items.length) + ' ' + (next ? label(next) : 'Завдання');
    if (text === chipText) return;
    chipText = text;
    chip.textContent = text;
  }

  function ensureDom() {
    if (!hasDom()) return false;
    if (!chip) {
      chip = el('button', 'msn-chip');
      chip.type = 'button';
      chip.id = 'msn-chip';
      chip.setAttribute('aria-label', 'Завдання зміни');
      chip.addEventListener('click', function () { showCard(card && card.classList.contains('on') ? false : true); });
      const host = document.getElementById('hud-extra') || document.getElementById('hud');
      if (host) host.insertBefore(chip, host.firstChild);
    }
    if (!card) {
      card = el('div', 'msn-card');
      card.id = 'msn-card';
      document.getElementById('stage').appendChild(card);
    }
    return true;
  }

  function paintCard() {
    if (!card) return;
    card.textContent = '';
    card.appendChild(el('div', 'msn-head', 'Завдання зміни ' + stars(doneCount(), items.length)));
    items.forEach(function (it) {
      const row = el('div', 'msn-row' + (it.done ? ' done' : it.fail ? ' fail' : ''));
      row.appendChild(el('span', 'msn-star', it.done ? '★' : '☆'));
      row.appendChild(el('span', 'msn-title', it.m.title));
      card.appendChild(row);
    });
    card.appendChild(el('div', 'msn-note', 'Зірки, не гроші. Список — на значку зверху'));
  }

  function showCard(on) {
    if (cardTimer) { clearTimeout(cardTimer); cardTimer = 0; }
    if (!ensureDom()) return;
    if (on) {
      paintCard();
      card.classList.add('on');
      cardTimer = setTimeout(function () { cardTimer = 0; card.classList.remove('on'); }, CARD_MS);
    } else {
      card.classList.remove('on');
    }
  }
  function hideCard() { if (card) showCard(false); }

  function refresh() {
    if (!ensureDom()) return;
    chip.hidden = !items.length;
    chipText = '';
    paintChip();
    if (card && card.classList.contains('on')) paintCard();
  }

  // «Завдання зміни ★★☆» on the result screen, between the stats and the race table
  function onScreen(p) {
    if (!hasDom() || !p) return;
    if (p.name !== 'play') hideCard();
    if (p.name === 'menu') paintMenu();
    if (p.name !== 'result' || !items.length) return;
    const res = document.getElementById('result');
    if (!res) return;
    const old = document.getElementById('msn-res');
    if (old) old.remove();
    const box = el('div', 'msn-res');
    box.id = 'msn-res';
    box.appendChild(el('div', 'msn-head', 'Завдання зміни ' + stars(doneCount(), items.length)));
    items.forEach(function (it) {
      const row = el('div', 'msn-row' + (it.done ? ' done' : ' fail'));
      row.appendChild(el('span', 'msn-star', it.done ? '★' : '☆'));
      row.appendChild(el('span', 'msn-title', it.m.title));
      box.appendChild(row);
    });
    res.insertBefore(box, res.querySelector('.res-place, .res-race, .res-buttons'));
  }

  // best stars on the campaign cards (own span in each card, nothing else of the menu is touched)
  function paintMenu() {
    readDoc();
    const shifts = PG.data && PG.data.shifts ? PG.data.shifts : [];
    shifts.forEach(function (sh) {
      const c = document.getElementById('shift-' + sh.id);
      if (!c) return;
      let s = c.querySelector('.msn-stars');
      const n = best(sh.id);
      if (!n) { if (s) s.remove(); return; }
      if (!s) { s = el('span', 'msn-stars'); c.insertBefore(s, c.querySelector('.shift-medal')); }
      s.textContent = stars(n, 3);
    });
  }

  const bus = PG.bus;
  if (bus) {
    bus.on('shift:start', onStart);
    bus.on('pickup', onPickup);
    bus.on('dropoff', onDropoff);
    bus.on('combo', onCombo);
    bus.on('shift:end', onEnd);
    bus.on('frame', function (e) { if (items.length) tick(e && e.dt > 0 ? e.dt : 0); });
    bus.on('ui:screen', onScreen);
  }

  PG.missions = {
    items: function () { return items; },
    stars: function () { return doneCount(); },
    best: best,
    _reset: function () { doc = null; loaded = false; items = []; saved = { v: 1, best: {} }; },
  };
})(typeof window !== 'undefined' ? window : globalThis);
