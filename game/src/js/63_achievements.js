(function (root) {
  const PG = root.PG = root.PG || {};

  // Achievements (CONTRACT §18): 12 badges, thresholds come from Python (achievements.json).
  // Progress is counted from PG.bus events; nothing of the other modules is edited.
  const KEY = 'porto-lanosiv-achievements-v1';
  const TOAST_MS = 3000;

  let doc = null;           // parsed achievements.json (null = no badges in this build)
  let loaded = false;
  let st = fresh();
  let panel = null;
  let queue = [];
  let qBusy = false;

  function fresh() { return { v: 1, p: {}, done: {}, seen: [], days: [] }; }
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function hasDom() { return typeof document !== 'undefined' && !!document.getElementById('menu'); }
  function party() { return !!(PG.engine && PG.engine.party); }
  function store() {
    try { return typeof window !== 'undefined' ? window.localStorage : null; } catch (e) { return null; }
  }
  function save() {
    try { const ls = store(); if (ls) ls.setItem(KEY, JSON.stringify(st)); } catch (e) { /* kept in memory */ }
  }
  function strs(a) { return Array.isArray(a) ? a.filter(function (s) { return typeof s === 'string'; }) : []; }
  function load() {
    try {
      const ls = store();
      const o = ls && ls.getItem(KEY) ? JSON.parse(ls.getItem(KEY)) : null;
      if (!o || typeof o !== 'object') return;
      ['p', 'done'].forEach(function (k) {
        Object.keys(o[k] || {}).forEach(function (id) {
          const v = +o[k][id];
          if (isFinite(v) && v > 0) st[k][id] = k === 'done' ? 1 : v;
        });
      });
      st.seen = strs(o.seen);
      st.days = strs(o.days);
    } catch (e) { st = fresh(); }
  }
  function readDoc() {
    if (loaded) return;
    loaded = true;
    load();
    if (PG.ACHIEVEMENTS) { doc = PG.ACHIEVEMENTS; return; }
    try {
      const e = typeof document !== 'undefined' ? document.getElementById('achievements-data') : null;
      if (e) doc = JSON.parse(e.textContent);
    } catch (err) { doc = null; }
  }
  function badge(id) {
    const list = doc && doc.badges ? doc.badges : [];
    for (let i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  function val(id) { return Math.floor(Math.min(st.p[id] || 0, (badge(id) || { n: 0 }).n)); }

  // ---- unlock + toasts (one at a time so none hides another) ----
  function toastNext() {
    if (!queue.length) { qBusy = false; return; }
    qBusy = true;
    if (PG.bus) PG.bus.emit('note', { text: '🏅 Досягнення: ' + queue.shift(), ms: TOAST_MS });
    setTimeout(toastNext, TOAST_MS + 200);
  }
  function check(id) {
    const b = badge(id);
    if (!b || st.done[id] || (st.p[id] || 0) < b.n) return;
    st.done[id] = 1;
    queue.push(b.title);
    if (!qBusy) toastNext();
  }
  function add(id, k) {
    if (!badge(id) || st.done[id]) return;
    st.p[id] = (st.p[id] || 0) + k;
    check(id);
  }
  function top(id, v) {
    if (!badge(id) || st.done[id] || v <= (st.p[id] || 0)) return;
    st.p[id] = v;
    check(id);
  }
  function mark(id, key, list) {
    if (!badge(id) || st.done[id] || list.indexOf(key) >= 0) return;
    list.push(key);
    st.p[id] = list.length;
    check(id);
  }
  function near(x, y, px, py, r) { return Math.hypot(px - x, py - y) <= r; }

  // ---- progress from events ----
  function onDropoff(p) {
    const o = p && p.o;
    if (!o || party()) return;
    readDoc();
    if (!doc) return;
    add('pax', 1);
    const a = badge('airport');
    if (a && (near(a.x, a.y, o.x0, o.y0, a.r) || near(a.x, a.y, o.x1, o.y1, a.r))) add('airport', 1);
    const l = badge('long');
    if (l && o.km >= l.km) add('long', 1);
    const d = badge('districts');
    if (d) {
      d.spots.forEach(function (s) {
        if (near(s.x, s.y, o.x0, o.y0, d.r) || near(s.x, s.y, o.x1, o.y1, d.r)) mark('districts', s.name, st.seen);
      });
    }
    save();
  }
  function onCombo(p) {
    if (!p || party()) return;
    readDoc();
    top('combo', p.n | 0);
    save();
  }
  function onEnd(p) {
    const r = p && p.result;
    if (!r || party()) return;
    readDoc();
    if (!doc) return;
    const sid = String(r.shiftId || '');
    const day = sid.split('-')[0];
    if (/-night$/.test(sid)) add('night', 1);
    if (day) mark('week', day, st.days);
    if (r.medal >= 3) add('ghost', 1);
    if (r.medal >= 2) add('top10', 1);
    if (r.racePlace === 1 && r.raceSize >= 8) add('rivals', 1);
    if (r.medal === 4 && (doc.weekend || []).indexOf(day) >= 0) add('legend', 1);
    if (r.earned > 0 && badge('money') && !st.done.money) { st.p.money = (st.p.money || 0) + r.earned; check('money'); }
    save();
  }

  // ---- interface: a button in the menu and a grid of badges ----
  function count() { return Object.keys(st.done).length; }
  function paintPanel() {
    panel.textContent = '';
    const box = el('div', 'ach-box');
    const head = el('div', 'ach-head');
    head.appendChild(el('h2', 'ach-title', 'Досягнення ' + count() + '/' + doc.badges.length));
    const close = el('button', 'ach-close', '✕');
    close.type = 'button';
    close.setAttribute('aria-label', 'Закрити');
    close.addEventListener('click', function () { panel.hidden = true; });
    head.appendChild(close);
    box.appendChild(head);
    const grid = el('div', 'ach-grid');
    doc.badges.forEach(function (b) {
      const got = !!st.done[b.id];
      const card = el('div', 'ach-card' + (got ? ' got' : ''));
      card.appendChild(el('div', 'ach-icon', b.icon));
      card.appendChild(el('div', 'ach-name', b.title));
      card.appendChild(el('div', 'ach-desc', b.desc));
      const bar = el('div', 'ach-bar');
      const fill = el('i');
      fill.style.width = Math.round(100 * (got ? b.n : val(b.id)) / b.n) + '%';
      bar.appendChild(fill);
      card.appendChild(bar);
      card.appendChild(el('div', 'ach-num', got ? '✓ Отримано' : (b.id === 'money' ? '€' : '') + val(b.id) + ' / ' + (b.id === 'money' ? '€' : '') + b.n));
      grid.appendChild(card);
    });
    box.appendChild(grid);
    panel.appendChild(box);
  }
  function openPanel() {
    if (!panel) {
      panel = el('div', 'ach-panel');
      panel.id = 'ach-panel';
      panel.addEventListener('click', function (e) { if (e.target === panel) panel.hidden = true; });
      document.body.appendChild(panel);
    }
    paintPanel();
    panel.hidden = false;
  }
  function paintMenu() {
    readDoc();
    if (!doc || !hasDom() || document.getElementById('ach-open')) return;
    const menu = document.getElementById('menu');
    const b = el('button', 'btn-link ach-open', '🏅 Досягнення');
    b.type = 'button';
    b.id = 'ach-open';
    b.addEventListener('click', openPanel);
    menu.insertBefore(b, document.getElementById('shiftList') || menu.querySelector('.menu-note'));
  }
  function onScreen(p) {
    if (!p || !hasDom()) return;
    if (p.name !== 'menu' && panel) panel.hidden = true;
    if (p.name === 'menu') paintMenu();
  }

  const bus = PG.bus;
  if (bus) {
    bus.on('dropoff', onDropoff);
    bus.on('combo', onCombo);
    bus.on('shift:end', onEnd);
    bus.on('ui:screen', onScreen);
  }

  PG.achievements = {
    done: function (id) { return !!st.done[id]; },
    progress: val,
    _reset: function () { doc = null; loaded = false; st = fresh(); queue = []; qBusy = false; },
  };
})(typeof window !== 'undefined' ? window : globalThis);
