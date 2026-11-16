(function (root) {
  const PG = root.PG = root.PG || {};

  // Result story (CONTRACT §17): the player's path and the ghost's path replayed on a small map,
  // plus the facts of the shift. Reads PG.bus events and read-only G; draws only on its own canvas.
  const SAMPLE_S = 10;      // game s between two recorded positions
  const REPLAY_MS = 6000;
  const SHIFT_S = 7200;
  const PAD = 8;
  const pal = function () { return (PG.theme && PG.theme.pal) || PG.C.THEMES.night; };

  let facts = null;         // parsed facts.json (null = no facts in this build)
  let loaded = false;
  let rec = null;           // {sh, pts: [t, x, y, ...], dots: [x, y, ...], times: [t, ...], last}
  let box = null;
  let raf = 0;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function curG() { return PG.engine && PG.engine.G ? PG.engine.G : null; }

  function readFacts() {
    if (loaded) return;
    loaded = true;
    if (PG.FACTS) { facts = PG.FACTS; return; }
    try {
      const e = typeof document !== 'undefined' ? document.getElementById('facts-data') : null;
      if (e) facts = JSON.parse(e.textContent);
    } catch (err) { facts = null; }
  }

  // ---- recording ----
  function onStart(p) {
    readFacts();
    const party = PG.engine && PG.engine.party;
    rec = party || !p || !p.sh ? null : { sh: p.sh, pts: [0, PG.engine.G.x, PG.engine.G.y], dots: [], times: [], last: 0 };
  }
  function onFrame() {
    const G = curG();
    if (!rec || !G || G.t - rec.last < SAMPLE_S) return;
    rec.last = G.t;
    rec.pts.push(G.t, G.x, G.y);
  }
  function onPickup(p) {
    const G = curG();
    if (!rec || !G || !p || !p.o) return;
    rec.dots.push(p.o.x0, p.o.y0);
    rec.times.push(G.t);
  }
  function onEnd() {
    const G = curG();
    if (rec && G) rec.pts.push(Math.max(G.t, rec.last), G.x, G.y);
  }

  // ---- the ghost: its trips as timed points (15 s per point of a ride, CONTRACT §4) ----
  function ghostPath(sh) {
    const pts = [];
    const dots = [];
    (sh.ghostOrders || []).forEach(function (o) {
      dots.push(o.x0, o.y0);
      for (let i = 0; i < o.pts.n; i++) pts.push(o.t + o.pts.tRel[i], o.pts.xs[i], o.pts.ys[i]);
    });
    return { pts: pts, dots: dots };
  }

  // ---- drawing ----
  function bounds(a, b) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    [a, b].forEach(function (s) {
      for (let i = 0; i < s.length; i += 3) {
        x0 = Math.min(x0, s[i + 1]); x1 = Math.max(x1, s[i + 1]);
        y0 = Math.min(y0, s[i + 2]); y1 = Math.max(y1, s[i + 2]);
      }
    });
    return isFinite(x0) ? { x0: x0, y0: y0, w: Math.max(x1 - x0, 500), h: Math.max(y1 - y0, 500) } : null;
  }

  function trail(ctx, s, T, col, fit) {
    ctx.strokeStyle = col;
    ctx.beginPath();
    for (let i = 0; i < s.length && s[i] <= T; i += 3) {
      const x = fit.ox + (s[i + 1] - fit.b.x0) * fit.k;
      const y = fit.oy + (s[i + 2] - fit.b.y0) * fit.k;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
  function pins(ctx, d, T, col, fit, times) {
    ctx.fillStyle = col;
    for (let i = 0; i < d.length; i += 2) {
      if (times && times[i / 2] > T) continue;
      ctx.beginPath();
      ctx.arc(fit.ox + (d[i] - fit.b.x0) * fit.k, fit.oy + (d[i + 1] - fit.b.y0) * fit.k, 2.5, 0, 6.2832);
      ctx.fill();
    }
  }

  function draw(cv, you, ghost, f) {
    const ctx = cv.getContext('2d');
    const w = cv.clientWidth, h = cv.clientHeight, dpr = root.devicePixelRatio || 1;
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const b = bounds(you.pts, ghost.pts);
    if (!b) return;
    const k = Math.min((w - 2 * PAD) / b.w, (h - 2 * PAD) / b.h);
    const fit = { b: b, k: k, ox: (w - b.w * k) / 2, oy: (h - b.h * k) / 2 };
    const T = f * SHIFT_S;
    ctx.lineWidth = 2; ctx.lineJoin = 'round';
    trail(ctx, ghost.pts, T, pal().ghost, fit);
    trail(ctx, you.pts, T, pal().acc, fit);
    pins(ctx, ghost.dots, T, pal().ghost, fit, ghost.times);
    pins(ctx, you.dots, T, pal().acc, fit, you.times);
  }

  function play(cv, you, ghost) {
    if (raf) cancelAnimationFrame(raf);
    const t0 = performance.now();
    (function step(now) {
      const f = Math.min(1, (now - t0) / REPLAY_MS);
      draw(cv, you, ghost, f);
      raf = f < 1 && cv.isConnected ? requestAnimationFrame(step) : 0;
    })(t0);
  }

  // ---- result screen ----
  function build() {
    const sh = rec.sh;
    const ghost = ghostPath(sh);
    ghost.times = (sh.ghostOrders || []).map(function (o) { return o.t; });
    const you = { pts: rec.pts, dots: rec.dots, times: rec.times };
    box = el('div', 'story');
    box.id = 'story';
    const cv = el('canvas', 'story-map');
    cv.setAttribute('aria-label', 'Твоя зміна й привид на карті');
    box.appendChild(cv);
    const bar = el('div', 'story-bar');
    const key = el('span', 'story-key');
    key.appendChild(el('i', 'you'));
    key.appendChild(document.createTextNode(' ти '));
    key.appendChild(el('i', 'ghost'));
    key.appendChild(document.createTextNode(' привид'));
    const again = el('button', 'story-replay', 'Повтор');
    again.type = 'button';
    again.addEventListener('click', function () { play(cv, you, ghost); });
    bar.appendChild(key);
    bar.appendChild(again);
    box.appendChild(bar);
    const list = facts && facts.shifts ? facts.shifts[sh.id] : null;
    if (list && list.length) {
      const ul = el('ul', 'story-facts');
      list.forEach(function (t) { ul.appendChild(el('li', '', t)); });
      box.appendChild(ul);
    }
    return { cv: cv, you: you, ghost: ghost };
  }

  function onScreen(p) {
    if (typeof document === 'undefined' || !p) return;
    if (p.name !== 'result') { if (raf) { cancelAnimationFrame(raf); raf = 0; } return; }
    const res = document.getElementById('result');
    const old = document.getElementById('story');
    if (old) old.remove();
    if (!res || !rec) return;
    const parts = build();
    res.insertBefore(box, res.querySelector('.res-race, .res-buttons'));
    play(parts.cv, parts.you, parts.ghost);
  }

  const bus = PG.bus;
  if (bus) {
    bus.on('shift:start', onStart);
    bus.on('frame', onFrame);
    bus.on('pickup', onPickup);
    bus.on('shift:end', onEnd);
    bus.on('ui:screen', onScreen);
  }
})(typeof window !== 'undefined' ? window : globalThis);
