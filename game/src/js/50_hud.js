(function (root) {
  const PG = root.PG = root.PG || {};

  const MEDAL_COLORS = ['var(--muted)', 'var(--bronze)', 'var(--silver)', 'var(--gold)', 'var(--legend)'];
  const MEDAL_NAMES = ['', 'Бронза', 'Срібло', 'Золото', 'Легенда'];
  const TOAST_MS = 2400;

  const dom = {};
  const last = {
    g: null, clock: '', money: '', rank: '', ghost: '', delta: '', ahead: null,
    prog: -1, mark: -1, level: -1, paused: null, fast: null, toast: '',
  };
  let toastTimer = 0;

  // ---- theme: «Авто» follows the shift hour (night 21..04); the choice is remembered ----
  const THEME_KEY = 'porto.theme';
  const MODES = [['auto', 'Авто'], ['day', 'День'], ['night', 'Ніч']];
  const themeSt = { mode: 'auto', hour: null, btns: [] };

  function isNight(h) { return h >= PG.C.NIGHT_FROM || h < PG.C.NIGHT_TO; }

  function themeName() {
    if (themeSt.mode !== 'auto') return themeSt.mode;
    const h = themeSt.hour !== null ? themeSt.hour : new Date().getHours();   // before any shift: the local clock
    return isNight(h) ? 'night' : 'day';
  }

  function applyTheme() {
    const name = themeName();
    const changed = PG.theme.name !== name;
    PG.theme.name = name;
    PG.theme.mode = themeSt.mode;
    PG.theme.pal = PG.C.THEMES[name];
    document.body.setAttribute('data-theme', name);
    const meta = document.querySelector('meta[name=theme-color]');
    if (meta) meta.setAttribute('content', name === 'night' ? '#0b1430' : '#eddfc2');
    themeSt.btns.forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.mode === themeSt.mode ? 'true' : 'false'); });
    if (changed && PG.bus) PG.bus.emit('theme', { name: name });
  }

  PG.theme = {
    name: '', mode: 'auto', pal: PG.C.THEMES.night,
    set(mode) {
      if (mode !== 'auto' && mode !== 'day' && mode !== 'night') return;
      themeSt.mode = mode;
      try { root.localStorage.setItem(THEME_KEY, mode); } catch (e) { /* ignore */ }
      applyTheme();
    },
    hour(h) { themeSt.hour = h; applyTheme(); },
  };

  function buildThemeSeg() {
    const seg = el('div', 'hud-seg');
    seg.setAttribute('role', 'group');
    seg.setAttribute('aria-label', 'Тема');
    MODES.forEach(function (m) {
      const b = el('button', null, m[1]);
      b.type = 'button';
      b.dataset.mode = m[0];
      b.addEventListener('click', function () { PG.theme.set(m[0]); });
      seg.appendChild(b);
      themeSt.btns.push(b);
    });
    return seg;
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function button(id, label, aria) {
    const b = el('button', 'dsp-btn', label);
    b.type = 'button';
    b.id = id;
    b.setAttribute('aria-label', aria);
    return b;
  }

  function cell(caption, value) {
    const c = el('div', 'hud-cell');
    c.appendChild(el('div', 'hud-cap', caption));
    c.appendChild(value);
    return c;
  }

  function buildHud(hud) {
    const top = el('div', 'hud-top');
    dom.clock = el('div', 'hud-clock', '--:--');
    dom.money = el('div', 'hud-money', '€0,00');
    dom.rank = el('div', 'hud-rank-wrap');
    dom.rankNum = el('span', null, '#–');
    dom.rankNum.id = 'hud-rank';
    dom.rank.appendChild(dom.rankNum);
    dom.rank.appendChild(el('span', 'hud-label', ' з … водіїв'));
    dom.rankTail = dom.rank.lastChild;
    top.appendChild(cell('час зміни', dom.clock));
    top.appendChild(cell('твої гроші', dom.money));
    top.appendChild(cell('місце серед водіїв', dom.rank)).classList.add('hud-cell-rank');

    const ghost = el('div', 'hud-ghost');
    ghost.appendChild(el('span', 'hud-label', 'Привид (найкращий водій) '));
    dom.ghost = el('span', 'hud-ghost-val', '€0,00');
    dom.delta = el('span', 'hud-delta', '');
    ghost.appendChild(dom.ghost);
    ghost.appendChild(dom.delta);
    dom.ghostWrap = ghost;

    const prog = el('div', 'hud-prog');
    dom.progFill = el('div', 'hud-prog-fill');
    prog.appendChild(dom.progFill);

    const lad = el('div', 'hud-ladder');
    const track = el('div', 'hud-ladder-track');
    dom.ladFill = el('div', 'hud-ladder-fill');
    track.appendChild(dom.ladFill);
    dom.ticks = [];
    for (let i = 1; i <= 4; i++) {
      const t = el('div', 'hud-tick');
      t.style.setProperty('--c', MEDAL_COLORS[i]);
      track.appendChild(t);
      dom.ticks.push(t);
    }
    dom.mark = el('div', 'hud-mark');
    track.appendChild(dom.mark);
    lad.appendChild(track);
    const names = el('div', 'hud-medals');
    dom.names = [];
    for (let i = 1; i <= 4; i++) {
      const n = el('span', 'hud-medal' + (i === 4 ? ' last' : ''), MEDAL_NAMES[i]);
      n.style.setProperty('--c', MEDAL_COLORS[i]);
      names.appendChild(n);
      dom.names.push(n);
    }
    lad.appendChild(names);
    dom.ladder = lad;

    dom.extra = el('div', null);
    dom.extra.id = 'hud-extra';

    hud.appendChild(top);
    hud.appendChild(ghost);
    hud.appendChild(prog);
    hud.appendChild(lad);
    const tools = el('div', 'hud-tools');
    tools.appendChild(buildThemeSeg());
    tools.appendChild(dom.extra);
    hud.appendChild(tools);
  }

  function buildDispatch(box) {
    dom.pause = button('btn-pause', 'Пауза', 'Пауза');
    dom.fast = button('btn-fast', '×3', 'Швидко ×3');
    dom.menu = button('btn-menu', 'Меню', 'Меню');
    box.appendChild(dom.pause);
    box.appendChild(dom.fast);
    box.appendChild(dom.menu);
    dom.pause.addEventListener('click', function () {
      const G = PG.engine && PG.engine.G;
      if (!G || G.over) return;
      G.paused = !G.paused;
      PG.bus.emit('pause', { paused: G.paused });
    });
    dom.fast.addEventListener('click', function () {
      const G = PG.engine && PG.engine.G;
      if (!G || G.over) return;
      G.fast = !G.fast;
    });
    dom.menu.addEventListener('click', function () {
      if (PG.screens) PG.screens.showMenu();
    });
  }

  function hideToast() {
    const t = document.getElementById('toast');
    if (t) t.classList.remove('on');
    if (toastTimer) { clearTimeout(toastTimer); toastTimer = 0; }
    last.toast = '';
  }

  function showToast(text, ms) {
    const t = document.getElementById('toast');
    if (!t) return;
    t.textContent = text;
    t.classList.add('on');
    last.toast = text;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      t.classList.remove('on');
      last.toast = '';
      toastTimer = 0;
    }, ms > 0 ? ms : TOAST_MS);
  }

  function pct(v, max) {
    return max > 0 ? Math.min(100, Math.max(0, v / max * 100)) : 0;
  }

  // Place the ladder ticks once per shift.
  function setupLadder(sh) {
    const thr = sh.thr || { median: sh.median, top10: sh.top10, ghost: sh.ranking[0], legend: 1.25 * sh.ranking[0] };
    last.thr = thr;
    const vals = [thr.median, thr.top10, thr.ghost, thr.legend];
    for (let i = 0; i < 4; i++) {
      dom.ticks[i].style.left = pct(vals[i], thr.legend) + '%';
      dom.names[i].style.left = pct(vals[i], thr.legend) + '%';
    }
    last.mark = -1;
    last.level = -1;
  }

  function levelOf(thr, tot) {
    if (tot >= thr.legend) return 4;
    if (tot > thr.ghost) return 3;
    if (tot >= thr.top10) return 2;
    if (tot >= thr.median) return 1;
    return 0;
  }

  function set(node, key, val, prop) {
    if (last[key] === val) return;
    last[key] = val;
    node[prop || 'textContent'] = val;
  }

  function update() {
    if (!dom.clock) return;
    const G = PG.engine && PG.engine.G;
    if (!G || !G.sh) return;
    const U = PG.util;
    if (last.g !== G) {
      last.g = G;
      PG.theme.hour(G.sh.startHour);
      last.clock = last.money = last.rank = last.ghost = last.delta = '';
      last.ahead = null;
      last.prog = -1;
      last.paused = last.fast = null;
      setupLadder(G.sh);
      set(dom.rankTail, 'rankTail', ' з ' + G.sh.nDrivers);
    }
    set(dom.clock, 'clock', U.clock(G.sh.startHour, G.t));
    set(dom.money, 'money', U.eur(G.tot));
    set(dom.rankNum, 'rank', '#' + Math.min(G.rank, G.sh.nDrivers));
    const gm = G.ghostMoney || 0;
    set(dom.ghost, 'ghost', U.eur(gm));
    const diff = Math.round((G.tot - gm) * 100) / 100;
    const side = diff > 0 ? 1 : diff < 0 ? -1 : 0;
    set(dom.delta, 'delta', ' (' + (side > 0 ? '+' : side < 0 ? '−' : '') + U.eur(Math.abs(diff)) + ')');
    if (last.ahead !== side) {
      last.ahead = side;
      dom.ghostWrap.classList.toggle('ahead', side > 0);
      dom.ghostWrap.classList.toggle('behind', side < 0);
      dom.money.classList.toggle('ahead', side > 0);
      dom.money.classList.toggle('behind', side < 0);
    }
    const p = Math.round(Math.min(1, G.t / PG.C.SHIFT) * 1000) / 10;
    if (p !== last.prog) { last.prog = p; dom.progFill.style.width = p + '%'; }
    const m = Math.round(pct(G.tot, last.thr.legend) * 10) / 10;
    if (m !== last.mark) {
      last.mark = m;
      dom.mark.style.left = m + '%';
      dom.ladFill.style.width = m + '%';
    }
    const lv = levelOf(last.thr, G.tot);
    if (lv !== last.level) {
      last.level = lv;
      dom.mark.style.setProperty('--c', MEDAL_COLORS[lv]);
      for (let i = 0; i < 4; i++) dom.names[i].classList.toggle('got', i < lv);
    }
    if (last.paused !== !!G.paused) {
      last.paused = !!G.paused;
      dom.pause.textContent = G.paused ? 'Далі' : 'Пауза';
      dom.pause.classList.toggle('on', last.paused);
    }
    if (last.fast !== !!G.fast) {
      last.fast = !!G.fast;
      dom.fast.classList.toggle('on', last.fast);
    }
  }

  function init() {
    try {
      const m = root.localStorage.getItem(THEME_KEY);
      if (m === 'day' || m === 'night') themeSt.mode = m;
    } catch (e) { /* ignore */ }
    const hud = document.getElementById('hud');
    const dsp = document.getElementById('dispatch');
    if (hud && !dom.clock) buildHud(hud);
    if (dsp && !dom.pause) buildDispatch(dsp);
    applyTheme();
    PG.bus.on('note', function (e) { if (e && e.text) showToast(e.text, e.ms); });
    PG.bus.on('shift:start', hideToast);
    PG.bus.on('shift:end', hideToast);
    PG.bus.on('ui:screen', function (e) { if (e && e.name !== 'play') hideToast(); });
  }

  PG.hud = { init: init, update: update };
})(typeof window !== 'undefined' ? window : globalThis);
