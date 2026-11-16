/* 40_render.js: map canvas, camera, street glow, pins, cars (CONTRACT §8, §14). */
(function (root) {
  const PG = root.PG = root.PG || {};

  const MAP_W = 15000;
  const MAP_H = 19000;
  const HOME_X = 9110;
  const HOME_Y = 12443;
  const TAU = Math.PI * 2;

  // §14 colours
  const COL_BG = '#070b14';
  const COL_MAP = '#0a1019';
  const COL_MINT = '#3df5b0';
  const COL_GHOST = '#b48cff';
  const COL_MUTED = '#6b7488';
  const PIN_COL = ['#ffc857', '#5ee6ff', '#ff7a90'];
  const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

  const PIN_GLOW = ['rgba(255,200,87,0.20)', 'rgba(94,230,255,0.20)', 'rgba(255,122,144,0.20)'];
  const PIN_TRACK = ['rgba(255,200,87,0.25)', 'rgba(94,230,255,0.25)', 'rgba(255,122,144,0.25)'];
  const FONT_LABEL = '700 12px ' + FONT;
  const FONT_TAG = '600 10px ' + FONT;
  const FONT_FLOAT = '800 15px ' + FONT;
  const GHOST_TRAIL_N = 10;
  const GHOST_ALPHA = [];
  for (let i = 0; i < GHOST_TRAIL_N; i++) GHOST_ALPHA.push('rgba(180,140,255,' + (0.35 * i / GHOST_TRAIL_N).toFixed(3) + ')');
  const LABELS = [];
  const DASH = [7, 7];
  const NO_DASH = [];

  const MAX_LABELS = 96;
  const MAX_FAINT = 900;
  const FLOAT_LIFE = 70;          // game s a float stays visible
  const PAN_HOLD_S = 4;           // camera stays put this long after a manual pan
  const MIN_SCALE_PHONE_M = 6000; // metres across on a phone at start
  const DESKTOP_VIEW_H_M = 8000;  // metres of height on desktop at start
  const MAX_SCALE = 0.4;          // px per metre
  const GHOST_TRAIL_DT = 12;      // game s between ghost trail samples

  // ---- state ----
  let stage = null;
  let canvas = null;
  let ctx = null;
  let centerBtn = null;
  let W = 0;
  let H = 0;
  let dpr = 1;
  let fitted = false;
  let lastClock = 0;
  let lastPanClock = -1e9;
  let recenterUntil = 0;
  let centerShown = null;
  let frameNo = 0;

  const view = { cx: HOME_X, cy: HOME_Y, scale: 0.065 };
  const pOut = { x: 0, y: 0 };
  const wOut = { x: 0, y: 0 };
  const pins = [];
  const pinPool = [];
  const faint = new Float32Array(MAX_FAINT * 2);
  let faintN = 0;
  const labelRects = new Float32Array(MAX_LABELS * 4);
  let labelN = 0;
  const ghostOut = { x: 0, y: 0, hx: 1, hy: 0 };
  const ghostTrail = new Float32Array(GHOST_TRAIL_N * 2);
  let ghostTrailN = 0;
  let ghostTrailT = -1e9;
  const carAngle = { player: 0, ghost: 0 };
  const layers = [];
  const zone = { top: 0, bottom: 1e9, bx0: 0, by0: 0, bx1: 0, by1: 0 };  // keeps pins clear of UI

  function clock() {
    return (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000;
  }

  // ---- projection ----
  function P(x, y) {
    pOut.x = (x - view.cx) * view.scale + W * 0.5;
    pOut.y = (y - view.cy) * view.scale + H * 0.5;
    return pOut;
  }

  function screenToWorld(px, py) {
    wOut.x = (px - W * 0.5) / view.scale + view.cx;
    wOut.y = (py - H * 0.5) / view.scale + view.cy;
    return wOut;
  }

  function minScale() {
    return Math.min(W / MAP_W, H / MAP_H);
  }

  function clampView() {
    const lo = Math.max(minScale(), 0.0001);
    if (view.scale < lo) view.scale = lo;
    if (view.scale > MAX_SCALE) view.scale = MAX_SCALE;
    if (view.cx < 0) view.cx = 0;
    if (view.cx > MAP_W) view.cx = MAP_W;
    if (view.cy < 0) view.cy = 0;
    if (view.cy > MAP_H) view.cy = MAP_H;
  }

  function defaultScale() {
    if (W < 700) return W / MIN_SCALE_PHONE_M;
    return Math.min(H / DESKTOP_VIEW_H_M, W / 11000);
  }

  function resetCamera(x, y) {
    view.cx = x;
    view.cy = y;
    view.scale = defaultScale();
    clampView();
  }

  function panBy(dxPx, dyPx) {
    view.cx -= dxPx / view.scale;
    view.cy -= dyPx / view.scale;
    clampView();
    lastPanClock = clock();
  }

  function zoomAt(px, py, factor) {
    const bx = (px - W * 0.5) / view.scale + view.cx;
    const by = (py - H * 0.5) / view.scale + view.cy;
    view.scale *= factor;
    clampView();
    view.cx = bx - (px - W * 0.5) / view.scale;
    view.cy = by - (py - H * 0.5) / view.scale;
    clampView();
    lastPanClock = clock();
  }

  function recenter() {
    const G = PG.engine && PG.engine.G;
    lastPanClock = -1e9;
    recenterUntil = clock() + 0.8;
    if (G && PG.screen === 'play') {
      view.scale = Math.max(view.scale, defaultScale() * 0.9);
      if (view.scale > defaultScale() * 1.6) view.scale = defaultScale() * 1.6;
      clampView();
    }
  }

  function measureZones() {
    if (!stage) return;
    const sr = stage.getBoundingClientRect();
    const hud = document.getElementById('hud');
    const dsp = document.getElementById('dispatch');
    zone.top = 0;
    zone.bottom = H;
    if (hud) {
      const r = hud.getBoundingClientRect();
      if (r.height > 0) zone.top = Math.max(0, r.bottom - sr.top);
    }
    if (dsp) {
      const r = dsp.getBoundingClientRect();
      if (r.height > 0) zone.bottom = Math.min(H, r.top - sr.top);
    }
    if (centerBtn) {
      const r = centerBtn.getBoundingClientRect();
      zone.bx0 = r.left - sr.left - 12;
      zone.bx1 = r.right - sr.left + 12;
      zone.by0 = r.top - sr.top - 12;
      zone.by1 = r.bottom - sr.top + 12;
    }
  }

  function inZone(x, y) {
    if (y < zone.top || y > zone.bottom) return false;
    return !(x >= zone.bx0 && x <= zone.bx1 && y >= zone.by0 && y <= zone.by1);
  }

  // ---- size ----
  function resize() {
    if (!stage || !canvas) return;
    const w = stage.clientWidth;
    const h = stage.clientHeight;
    if (w <= 0 || h <= 0) return;
    dpr = Math.min(root.devicePixelRatio || 1, 2);
    W = w;
    H = h;
    const bw = Math.round(w * dpr);
    const bh = Math.round(h * dpr);
    if (canvas.width !== bw) canvas.width = bw;
    if (canvas.height !== bh) canvas.height = bh;
    measureZones();
    if (!fitted) {
      fitted = true;
      resetCamera(HOME_X, HOME_Y);
    } else {
      clampView();
    }
  }

  // ---- street glow ----
  const BUCKETS = [40, 20, 10];  // metres per texture pixel
  const STREET_RGB = '90,169,255';
  const STREET_CAP = 0.18;
  const caches = {};
  let streetImg = null;
  let alphaLut = null;

  function streetsReady() {
    return !!(streetImg && streetImg.complete && streetImg.naturalWidth > 0);
  }

  function pickBucket() {
    const mPerPx = 1 / view.scale;
    for (let i = 0; i < BUCKETS.length; i++) {
      if (BUCKETS[i] <= mPerPx * 1.1) return BUCKETS[i];
    }
    return BUCKETS[BUCKETS.length - 1];
  }

  function makeCache(mpp) {
    const cv = document.createElement('canvas');
    cv.width = Math.ceil(MAP_W / mpp);
    cv.height = Math.ceil(MAP_H / mpp);
    const c = cv.getContext('2d');
    c.globalCompositeOperation = 'lighter';
    c.lineJoin = 'round';
    c.lineWidth = Math.max(0.8, Math.min(2, 16 / mpp));
    c.strokeStyle = 'rgba(' + STREET_RGB + ',0.04)';
    return { mpp: mpp, cv: cv, c: c, si: 0, oi: 0, done: false };
  }

  function finishCache(k) {
    // cap the accumulated alpha with a soft knee so busy roads do not blow out
    if (!alphaLut) {
      alphaLut = new Uint8ClampedArray(256);
      for (let a = 0; a < 256; a++) {
        alphaLut[a] = Math.round(255 * STREET_CAP * (1 - Math.exp(-(a / 255) * 9)));
      }
    }
    const img = k.c.getImageData(0, 0, k.cv.width, k.cv.height);
    const d = img.data;
    for (let i = 3; i < d.length; i += 4) d[i] = alphaLut[d[i]];
    k.c.globalCompositeOperation = 'source-over';
    k.c.putImageData(img, 0, 0);
    k.done = true;
  }

  function buildSlice(k, budgetMs) {
    const shifts = PG.data && PG.data.shifts;
    if (!shifts) { k.done = true; return; }
    const c = k.c;
    const inv = 1 / k.mpp;
    const t0 = performance.now();
    let guard = 0;
    while (k.si < shifts.length) {
      const orders = shifts[k.si].orders;
      while (k.oi < orders.length) {
        const pts = orders[k.oi++].pts;
        const n = pts.n;
        if (n >= 2) {
          const xs = pts.xs;
          const ys = pts.ys;
          c.beginPath();
          c.moveTo(xs[0] * inv, ys[0] * inv);
          for (let j = 1; j < n; j++) c.lineTo(xs[j] * inv, ys[j] * inv);
          c.stroke();
        }
        if ((++guard & 63) === 0 && performance.now() - t0 > budgetMs) return;
      }
      k.si++;
      k.oi = 0;
    }
    finishCache(k);
  }

  function drawStreets() {
    if (streetsReady()) {
      ctx.globalCompositeOperation = 'lighter';
      ctx.imageSmoothingEnabled = true;
      P(0, 0);
      ctx.drawImage(streetImg, pOut.x, pOut.y, MAP_W * view.scale, MAP_H * view.scale);
      ctx.globalCompositeOperation = 'source-over';
      return;
    }
    if (!PG.data || !PG.data.shifts) return;
    const want = pickBucket();
    let k = caches[want];
    if (!k) k = caches[want] = makeCache(want);
    if (!k.done) buildSlice(k, 5);
    let use = k;
    if (!k.done) {
      // prefer the finest finished bucket while the wanted one is still building
      for (let i = BUCKETS.length - 1; i >= 0; i--) {
        const o = caches[BUCKETS[i]];
        if (o && o.done) { use = o; break; }
      }
    }
    P(0, 0);
    ctx.globalCompositeOperation = 'lighter';
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(use.cv, pOut.x, pOut.y, MAP_W * view.scale, MAP_H * view.scale);
    ctx.globalCompositeOperation = 'source-over';
  }

  // ---- layers from other modules ----
  function onDraw(fn, z) {
    const zz = typeof z === 'number' ? z : 0;
    const entry = { fn: fn, z: zz };
    let i = layers.length;
    layers.push(entry);
    while (i > 0 && layers[i - 1].z > zz) { layers[i] = layers[i - 1]; i--; }
    layers[i] = entry;
  }

  function runLayers(now, neg) {
    for (let i = 0; i < layers.length; i++) {
      const l = layers[i];
      if ((l.z < 0) !== neg) continue;
      ctx.save();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      l.fn(ctx, now);
      ctx.restore();
    }
  }

  // ---- camera update ----
  function updateCamera(dt, G, play) {
    const t = clock();
    if (play && G) {
      const held = t - lastPanClock < PAN_HOLD_S;
      const forced = t < recenterUntil;
      if ((G.mode !== 'idle' && !held) || forced) {
        const k = 1 - Math.exp(-dt * (forced ? 6 : 2.5));
        view.cx += (G.x - view.cx) * k;
        view.cy += (G.y - view.cy) * k;
      }
    } else {
      // menu / result: a slow drift around the city core
      const tx = HOME_X + Math.cos(t * 0.035) * 1800;
      const ty = HOME_Y - 900 + Math.sin(t * 0.025) * 1200;
      const k = 1 - Math.exp(-dt * 0.8);
      view.cx += (tx - view.cx) * k;
      view.cy += (ty - view.cy) * k;
    }
    clampView();
  }

  // ---- pins ----
  function pinAt(i) {
    let p = pinPool[i];
    if (!p) p = pinPool[i] = { o: null, px: 0, py: 0, r: 0, reach: false, fare: 0, key: 0 };
    return p;
  }

  function firstAfter(orders, t) {
    let lo = 0;
    let hi = orders.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (orders[mid].t > t) hi = mid; else lo = mid + 1;
    }
    return lo;
  }

  function collectPins(G) {
    const eng = PG.engine;
    const C = PG.C;
    const orders = G.sh.orders;
    const dk = (eng.DIFF_K && eng.config && eng.DIFF_K[eng.config.difficulty]) || 1;
    const maxLead = Math.max(C.LEAD[0], C.LEAD[1], C.LEAD[2]) * 1.25;
    const horizon = G.t + maxLead + 1800;
    let n = 0;
    faintN = 0;
    const margin = 24;
    for (let i = firstAfter(orders, G.t); i < orders.length; i++) {
      const o = orders[i];
      if (o.t > horizon) break;
      if (G.taken && G.taken.has(o.i)) continue;
      if (o === G.cur || o === G.next) continue;
      const cl = G.claim && G.claim.get(o.i);
      if (cl && cl.by !== 'player' && cl.t1 <= G.t) continue;
      const sx = (o.x0 - view.cx) * view.scale + W * 0.5;
      const sy = (o.y0 - view.cy) * view.scale + H * 0.5;
      if (sx < -margin || sy < -margin || sx > W + margin || sy > H + margin) continue;
      let isPin = false;
      if (o.t - eng.leadOf(o) <= G.t) {
        const dx = o.x0 - G.x;
        const dy = o.y0 - G.y;
        isPin = dx * dx + dy * dy <= (C.RADIUS[o.c] * dk) * (C.RADIUS[o.c] * dk);
      }
      if (isPin && !inZone(sx, sy)) isPin = false;
      if (isPin) {
        const p = pinAt(n++);
        const reach = eng.reachable(o);
        p.o = o;
        p.px = sx;
        p.py = sy;
        p.reach = reach;
        p.fare = o.fare;
        p.r = reach ? 9 + Math.min(3, o.fare / 8) : 3;
        pins[n - 1] = p;
      } else if (faintN < MAX_FAINT) {
        faint[faintN * 2] = sx;
        faint[faintN * 2 + 1] = sy;
        faintN++;
      }
    }
    pins.length = n;
    // reachable first, then nearest to the car (the quickest to take; labels are given out in this order)
    for (let i = 0; i < n; i++) {
      const q = pins[i];
      const dx = q.o.x0 - G.x;
      const dy = q.o.y0 - G.y;
      q.key = (q.reach ? 0 : 1e12) + dx * dx + dy * dy;
    }
    for (let i = 1; i < n; i++) {
      const p = pins[i];
      let j = i - 1;
      while (j >= 0 && pins[j].key > p.key) {
        pins[j + 1] = pins[j];
        j--;
      }
      pins[j + 1] = p;
    }
  }

  function nearestPin(px, py) {
    let best = null;
    let bd = Infinity;
    for (let i = 0; i < pins.length; i++) {
      const p = pins[i];
      const dx = px - p.px;
      const dy = py - p.py;
      const d = Math.sqrt(dx * dx + dy * dy);
      const lim = p.r + 10;
      if (d <= lim && d < bd) { bd = d; best = p; }
    }
    return best;
  }

  function addLabelRect(x, y, w, h) {
    if (labelN >= MAX_LABELS) return false;
    const i = labelN * 4;
    labelRects[i] = x;
    labelRects[i + 1] = y;
    labelRects[i + 2] = w;
    labelRects[i + 3] = h;
    labelN++;
    return true;
  }

  function labelFree(x, y, w, h) {
    for (let i = 0; i < labelN; i++) {
      const j = i * 4;
      if (x < labelRects[j] + labelRects[j + 2] && x + w > labelRects[j] &&
          y < labelRects[j + 1] + labelRects[j + 3] && y + h > labelRects[j + 1]) return false;
    }
    return true;
  }

  // ---- drawing helpers ----
  function strokePts(xs, ys, n) {
    if (n < 2) return;
    const s = view.scale;
    const ox = W * 0.5 - view.cx * s;
    const oy = H * 0.5 - view.cy * s;
    ctx.beginPath();
    ctx.moveTo(xs[0] * s + ox, ys[0] * s + oy);
    for (let i = 1; i < n; i++) ctx.lineTo(xs[i] * s + ox, ys[i] * s + oy);
    ctx.stroke();
  }

  function dashedLine(x0, y0, x1, y1) {
    P(x0, y0);
    const ax = pOut.x;
    const ay = pOut.y;
    P(x1, y1);
    ctx.beginPath();
    ctx.moveTo(ax, ay);
    ctx.lineTo(pOut.x, pOut.y);
    ctx.stroke();
  }

  function drawFlag(x, y) {
    P(x, y);
    const px = pOut.x;
    const py = pOut.y;
    ctx.strokeStyle = '#e8eefc';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(px, py);
    ctx.lineTo(px, py - 20);
    ctx.stroke();
    ctx.fillStyle = COL_MINT;
    ctx.beginPath();
    ctx.moveTo(px, py - 20);
    ctx.lineTo(px + 13, py - 15);
    ctx.lineTo(px, py - 10);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = '#e8eefc';
    ctx.beginPath();
    ctx.arc(px, py, 3, 0, TAU);
    ctx.fill();
  }

  function carBody(len, wid, color, alpha) {
    // car points to +x; centre at origin
    const hl = len * 0.5;
    const hw = wid * 0.5;
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(-hl + 3, -hw);
    ctx.lineTo(hl - 4, -hw);
    ctx.lineTo(hl, -hw + 3);
    ctx.lineTo(hl, hw - 3);
    ctx.lineTo(hl - 4, hw);
    ctx.lineTo(-hl + 3, hw);
    ctx.lineTo(-hl, hw - 2);
    ctx.lineTo(-hl, -hw + 2);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = 'rgba(7,11,20,0.75)';
    ctx.fillRect(hl * 0.05, -hw + 1.5, hl * 0.5, wid - 3);
    ctx.globalAlpha = 1;
  }

  function drawCar(px, py, hx, hy, len, wid, color, alpha, halo) {
    if (halo > 0) {
      ctx.globalAlpha = 0.16 * alpha;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(px, py, halo, 0, TAU);
      ctx.fill();
      ctx.globalAlpha = 1;
    }
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(Math.atan2(hy, hx));
    carBody(len, wid, color, alpha);
    ctx.restore();
  }

  function drawFaint(G) {
    ctx.fillStyle = 'rgba(138,150,179,0.22)';
    for (let i = 0; i < faintN; i++) {
      ctx.fillRect(faint[i * 2] - 1, faint[i * 2 + 1] - 1, 2, 2);
    }
  }

  function drawPinDots(G, tReal) {
    const eng = PG.engine;
    for (let i = pins.length - 1; i >= 0; i--) {
      const p = pins[i];
      const o = p.o;
      if (!p.reach) {
        ctx.fillStyle = COL_MUTED;
        ctx.globalAlpha = 0.85;
        ctx.beginPath();
        ctx.arc(p.px, p.py, 3, 0, TAU);
        ctx.fill();
        ctx.globalAlpha = 1;
        continue;
      }
      const c = o.c;
      const lead = eng.leadOf(o);
      let frac = (o.t - G.t) / lead;
      if (frac < 0) frac = 0;
      if (frac > 1) frac = 1;
      const pulse = frac < 0.25 ? 0.6 + 0.4 * Math.sin(tReal * 10) : 1;
      ctx.fillStyle = PIN_GLOW[c];
      ctx.beginPath();
      ctx.arc(p.px, p.py, p.r + 5, 0, TAU);
      ctx.fill();
      ctx.fillStyle = PIN_COL[c];
      ctx.beginPath();
      ctx.arc(p.px, p.py, p.r, 0, TAU);
      ctx.fill();
      ctx.strokeStyle = 'rgba(7,11,20,0.55)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(p.px, p.py, p.r - 3, 0, TAU);
      ctx.stroke();
      ctx.strokeStyle = PIN_TRACK[c];
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.arc(p.px, p.py, p.r + 4.5, 0, TAU);
      ctx.stroke();
      if (frac > 0.002) {
        ctx.globalAlpha = pulse;
        ctx.strokeStyle = PIN_COL[c];
        ctx.beginPath();
        ctx.arc(p.px, p.py, p.r + 4.5, -Math.PI / 2, -Math.PI / 2 + TAU * frac);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    }
  }

  function drawPinLabels(carPx, carPy) {
    ctx.font = FONT_LABEL;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (let i = 0; i < pins.length; i++) {
      const p = pins[i];
      if (!p.reach) continue;
      const fr = Math.round(p.o.fare);
      const txt = LABELS[fr] || (LABELS[fr] = '€' + fr);
      const w = txt.length * 7.4 + 10;
      const h = 16;
      const x = p.px - w * 0.5;
      const y = p.py - p.r - 7 - h;
      if (x < 2 || x + w > W - 2 || y < 2) continue;
      if (!labelFree(x, y, w, h)) continue;
      if (!addLabelRect(x, y, w, h)) break;
      ctx.fillStyle = 'rgba(7,11,20,0.82)';
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = PIN_COL[p.o.c];
      ctx.fillText(txt, p.px, y + h * 0.5 + 0.5);
    }
  }

  function drawRoutes(G) {
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    if (G.mode === 'pickup' && G.leg) {
      ctx.setLineDash(DASH);
      ctx.strokeStyle = 'rgba(61,245,176,0.75)';
      ctx.lineWidth = 2.5;
      if (G.leg.path && G.leg.path.n > 1) strokePts(G.leg.path.xs, G.leg.path.ys, G.leg.path.n);
      else dashedLine(G.x, G.y, G.leg.x1, G.leg.y1);
      ctx.setLineDash(NO_DASH);
      if (G.cur) {
        P(G.cur.x0, G.cur.y0);
        ctx.strokeStyle = COL_MINT;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(pOut.x, pOut.y, 13, 0, TAU);
        ctx.stroke();
      }
    } else if (G.mode === 'ride' && G.cur && G.cur.pts) {
      const pts = G.cur.pts;
      ctx.strokeStyle = 'rgba(61,245,176,0.30)';
      ctx.lineWidth = 6;
      strokePts(pts.xs, pts.ys, pts.n);
      ctx.strokeStyle = 'rgba(61,245,176,0.9)';
      ctx.lineWidth = 2.5;
      strokePts(pts.xs, pts.ys, pts.n);
      drawFlag(G.cur.x1, G.cur.y1);
    } else if (G.mode === 'cruise' && G.leg) {
      ctx.setLineDash(DASH);
      ctx.strokeStyle = 'rgba(138,150,179,0.55)';
      ctx.lineWidth = 2;
      if (G.leg.path && G.leg.path.n > 1) strokePts(G.leg.path.xs, G.leg.path.ys, G.leg.path.n);
      else dashedLine(G.x, G.y, G.leg.x1, G.leg.y1);
      ctx.setLineDash(NO_DASH);
    }
    if (G.next && G.cur) {
      ctx.setLineDash(DASH);
      ctx.strokeStyle = 'rgba(255,200,87,0.7)';
      ctx.lineWidth = 2;
      dashedLine(G.cur.x1, G.cur.y1, G.next.x0, G.next.y0);
      ctx.setLineDash(NO_DASH);
      P(G.next.x0, G.next.y0);
      ctx.strokeStyle = '#ffc857';
      ctx.beginPath();
      ctx.arc(pOut.x, pOut.y, 13, 0, TAU);
      ctx.stroke();
    }
  }

  function drawTrail(G) {
    const tr = G.trail;
    if (!tr || tr.length < 4) return;
    const s = view.scale;
    const ox = W * 0.5 - view.cx * s;
    const oy = H * 0.5 - view.cy * s;
    const maxJump = 800;
    ctx.strokeStyle = 'rgba(61,245,176,0.28)';
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    ctx.beginPath();
    let px = tr[0];
    let py = tr[1];
    ctx.moveTo(px * s + ox, py * s + oy);
    for (let i = 2; i + 1 < tr.length; i += 2) {
      const x = tr[i];
      const y = tr[i + 1];
      const jump = Math.abs(x - px) + Math.abs(y - py) > maxJump;
      if (jump) ctx.moveTo(x * s + ox, y * s + oy);
      else ctx.lineTo(x * s + ox, y * s + oy);
      px = x;
      py = y;
    }
    ctx.lineTo(G.x * s + ox, G.y * s + oy);
    ctx.stroke();
  }

  function updateGhostTrail(G) {
    if (G.t < ghostTrailT) { ghostTrailN = 0; ghostTrailT = -1e9; }
    if (G.t - ghostTrailT >= GHOST_TRAIL_DT) {
      if (ghostTrailN < GHOST_TRAIL_N) {
        ghostTrail[ghostTrailN * 2] = ghostOut.x;
        ghostTrail[ghostTrailN * 2 + 1] = ghostOut.y;
        ghostTrailN++;
      } else {
        ghostTrail.copyWithin(0, 2);
        ghostTrail[(GHOST_TRAIL_N - 1) * 2] = ghostOut.x;
        ghostTrail[(GHOST_TRAIL_N - 1) * 2 + 1] = ghostOut.y;
      }
      ghostTrailT = G.t;
    }
  }

  function drawGhost(G) {
    if (!PG.data || !PG.data.ghostAt) return;
    PG.data.ghostAt(G.sh, G.t, ghostOut);
    updateGhostTrail(G);
    const s = view.scale;
    const ox = W * 0.5 - view.cx * s;
    const oy = H * 0.5 - view.cy * s;
    if (ghostTrailN > 1) {
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      for (let i = 1; i < ghostTrailN; i++) {
        ctx.strokeStyle = GHOST_ALPHA[i];
        ctx.beginPath();
        ctx.moveTo(ghostTrail[i * 2 - 2] * s + ox, ghostTrail[i * 2 - 1] * s + oy);
        ctx.lineTo(ghostTrail[i * 2] * s + ox, ghostTrail[i * 2 + 1] * s + oy);
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.moveTo(ghostTrail[(ghostTrailN - 1) * 2] * s + ox, ghostTrail[(ghostTrailN - 1) * 2 + 1] * s + oy);
      ctx.lineTo(ghostOut.x * s + ox, ghostOut.y * s + oy);
      ctx.stroke();
    }
    let hx = ghostOut.hx;
    let hy = ghostOut.hy;
    if (!hx && !hy) { hx = Math.cos(carAngle.ghost); hy = Math.sin(carAngle.ghost); }
    else carAngle.ghost = Math.atan2(hy, hx);
    const px = ghostOut.x * s + ox;
    const py = ghostOut.y * s + oy;
    if (px < -30 || py < -30 || px > W + 30 || py > H + 30) return;
    drawCar(px, py, hx, hy, 19, 10, COL_GHOST, 0.5, 18);
  }

  function drawRivals(G) {
    const rv = G.rivals;
    if (!rv || !rv.length) return;
    ctx.font = FONT_TAG;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    for (let i = 0; i < rv.length; i++) {
      const r = rv[i];
      P(r.x, r.y);
      const px = pOut.x;
      const py = pOut.y;
      if (px < -30 || py < -30 || px > W + 30 || py > H + 30) continue;
      let hx = r.hx;
      let hy = r.hy;
      if (!hx && !hy) { hx = 1; hy = 0; }
      drawCar(px, py, hx, hy, 15, 8, r.color || '#ffffff', 1, 11);
      const name = r.name || r.id || '';
      const w = name.length * 5.6 + 6;
      const x = px - w * 0.5;
      const y = py - 22;
      if (labelFree(x, y, w, 12) && addLabelRect(x, y, w, 12)) {
        ctx.fillStyle = 'rgba(7,11,20,0.7)';
        ctx.fillRect(x, y, w, 12);
        ctx.fillStyle = r.color || '#ffffff';
        ctx.fillText(name, px, y + 9.5);
      }
    }
  }

  function drawPlayer(G) {
    P(G.x, G.y);
    const px = pOut.x;
    const py = pOut.y;
    let hx = G.hx;
    let hy = G.hy;
    if (!hx && !hy) { hx = Math.cos(carAngle.player); hy = Math.sin(carAngle.player); }
    else carAngle.player = Math.atan2(hy, hx);
    drawCar(px, py, hx, hy, 22, 12, COL_MINT, 1, 20);
    ctx.strokeStyle = 'rgba(61,245,176,0.55)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(px, py, 16, 0, TAU);
    ctx.stroke();
  }

  function drawFloats(G) {
    const fl = G.floats;
    if (!fl || !fl.length) return;
    ctx.font = FONT_FLOAT;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (let i = 0; i < fl.length; i++) {
      const f = fl[i];
      const age = G.t - f.born;
      if (age < 0 || age > FLOAT_LIFE) continue;
      const k = age / FLOAT_LIFE;
      P(f.x, f.y);
      const y = pOut.y - 18 - k * 34;
      ctx.globalAlpha = 1 - k * k;
      ctx.lineWidth = 3;
      ctx.strokeStyle = 'rgba(7,11,20,0.85)';
      ctx.strokeText(f.text, pOut.x, y);
      ctx.fillStyle = f.color || COL_MINT;
      ctx.fillText(f.text, pOut.x, y);
    }
    ctx.globalAlpha = 1;
  }

  function updateCenterBtn(show) {
    if (!centerBtn || centerShown === show) return;
    centerShown = show;
    centerBtn.hidden = !show;
    measureZones();
  }

  // ---- main draw ----
  function draw(now) {
    if (!ctx) return;
    if (!W || !H) resize();
    if (!W || !H) return;
    const t = clock();
    let dt = t - lastClock;
    lastClock = t;
    if (dt > 0.1 || dt < 0) dt = 0.1;

    const G = PG.engine && PG.engine.G;
    const play = PG.screen === 'play' && !!G && !!G.sh;
    updateCamera(dt, G, play);
    updateCenterBtn(play);
    if ((++frameNo & 63) === 0) measureZones();

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = COL_BG;
    ctx.fillRect(0, 0, W, H);
    // map plate
    P(0, 0);
    const mx = pOut.x;
    const my = pOut.y;
    ctx.fillStyle = COL_MAP;
    ctx.fillRect(mx, my, MAP_W * view.scale, MAP_H * view.scale);
    ctx.strokeStyle = 'rgba(138,150,179,0.14)';
    ctx.lineWidth = 1;
    ctx.strokeRect(mx, my, MAP_W * view.scale, MAP_H * view.scale);

    drawStreets();
    runLayers(now, true);

    if (!G || !G.sh) {
      pins.length = 0;
      runLayers(now, false);
      return;
    }

    labelN = 0;
    collectPins(G);
    drawFaint(G);
    drawRoutes(G);
    drawPinDots(G, t);
    drawTrail(G);
    drawGhost(G);
    P(G.x, G.y);
    addLabelRect(pOut.x - 30, pOut.y - 30, 60, 60);   // keep labels off the player's car
    drawPinLabels(pOut.x, pOut.y);
    drawRivals(G);
    drawPlayer(G);
    drawFloats(G);
    runLayers(now, false);
  }

  // ---- init ----
  function init() {
    stage = document.getElementById('stage');
    if (!stage) return;
    canvas = document.createElement('canvas');
    canvas.id = 'map';
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', 'Мапа Порту');
    stage.insertBefore(canvas, stage.firstChild);
    ctx = canvas.getContext('2d');
    streetImg = document.getElementById('streets-png');

    centerBtn = document.createElement('button');
    centerBtn.id = 'map-center';
    centerBtn.type = 'button';
    centerBtn.textContent = '⌖ центр';
    centerBtn.setAttribute('aria-label', 'Центрувати на авто');
    centerBtn.hidden = true;
    centerBtn.addEventListener('click', recenter);
    stage.appendChild(centerBtn);

    resize();
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(resize).observe(stage);
    root.addEventListener('resize', resize);

    if (PG.bus) {
      PG.bus.on('shift:start', function () {
        const G = PG.engine && PG.engine.G;
        measureZones();
        ghostTrailN = 0;
        ghostTrailT = -1e9;
        lastPanClock = -1e9;
        recenterUntil = 0;
        resetCamera(G ? G.x : HOME_X, G ? G.y : HOME_Y);
      });
    }
  }

  PG.render = {
    init: init,
    draw: draw,
    P: P,
    screenToWorld: screenToWorld,
    pins: pins,
    view: view,
    onDraw: onDraw,
    drawsRivals: true,
    // helpers used by 70_input.js
    nearestPin: nearestPin,
    panBy: panBy,
    zoomAt: zoomAt,
    recenter: recenter,
  };
})(typeof window !== 'undefined' ? window : globalThis);
