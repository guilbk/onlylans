(function (root) {
  const PG = root.PG = root.PG || {};

  // Guided first shift (steps a-f) and, once it is done, three contextual hints.
  const STEPS = [
    'Світлі кружки з €# — замовлення. Торкнись одного',
    'Це маршрут до пасажира і до прапорця. Торкнись ще раз або «Беру»',
    'Їдеш до пасажира. Гроші — коли пасажир сяде',
    'Пасажир у машині — веземо до прапорця. Наступне замовлення можна взяти вже зараз',
    'Бузкова машина — привид, найкращий справжній водій цієї зміни. Обжени його',
    'Угорі — твоє місце серед водіїв і медалі. Бронза відкриває наступну зміну'
  ];
  const DWELL_S = [0, 0, 0, 6, 7, 7];   // real seconds a step stays at least (0: waits for the player)
  const TEXT = {
    idle: 'Є замовлення поруч: торкнись світлого кружка з €#',
    none: 'Поруч замовлень немає: торкнись мапи, щоб поїхати туди, де їх більше',
    expired: 'Замовлення згасло. На картці зелений рядок — встигаєш, червоний — ні',
    stolen: 'Суперник приїхав раніше. Бери замовлення ближче до машини: там ти перший'
  };
  const IDLE_S = 15;
  const HINT_S = 6.5;
  const COOLDOWN_S = 20;
  const MAX_IDLE = 3;
  const PLACE_EVERY_S = 0.25;

  const S = {
    on: false, step: 0, dwell: 0, card: null, skip: null, stage: null,
    text: '', until: 0, kind: '', lastAt: -1e9, idle: 0, idleN: 0, shown: {}, pending: '', lastSel: null,
    placeAt: 0, top: true, tgt: null
  };
  const pt = { k: '', x: 0, y: 0, rx: 0, ry: 0, rw: 0, rh: 0 };   // where the pointer is drawn: '', 'pt' or 'rect'

  function G() { return PG.engine && PG.engine.G; }

  function aimPt(x, y) { pt.k = 'pt'; pt.x = x; pt.y = y; }

  function aimWorld(x, y) {
    const p = PG.render.P(x, y);
    aimPt(p.x, p.y);
  }

  function aimEl(sel) {
    const e = root.document.querySelector(sel);
    if (!e || !S.stage) { pt.k = ''; return; }
    const r = e.getBoundingClientRect(), s = S.stage.getBoundingClientRect();
    pt.k = 'rect'; pt.rx = r.left - s.left; pt.ry = r.top - s.top; pt.rw = r.width; pt.rh = r.height;
  }

  function onScreen(x, y) {
    const z = PG.render.zone;
    return x > 16 && x < S.stage.clientWidth - 16 && y > z.top + 10 && y < z.bottom - 10;
  }

  function bestPin() {
    const p = PG.render.pins[0];
    return p && p.reach ? p : null;
  }

  function euro(text, pin) {
    return pin ? text.replace('€#', PG.util.eur(pin.fare)) : text;
  }

  // ---- guided shift: the step follows the game state, never blocks a tap ----
  function go(n) { S.step = n; S.dwell = 0; }

  function guided(g, dt) {
    const m = g.mode, sel = PG.orders && PG.orders.selected;
    const s = S.step;
    if (!g.paused) S.dwell += dt;
    if (s <= 1) {
      if (m === 'pickup') go(2);
      else if (m === 'ride') go(3);
      else go(sel ? 1 : 0);
    } else if (s === 2) {
      if (m === 'ride') go(3);
      else if (m !== 'pickup') go(0);
    } else if (s === 3 ? (S.dwell >= DWELL_S[3] || (m !== 'ride' && S.dwell >= 3)) : S.dwell >= DWELL_S[s]) {
      if (s === 5) { finish(); return; }
      go(s + 1);
    }
    const pin = bestPin();
    S.text = STEPS[S.step];
    pt.k = '';
    if (S.step === 0) {
      if (!pin) { S.text = ''; return; }
      aimPt(pin.px, pin.py);
      S.text = euro(S.text, pin);
    } else if (S.step === 1) {
      const p = PG.render.pins.find(function (q) { return q.o === sel; });
      if (p) aimPt(p.px, p.py);
    } else if (S.step === 2 && g.cur) aimWorld(g.cur.x0, g.cur.y0);
    else if (S.step === 3 && g.cur) aimWorld(g.cur.x1, g.cur.y1);
    else if (S.step === 4) {
      const o = { x: 0, y: 0 };
      PG.data.ghostAt(g.sh, g.t, o);
      const p = PG.render.P(o.x, o.y);
      if (onScreen(p.x, p.y)) aimPt(p.x, p.y); else aimEl('#hud .hud-ghost');
    } else if (S.step === 5) aimEl('#hud .hud-ladder');
  }

  function finish() {
    S.on = false;
    S.text = '';
    if (PG.progress) PG.progress.setCoachDone(true);
  }

  // ---- contextual hints: once the guided shift is done ----
  function show(kind, text, now, tgt) {
    S.kind = kind; S.text = text; S.until = now + HINT_S; S.lastAt = now;
    S.tgt = tgt || null;
  }

  function contextual(g, e) {
    const now = e.now;
    const m = g.mode;
    if (!g.paused) S.idle = (m === 'idle' || m === 'cruise') ? S.idle + e.dt : 0;
    const sel = PG.orders && PG.orders.selected;
    if (S.lastSel && !sel && S.lastSel.t <= g.t && m !== 'pickup' && m !== 'ride') S.pending = 'expired';
    S.lastSel = sel || null;
    if (S.text && now >= S.until) { S.text = ''; S.kind = ''; }
    if (S.text || now - S.lastAt < COOLDOWN_S) return;
    const pin = bestPin();
    if (S.pending) {
      const k = S.pending;
      S.pending = '';
      if (!S.shown[k]) { S.shown[k] = true; show(k, TEXT[k], now); return; }
    }
    if (S.idle >= IDLE_S && S.idleN < MAX_IDLE) {
      S.idle = 0;
      S.idleN++;
      show('idle', pin ? euro(TEXT.idle, pin) : TEXT.none, now, pin ? 'pin' : '');
    }
  }

  // ---- card placement: top or bottom of the map, away from the target, the order card and bright pins ----
  function overlap(y, h, x0, y0, x1, y1, w, W) {
    const x = (W - w) / 2;
    return x < x1 && x + w > x0 && y < y1 && y + h > y0;
  }

  function cost(y, w, h, W) {
    const R = PG.render, g = G();
    let c = 0;
    if (pt.k === 'pt' && overlap(y, h, pt.x - 30, pt.y - 44, pt.x + 30, pt.y + 30, w, W)) c += 5000;
    if (pt.k === 'rect' && overlap(y, h, pt.rx, pt.ry, pt.rx + pt.rw, pt.ry + pt.rh, w, W)) c += 5000;
    const oc = root.document.querySelector('.order-card.sel:not(.hidden)');
    if (oc) {
      const r = oc.getBoundingClientRect(), s = S.stage.getBoundingClientRect();
      if (overlap(y, h, r.left - s.left, r.top - s.top, r.right - s.left, r.bottom - s.top, w, W)) c += 5000;
    }
    for (let i = 0; i < R.pins.length; i++) {
      const p = R.pins[i];
      if (p.reach && overlap(y, h, p.px - p.r - 4, p.py - p.r - 4, p.px + p.r + 4, p.py + p.r + 4, w, W)) c += 200;
    }
    const car = R.P(g.x, g.y);
    if (overlap(y, h, car.x - 24, car.y - 24, car.x + 24, car.y + 24, w, W)) c += 1500;
    return c;
  }

  function place(now) {
    if (now < S.placeAt) return;
    S.placeAt = now + PLACE_EVERY_S;
    const z = PG.render.zone, W = S.stage.clientWidth;
    const w = S.card.offsetWidth, h = S.card.offsetHeight;
    const yTop = z.top + 6, yBot = z.bottom - h - 6;
    const ct = cost(yTop, w, h, W), cb = cost(yBot, w, h, W);
    S.top = S.top ? ct <= cb + 300 : ct + 300 < cb;
    S.card.style.top = Math.round(S.top ? yTop : yBot) + 'px';
  }

  function tick(e) {
    const g = G();
    if (!S.card || PG.screen !== 'play' || !g || !g.sh || g.over || !PG.render || !PG.render.P) {
      pt.k = '';
      if (S.card) S.card.classList.remove('on');
      return;
    }
    if (S.on) guided(g, e.dt);
    else {
      contextual(g, e);
      pt.k = '';
      if (S.text && S.tgt === 'pin') {
        const p = bestPin();
        if (p) aimPt(p.px, p.py);
      }
    }
    const on = !!S.text;
    if (on && S.card.textContent !== S.text) S.card.textContent = S.text;
    S.card.classList.toggle('on', on);
    S.skip.classList.toggle('on', S.on);
    if (on) place(e.now);
    else pt.k = '';
  }

  function draw(ctx, now) {
    if (!pt.k) return;
    const k = PG.REDUCED ? 0 : Math.sin(now * 5);
    ctx.lineWidth = 3;
    ctx.strokeStyle = '#ffc857';
    ctx.fillStyle = '#ffc857';
    if (pt.k === 'pt') {
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 24 + 3 * k, 0, 6.2832);
      ctx.stroke();
      const up = pt.y - 70 > PG.render.zone.top;
      const y = up ? pt.y - 34 - 3 * k : pt.y + 34 + 3 * k;
      const d = up ? 1 : -1;
      ctx.beginPath();
      ctx.moveTo(pt.x, y);
      ctx.lineTo(pt.x - 9, y - 14 * d);
      ctx.lineTo(pt.x + 9, y - 14 * d);
      ctx.closePath();
      ctx.fill();
    } else {
      const g = 3 + 2 * k;
      ctx.lineWidth = 2;
      ctx.strokeRect(pt.rx - g, pt.ry - g, pt.rw + 2 * g, pt.rh + 2 * g);
    }
  }

  // Run the guided shift again on the next shift (from «Як грати»).
  function rearm() { if (PG.progress) PG.progress.setCoachDone(false); }

  function begin() {
    const hostView = root.document.body.classList.contains('party-host');
    S.on = !hostView && !!PG.progress && !PG.progress.coachDone();
    S.step = 0; S.dwell = 0; S.text = ''; S.kind = ''; S.until = 0;
    S.idle = 0; S.idleN = 0; S.shown = {}; S.pending = ''; S.lastSel = null; S.lastAt = -1e9;
  }

  function init() {
    const R = PG.render;
    const stage = root.document.getElementById('stage');
    if (S.card || !stage || !R || !R.onDraw) return;
    S.stage = stage;
    S.card = root.document.createElement('div');
    S.card.className = 'coach-card';
    S.card.id = 'coach-card';
    stage.appendChild(S.card);
    S.skip = root.document.createElement('button');
    S.skip.type = 'button';
    S.skip.className = 'coach-skip';
    S.skip.id = 'coach-skip';
    S.skip.textContent = 'Зрозуміло';
    const host = root.document.getElementById('hud-extra') || root.document.getElementById('hud');
    host.insertBefore(S.skip, host.firstChild);
    S.skip.addEventListener('click', finish);
    R.onDraw(draw, 50);
    PG.bus.on('frame', tick);
    PG.bus.on('shift:start', begin);
    PG.bus.on('order:lost', function (e) { if (!S.on && e) S.pending = e.by === 'real' ? 'expired' : 'stolen'; });
    const stop = function () { S.on = false; S.text = ''; pt.k = ''; S.card.classList.remove('on'); S.skip.classList.remove('on'); };
    PG.bus.on('shift:end', stop);
    PG.bus.on('ui:screen', function (e) { if (e && e.name !== 'play') stop(); });
  }

  PG.coach = { init: init, rearm: rearm };
})(typeof window !== 'undefined' ? window : globalThis);
