(function (root) {
  const PG = root.PG = root.PG || {};

  const MEDAL_COLORS = ['#8a96b3', '#cd7f32', '#c0c8d8', '#ffd700', '#b48cff'];
  const TOAST_MS = 2400;

  const dom = {};
  const last = {
    g: null, clock: '', money: '', rank: '', ghost: '', delta: '', ahead: null,
    prog: -1, mark: -1, level: -1, paused: null, fast: null, toast: '',
  };
  let toastTimer = 0;

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
    top.appendChild(dom.clock);
    top.appendChild(dom.money);
    top.appendChild(dom.rank);

    const ghost = el('div', 'hud-ghost');
    ghost.appendChild(el('span', 'hud-label', 'Привид '));
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
    dom.ladder = lad;

    dom.extra = el('div', null);
    dom.extra.id = 'hud-extra';

    hud.appendChild(top);
    hud.appendChild(ghost);
    hud.appendChild(prog);
    hud.appendChild(lad);
    hud.appendChild(dom.extra);
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
    for (let i = 0; i < 4; i++) dom.ticks[i].style.left = pct(vals[i], thr.legend) + '%';
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
    const hud = document.getElementById('hud');
    const dsp = document.getElementById('dispatch');
    if (hud && !dom.clock) buildHud(hud);
    if (dsp && !dom.pause) buildDispatch(dsp);
    PG.bus.on('note', function (e) { if (e && e.text) showToast(e.text, e.ms); });
    PG.bus.on('shift:start', hideToast);
    PG.bus.on('shift:end', hideToast);
    PG.bus.on('ui:screen', function (e) { if (e && e.name !== 'play') hideToast(); });
  }

  PG.hud = { init: init, update: update };
})(typeof window !== 'undefined' ? window : globalThis);
