(function (root) {
  const PG = root.PG = root.PG || {};
  const HAS_DOM = typeof document !== 'undefined';

  // Call-type colours (CONTRACT §14): A amber, B cyan, C coral.
  const pal = function () { return (PG.theme && PG.theme.pal) || PG.C.THEMES.night; };
  const CALL_FALLBACK = ['Виклик', 'Стоянка', 'З вулиці'];
  const DASH_ROUTE = [7, 6];
  const DASH_NONE = [];
  const HOVER_MS = 6000;           // a hover card never stays longer than this
  const ROUTE_REFRESH_M = 250;     // re-route only if the start moved this far
  const HOVER_MS = 6000;           // a hover card never stays longer than this
  const ROUTE_REFRESH_MS = 1000;   // ... and not more often than this

  const S = {
    selected: null,   // order selected by a touch tap (or null)
    hovered: null,    // order under the mouse (or null)
    touch: false,     // last pointer was touch/pen
    tapped: false,    // tap() was called during the current gesture
    card: null, els: null, cardKey: '', cardW: 0, cardH: 0, cardMode: '', cand: -1, phoneTop: false,
    route: null, routeOrd: null, routeFx: 0, routeFy: 0, routeAt: 0, routeRoads: false,
    hinted: false, inited: false, hoverAt: 0
  };

  const orders = PG.orders = {
    init: init,
    hover: hover,
    tap: tap,
    clear: clear,
    hideHover: function () { if (!S.selected) hover(null); },
    blocks: blocks,
    selected: null,
    hovered: null   // order under the mouse: the camera holds still while it is set
  };

  function G() { return PG.engine && PG.engine.G; }

  function setSelected(o) { S.selected = o; orders.selected = o; }

  function markHint() {
    if (S.hinted) return;
    S.hinted = true;
    try { if (PG.progress && PG.progress.markHint) PG.progress.markHint(1); } catch (e) { /* hint is optional */ }
  }

  function clear() {
    setSelected(null);
    S.hovered = null; orders.hovered = null;
    S.route = null; S.routeOrd = null;
    if (S.card) S.card.className = 'order-card hidden';
    S.cardKey = '';
    S.cardMode = '';        // the class list was reset, so the next place() must run in full
    S.cand = -1;
  }

  function hideCard() {
    if (!S.card || S.card.classList.contains('hidden')) return;
    S.card.className = 'order-card hidden';
    S.cardKey = ''; S.cardMode = ''; S.cand = -1;
  }

  function hover(o) {
    if (S.touch && o) return;           // touch has no hover
    if (S.selected) return;             // a selection wins over hover
    S.hovered = o || null;
    orders.hovered = S.hovered;
    S.hoverAt = Date.now();
    if (o) markHint(); else hideCard();   // the card leaves with the pointer
  }

  // Take the order: pickup, or book-next while riding. On refusal keep the card
  // (the engine shows its own toast).
  function take(o) {
    const E = PG.engine;
    const g = G();
    if (!E || !g || !o) return false;
    const ok = g.mode === 'ride' ? E.bookNext(o) : E.startPickup(o);
    if (ok) clear();
    return !!ok;
  }

  function tap(o) {
    S.tapped = true;
    if (!o) { clear(); return; }
    if (!S.touch) { take(o); return; }      // mouse: one click takes at once
    if (S.selected === o) { take(o); return; }
    setSelected(o);
    S.hovered = null; orders.hovered = null;
    S.route = null; S.routeOrd = null;
    markHint();
  }

  // ---- preview geometry -------------------------------------------------
  function ensureRoute(o, pv, now) {
    const roads = PG.roads;
    const on = !!(roads && roads.enabled);
    const moved = Math.hypot(pv.fromX - S.routeFx, pv.fromY - S.routeFy);
    const stale = S.routeOrd !== o || on !== S.routeRoads ||
      (moved > ROUTE_REFRESH_M && now - S.routeAt > ROUTE_REFRESH_MS);
    if (!stale) return;
    S.routeOrd = o; S.routeRoads = on; S.routeAt = now;
    S.routeFx = pv.fromX; S.routeFy = pv.fromY;
    S.route = on ? roads.route(pv.fromX, pv.fromY, o.x0, o.y0) : null;
  }

  function drawFlag(ctx, x, y, col) {
    ctx.save();
    ctx.lineWidth = 2; ctx.strokeStyle = pal().flag; ctx.fillStyle = col;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, y - 20); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x, y - 20); ctx.lineTo(x + 13, y - 15); ctx.lineTo(x, y - 10); ctx.closePath(); ctx.fill();
    ctx.beginPath(); ctx.arc(x, y, 3, 0, 6.2832); ctx.fillStyle = pal().flag; ctx.fill();
    ctx.restore();
  }

  function drawPreview(ctx, now) {
    const g = G();
    let o = S.selected || S.hovered;
    if (o && !S.selected && Date.now() - S.hoverAt > HOVER_MS) { S.hovered = null; orders.hovered = null; o = null; }
    if (!g || !o || !PG.render || !PG.engine) { hideCard(); return; }
    if (g.over || o.t <= g.t) { if (S.selected === o) clear(); else { S.hovered = null; orders.hovered = null; hideCard(); } return; }
    const pv = PG.engine.preview(o);
    if (!pv) { hideCard(); return; }
    const hoverOnly = !S.selected;
    if (hoverOnly && !pv.ok) { hideCard(); return; }       // unreachable: no preview on hover
    ensureRoute(o, pv, now);
    const col = pal().pins[o.c] || pal().pins[0];
    const P = PG.render.P;
    const shift = PG.REDUCED ? 0 : -((now / 40) % 26);   // marching dashes

    ctx.save();
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    ctx.globalAlpha = pv.ok ? 1 : 0.5;

    // 1) car -> pickup
    let p = P(pv.fromX, pv.fromY);
    const fx = p.x, fy = p.y;
    ctx.beginPath(); ctx.moveTo(fx, fy);
    const r = S.route;
    if (r && r.n > 1) {
      for (let i = 1; i < r.n; i++) { p = P(r.xs[i], r.ys[i]); ctx.lineTo(p.x, p.y); }
    }
    p = P(o.x0, o.y0);
    const px = p.x, py = p.y;
    ctx.lineTo(px, py);
    ctx.setLineDash(DASH_ROUTE);
    ctx.lineDashOffset = shift;
    ctx.strokeStyle = pal().ink; ctx.lineWidth = 2;
    ctx.globalAlpha = pv.ok ? 0.6 : 0.3;
    ctx.stroke();
    ctx.globalAlpha = pv.ok ? 1 : 0.5;

    // 2) passenger's trip along the real GPS points
    const pts = o.pts;
    ctx.beginPath(); ctx.moveTo(px, py);
    for (let i = 1; i < pts.n; i++) { p = P(pts.xs[i], pts.ys[i]); ctx.lineTo(p.x, p.y); }
    ctx.setLineDash(DASH_ROUTE);
    ctx.lineDashOffset = shift;
    ctx.globalAlpha = pv.ok ? 0.6 : 0.3;
    ctx.strokeStyle = col; ctx.lineWidth = 2.5;
    ctx.stroke();
    ctx.globalAlpha = pv.ok ? 1 : 0.5;
    ctx.setLineDash(DASH_NONE);

    // 3) pickup ring and drop-off flag
    ctx.beginPath(); ctx.arc(px, py, 26, 0, 6.2832);
    ctx.lineWidth = 2.5; ctx.strokeStyle = col; ctx.stroke();
    p = P(o.x1, o.y1);
    drawFlag(ctx, p.x, p.y, col);
    ctx.restore();

    updateCard(o, pv, px, py, !hoverOnly);
  }

  // ---- card -------------------------------------------------------------
  function mins(sec) { return Math.max(1, Math.round(sec / 60)) + ' хв'; }

  function callName(c) {
    const n = PG.C && PG.C.CALL_NAMES;
    return (n && n[c]) || CALL_FALLBACK[c] || '';
  }

  function eur(x) { return PG.util && PG.util.eur ? PG.util.eur(x) : '€' + x.toFixed(2).replace('.', ','); }

  function updateCard(o, pv, px, py, selected) {
    if (!HAS_DOM || !S.card) return;
    const g = G();
    const key = o.i + '|' + (pv.ok ? 1 : 0) + '|' + Math.round(pv.eta / 60) + '|' +
      Math.round(pv.wait / 60) + '|' + (selected ? 1 : 0) + '|' + g.mode;
    const els = S.els;
    if (key !== S.cardKey) {
      S.cardKey = key;
      els.type.textContent = callName(o.c);
      els.fare.textContent = eur(o.fare);
      els.km.textContent = (Math.round(o.km * 10) / 10).toString().replace('.', ',') + ' км';
      els.eta.textContent = 'доїзд ' + mins(pv.eta);
      els.wait.textContent = pv.ok ? (g.mode === 'ride' ? 'наступним · ' : '') + 'чекає ще ' + mins(pv.wait) : 'не встигнеш';
      els.wait.className = pv.ok ? 'oc-wait' : 'oc-wait oc-bad';
      els.btn.style.display = selected && pv.ok ? '' : 'none';
      els.btn.textContent = 'Взяти';
      const cl = S.card.classList;
      cl.remove('hidden');
      cl.toggle('sel', selected);
      cl.toggle('hov', !selected);
      cl.toggle('dock', S.stage.clientWidth <= 640);   // measure at the final width
      S.cardMode = '';
      S.cardW = S.card.offsetWidth; S.cardH = S.card.offsetHeight;
    }
    place(px, py);
  }

  // True when a tap at client (x, y) lands on or right next to the open card:
  // such a tap must not clear the selection or send the car cruising.
  function blocks(x, y) {
    if (!S.card || !S.card.classList.contains('sel')) return false;
    const r = S.card.getBoundingClientRect(), m = 10;
    return x >= r.left - m && x <= r.right + m && y >= r.top - m && y <= r.bottom + m;
  }

  function hits(x, y, w, h, bx, by, bw, bh) {
    return x < bx + bw && x + w > bx && y < by + bh && y + h > by;
  }

  // Cost of a card rectangle: the car, the pin itself and other bright pins must stay visible.
  function cost(x, y, w, h, px, py, cx, cy, pins) {
    let c = 0;
    if (hits(x, y, w, h, cx - 22, cy - 22, 44, 44)) c += 4000;
    if (hits(x, y, w, h, px - 20, py - 20, 40, 40)) c += 6000;
    for (let i = 0; i < pins.length; i++) {
      const p = pins[i];
      if (!p.reach || (Math.abs(p.px - px) < 3 && Math.abs(p.py - py) < 3)) continue;
      if (hits(x, y, w, h, p.px - p.r - 4, p.py - p.r - 4, 2 * p.r + 8, 2 * p.r + 8)) c += 1500;
    }
    return c;
  }

  // Keep the card on screen, off the HUD and dispatch bar, off the car and off neighbouring pins.
  function place(px, py) {
    const st = S.stage, g = G(), c = S.card, R = PG.render;
    if (!st || !R) return;
    const z = R.zone, pins = R.pins;
    const W = st.clientWidth, H = st.clientHeight;
    const car = R.P(g.x, g.y);
    const cx = car.x, cy = car.y;
    const w = S.cardW, h = S.cardH, m = 8, gap = 26;
    const phone = W <= 640;
    const top0 = z.top + m, bot0 = Math.min(H, z.bottom) - m;
    let k, left = 0, top = 0, bottom = 0;
    if (phone) {
      // docked full width: bottom by default, top when the bottom one would hide the car or the pin
      const bx = (W - w) / 2;
      const cb = cost(bx, bot0 - h, w, h, px, py, cx, cy, pins);
      const ct = cost(bx, top0, w, h, px, py, cx, cy, pins);
      const atTop = ct - (S.phoneTop ? 300 : 0) < cb - (S.phoneTop ? 0 : 300);
      S.phoneTop = atTop;
      k = atTop ? 'top' : 'bottom';
      top = Math.round(top0);
      bottom = Math.round(H - bot0);
    } else {
      const lo = Math.max(top0, 0), hi = bot0 - h;
      const cand = [
        [px + gap, py - h / 2], [px - gap - w, py - h / 2],
        [px - w / 2, py + gap], [px - w / 2, py - gap - h - 18],
        [px + gap, py - h - 10], [px - gap - w, py - h - 10], [px + gap, py + 10], [px - gap - w, py + 10],
        [px + 2.4 * gap, py - h / 2], [px - 2.4 * gap - w, py - h / 2],
      ];
      let best = -1, bc = Infinity;
      for (let i = 0; i < cand.length; i++) {
        const x = Math.min(Math.max(cand[i][0], m), W - m - w);
        const y = Math.min(Math.max(cand[i][1], lo), Math.max(lo, hi));
        // prefer the first candidates; a card pushed far from its pin costs more; stay with the last choice
        const cc = cost(x, y, w, h, px, py, cx, cy, pins) + i * 40 +
          Math.hypot(x - cand[i][0], y - cand[i][1]) * 3 - (i === S.cand ? 250 : 0);
        if (cc < bc) { bc = cc; best = i; left = x; top = y; }
      }
      S.cand = best;
      left = Math.round(left); top = Math.round(top);
      k = 'float';
    }
    const key = k + left + ':' + top + ':' + bottom + ':' + W + ':' + H;
    if (key === S.cardMode) return;
    S.cardMode = key;
    c.style.left = phone ? '50%' : left + 'px';
    if (k === 'bottom') { c.style.top = ''; c.style.bottom = bottom + 'px'; }
    else { c.style.top = top + 'px'; c.style.bottom = ''; }
    c.classList.toggle('dock', phone);
  }

  // ---- init -------------------------------------------------------------
  function init() {
    if (S.inited) return;
    S.inited = true;
    if (PG.bus) {
      const drop = function () { clear(); };
      PG.bus.on('shift:start', drop);
      PG.bus.on('shift:end', drop);
      PG.bus.on('ui:screen', drop);
      PG.bus.on('order:lost', function (e) { if (e && (e.o === S.selected || e.o === S.hovered)) clear(); });
    }
    if (PG.render && PG.render.onDraw) PG.render.onDraw(drawPreview, 5);
    if (!HAS_DOM) return;

    const stage = S.stage = document.getElementById('stage');
    const card = S.card = document.createElement('div');
    card.id = 'order-card';
    card.className = 'order-card hidden';
    card.innerHTML =
      '<div class="oc-main"><div class="oc-row"><span class="oc-fare"></span><span class="oc-type"></span></div>' +
      '<div class="oc-row oc-sub"><span class="oc-km"></span><span class="oc-eta"></span></div>' +
      '<div class="oc-wait"></div></div>' +
      '<button type="button" class="oc-btn">Взяти</button>';
    S.els = {
      type: card.querySelector('.oc-type'), fare: card.querySelector('.oc-fare'),
      km: card.querySelector('.oc-km'), eta: card.querySelector('.oc-eta'),
      wait: card.querySelector('.oc-wait'), btn: card.querySelector('.oc-btn')
    };
    (stage || document.body).appendChild(card);

    // The card is its own touch target: its events never reach the map.
    const stop = function (e) { e.stopPropagation(); };
    ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'touchstart', 'touchend', 'click'].forEach(function (n) {
      card.addEventListener(n, stop);
    });
    S.els.btn.addEventListener('click', function () { if (S.selected) take(S.selected); });

    // Pointer kind: decides one-click (mouse) vs two-step (touch/pen).
    const kind = function (e) { S.touch = !!(e.pointerType && e.pointerType !== 'mouse'); S.tapped = false; };
    window.addEventListener('pointerdown', kind, true);
    window.addEventListener('touchstart', function () { S.touch = true; S.tapped = false; }, { capture: true, passive: true });
    // A gesture that did not reach tap() (map tap, empty space) clears the selection.
    window.addEventListener('click', function () {
      if (S.selected && !S.tapped) clear();
    });
  }
})(typeof window !== 'undefined' ? window : globalThis);
