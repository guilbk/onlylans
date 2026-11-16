(function (root) {
  const PG = root.PG = root.PG || {};
  const HAS_DOM = typeof document !== 'undefined';

  // Call-type colours (CONTRACT §14): A amber, B cyan, C coral.
  const COL = ['#ffc857', '#5ee6ff', '#ff7a90'];
  const CALL_FALLBACK = ['Виклик', 'Стоянка', 'З вулиці'];
  const DASH_ROUTE = [7, 6];
  const DASH_NONE = [];
  const ROUTE_REFRESH_M = 250;     // re-route only if the start moved this far
  const ROUTE_REFRESH_MS = 1000;   // ... and not more often than this

  const S = {
    selected: null,   // order selected by a touch tap (or null)
    hovered: null,    // order under the mouse (or null)
    touch: false,     // last pointer was touch/pen
    tapped: false,    // tap() was called during the current gesture
    card: null, els: null, cardKey: '', cardW: 0, cardH: 0, cardMode: '',
    route: null, routeOrd: null, routeFx: 0, routeFy: 0, routeAt: 0, routeRoads: false,
    hinted: false, inited: false
  };

  const orders = PG.orders = {
    init: init,
    hover: hover,
    tap: tap,
    clear: clear,
    selected: null
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
    S.hovered = null;
    S.route = null; S.routeOrd = null;
    if (S.card) S.card.className = 'order-card hidden';
    S.cardKey = '';
  }

  function hover(o) {
    if (S.touch && o) return;           // touch has no hover
    if (S.selected) return;             // a selection wins over hover
    S.hovered = o || null;
    if (o) markHint();
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
    S.hovered = null;
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
    ctx.lineWidth = 2; ctx.strokeStyle = '#e8eefc'; ctx.fillStyle = col;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, y - 20); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x, y - 20); ctx.lineTo(x + 13, y - 15); ctx.lineTo(x, y - 10); ctx.closePath(); ctx.fill();
    ctx.beginPath(); ctx.arc(x, y, 3, 0, 6.2832); ctx.fillStyle = '#e8eefc'; ctx.fill();
    ctx.restore();
  }

  function drawPreview(ctx, now) {
    const g = G();
    const o = S.selected || S.hovered;
    if (!g || !o || !PG.render || !PG.engine) return;
    if (g.over || o.t <= g.t) { if (S.selected === o) clear(); else S.hovered = null; return; }
    const pv = PG.engine.preview(o);
    if (!pv) return;
    const hoverOnly = !S.selected;
    if (hoverOnly && !pv.ok) return;       // unreachable: no preview on hover
    ensureRoute(o, pv, now);
    const col = COL[o.c] || COL[0];
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
    ctx.setLineDash(r ? DASH_NONE : DASH_ROUTE);
    ctx.lineDashOffset = r ? 0 : shift;
    ctx.strokeStyle = '#e8eefc'; ctx.lineWidth = 2.5;
    ctx.stroke();

    // 2) passenger's trip along the real GPS points
    const pts = o.pts;
    ctx.beginPath(); ctx.moveTo(px, py);
    for (let i = 1; i < pts.n; i++) { p = P(pts.xs[i], pts.ys[i]); ctx.lineTo(p.x, p.y); }
    ctx.setLineDash(DASH_NONE);
    ctx.strokeStyle = col; ctx.lineWidth = 4;
    ctx.stroke();

    // 3) pickup ring and drop-off flag
    ctx.beginPath(); ctx.arc(px, py, 12, 0, 6.2832);
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
      els.type.style.color = COL[o.c] || COL[0];
      els.fare.textContent = eur(o.fare);
      els.km.textContent = (Math.round(o.km * 10) / 10).toString().replace('.', ',') + ' км';
      els.eta.textContent = 'доїзд ' + mins(pv.eta);
      els.wait.textContent = pv.ok ? 'чекає ще ' + mins(pv.wait) : 'не встигнеш';
      els.wait.className = pv.ok ? 'oc-wait' : 'oc-wait oc-bad';
      els.btn.style.display = selected && pv.ok ? '' : 'none';
      els.btn.textContent = g.mode === 'ride' ? 'Беру наступним' : 'Беру';
      S.card.className = 'order-card' + (selected ? ' sel' : ' hov');
      S.cardW = S.card.offsetWidth; S.cardH = S.card.offsetHeight;
    }
    place(px, py);
  }

  // Keep the card on screen and off the player's car.
  function place(px, py) {
    const st = S.stage, g = G(), c = S.card;
    if (!st) return;
    const W = st.clientWidth, H = st.clientHeight;
    const car = PG.render.P(g.x, g.y);
    const cx = car.x, cy = car.y;
    const w = S.cardW, h = S.cardH, m = 8;
    const phone = W <= 640;
    let mode, left, top;
    if (phone) {
      // docked bottom; switch to the top if the car would be hidden
      const dockH = parseFloat(st.style.getPropertyValue('--dock-h')) || 0;
      const botTop = H - h - m - dockH;
      const hidden = cy > botTop - 14 && cy < H;
      mode = hidden ? 'top' : 'bottom';
      left = 0;
      top = mode === 'top' ? Math.round(m + (parseFloat(st.style.getPropertyValue('--hud-h')) || 0)) : 0;
    } else {
      mode = 'float';
      left = px + 22; top = py - h / 2;
      if (left + w > W - m) left = px - 22 - w;
      if (left < m) left = m;
      if (top < m) top = m;
      if (top + h > H - m) top = H - m - h;
      if (cx > left - 14 && cx < left + w + 14 && cy > top - 14 && cy < top + h + 14) {
        top = cy < H / 2 ? H - m - h : m;                  // jump to the far side of the car
      }
      left = Math.round(left); top = Math.round(top);
    }
    const k = mode + left + ':' + top;
    if (k === S.cardMode) return;
    S.cardMode = k;
    c.style.left = phone ? '50%' : left + 'px';
    if (mode === 'bottom') { c.style.top = ''; c.style.bottom = 'var(--dock-h, 70px)'; }
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
      '<div class="oc-row"><span class="oc-type"></span><span class="oc-fare"></span></div>' +
      '<div class="oc-row oc-sub"><span class="oc-km"></span><span class="oc-eta"></span></div>' +
      '<div class="oc-wait"></div>' +
      '<button type="button" class="oc-btn">Беру</button>';
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
