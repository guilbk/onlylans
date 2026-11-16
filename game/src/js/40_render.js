/* 40_render.js: map canvas, camera, street glow, pins, cars (CONTRACT §8, §14). */
(function (root) {
  const PG = root.PG = root.PG || {};

  const MAP_W = 15000;
  const MAP_H = 19000;
  const HOME_X = 9110;
  const HOME_Y = 12443;
  const TAU = Math.PI * 2;

  // colours come from the theme palette (PG.C.THEMES, picked by 50_hud.js)
  function T() { return (PG.theme && PG.theme.pal) || PG.C.THEMES.night; }
  const FONT = '"Trebuchet MS", "Helvetica Neue", system-ui, sans-serif';

  const FONT_LABEL = '800 14px ' + FONT;
  const FONT_TAG = '700 12px ' + FONT;
  const GHOST_TRAIL_N = 10;
  const LABELS = [];
  const DASH = [7, 7];
  const NO_DASH = [];

  const MAX_LABELS = 96;
  const MAX_FAINT = 900;
  const EDGE_MAX = 6;             // off-screen takeable pins shown as edge arrows while riding
  const edge = [];
  const POP_S = 0.4;              // real s of the pin pop-in
  const EXPIRE_S = 0.35;          // real s of the pin expiry fade
  const EXPIRE_N = 16;
  const LABEL_S = 1.4;            // real s a «Забрав …» / «Минув час» label stays
  const PAN_HOLD_S = 4;           // camera stays put this long after a manual pan
  const VIEW_PHONE_M = 2800;      // metres across on a phone at start
  const VIEW_WIDE_M = 5000;       // metres across on a wide screen at start
  const VIEW_MIN_M = 1000;        // closest zoom: this many metres across
  const ZOOM_STEP = 1.45;         // one press of + or -
  const PEEK_S = 2.5;             // a tapped or hovered rival shows its name this long
  const NEAR_M = 1500;            // rivals this close to the hero (metres) always show a name
  const GHOST_TRAIL_DT = 12;      // game s between ghost trail samples
  const CAR_PX = 40;              // the hero is this long (px) at the default zoom; cars scale with the zoom, in proportion to the streets
  const CAR_K = { hero: 1, ghost: 0.92, rival: 0.85 };
  const TAG_H = 16;

  // ---- state ----
  let stage = null;
  let canvas = null;
  let ctx = null;
  let centerBtn = null;
  let zoomBox = null;
  let peekX = -1e9;
  let peekY = -1e9;
  let peekAt = -1e9;
  let W = 0;
  let H = 0;
  let dpr = 1;
  let fitted = false;
  let lastClock = 0;
  let lastPanClock = -1e9;
  let recenterUntil = 0;
  let centerShown = null;
  let frameNo = 0;
  let dtNow = 0.016;

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
  const born = new Map();         // order -> real s it first showed as a pin
  let prevPins = new Set();
  let curPins = new Set();
  let prevBright = new Set();     // pins that were takeable one frame ago (they get a label when they go)
  let curBright = new Set();
  const expired = [];             // fading pins: {x, y, c, r, t0} in world metres
  let punch = 0;                  // short zoom kick on pickup / drop-off
  let zoomEaseTo = 0;
  let zoomEaseUntil = 0;
  const rx = new Float32Array(16);
  const ry = new Float32Array(16);
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
    const hi = Math.max(lo, W / VIEW_MIN_M);
    if (view.scale > hi) view.scale = hi;
    if (view.cx < 0) view.cx = 0;
    if (view.cx > MAP_W) view.cx = MAP_W;
    if (view.cy < 0) view.cy = 0;
    if (view.cy > MAP_H) view.cy = MAP_H;
  }

  function defaultScale() {
    return W / (W < 700 ? VIEW_PHONE_M : VIEW_WIDE_M);
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
    const G = PG.engine && PG.engine.G;
    // while the camera follows the car, zoom around the car and keep following; a pan lets go
    const follow = !!G && PG.screen === 'play' && clock() - lastPanClock >= PAN_HOLD_S;
    if (follow) { const c = P(G.x, G.y); px = c.x; py = c.y; }
    const bx = (px - W * 0.5) / view.scale + view.cx;
    const by = (py - H * 0.5) / view.scale + view.cy;
    view.scale *= factor;
    zoomEaseUntil = 0;
    clampView();
    view.cx = bx - (px - W * 0.5) / view.scale;
    view.cy = by - (py - H * 0.5) / view.scale;
    clampView();
    if (!follow) lastPanClock = clock();
  }

  function kick(v) {
    if (!PG.REDUCED && punch < 0.09) punch += v;
  }

  // Car length in screen px: CAR_PX at the default zoom, scaling with the zoom, clamped so it stays readable
  // when zoomed out and does not swallow the street when zoomed in.
  function carLen(kind) {
    const px = Math.min(56, Math.max(24, CAR_PX * view.scale / defaultScale()));
    return px * (CAR_K[kind] || 1);
  }

  // + / - buttons: ease to a nearby zoom level around the middle of the screen
  function zoomStep(f) {
    const base = clock() < zoomEaseUntil ? zoomEaseTo : view.scale;   // quick presses add up
    zoomEaseTo = Math.min(Math.max(base * f, minScale()), Math.max(minScale(), W / VIEW_MIN_M));
    zoomEaseUntil = clock() + 0.9;
  }

  // a tap or hover at (px, py) lets the rival under it show its name for a moment
  function peek(px, py) {
    peekX = px;
    peekY = py;
    peekAt = clock();
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
      const q = zoomBox && !zoomBox.hidden ? zoomBox.getBoundingClientRect() : r;
      zone.bx0 = Math.min(r.left, q.left) - sr.left - 12;
      zone.bx1 = Math.max(r.right, q.right) - sr.left + 12;
      zone.by0 = Math.min(r.top, q.top) - sr.top - 12;
      zone.by1 = Math.max(r.bottom, q.bottom) - sr.top + 12;
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
  const STREET_CAP = 0.1;
  let dimCv = null;
  let tile = null;
  let tileName = '';
  const TILE_PX = 512;
  const TILE_M = 800;           // metres of map in one ground tile
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
    c.globalCompositeOperation = T().additive ? 'lighter' : 'source-over';
    c.lineJoin = 'round';
    c.lineWidth = Math.max(0.8, Math.min(2, 16 / mpp));
    c.strokeStyle = 'rgba(' + T().street + ',0.04)';
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

  // One pass over the street picture: minor streets nearly vanish, busy roads keep a clear line.
  function dimStreets(pal) {
    const cv = document.createElement('canvas');
    cv.width = streetImg.naturalWidth;
    cv.height = streetImg.naturalHeight;
    const c = cv.getContext('2d');
    c.drawImage(streetImg, 0, 0);
    try {
      const img = c.getImageData(0, 0, cv.width, cv.height);
      const d = img.data;
      let lo = 255;
      let hi = 0;
      for (let i = 3; i < d.length; i += 4) {
        const a = d[i];
        if (a === 0) continue;
        if (a < lo) lo = a;
        if (a > hi) hi = a;
      }
      const span = Math.max(1, hi - lo);
      for (let i = 3; i < d.length; i += 4) {
        const a = d[i];
        if (a === 0) continue;
        const t = (a - lo) / span;
        d[i] = Math.round(255 * (pal.streetMinor + (pal.streetMain - pal.streetMinor) * t * t * t));
      }
      c.putImageData(img, 0, 0);
      c.globalCompositeOperation = 'source-in';       // keep the alpha, paint it in the theme's street colour
      c.fillStyle = 'rgb(' + pal.street + ')';
      c.fillRect(0, 0, cv.width, cv.height);
      c.globalCompositeOperation = 'source-over';
      if (pal.widen) {                                  // light streets need body: grow every line by a pixel
        c.drawImage(cv, 1, 0);
        c.drawImage(cv, 0, 1);
      }
    } catch (e) {
      return null;      // tainted canvas: the plain picture is drawn at a lower alpha
    }
    return cv;
  }

  // Flat ground: a seeded tile of a few irregular, low-contrast blocks (a rare park), repeated over the map.
  // The streets and the route stay the loudest thing on the map.
  function makeTile(pal) {
    const cv = document.createElement('canvas');
    cv.width = cv.height = TILE_PX;
    const c = cv.getContext('2d');
    c.fillStyle = pal.ground;
    c.fillRect(0, 0, TILE_PX, TILE_PX);
    let seed = 11;
    const rnd = function () { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    for (let i = 0; i < 14; i++) {
      const w = 40 + rnd() * 110, h = 30 + rnd() * 90;
      const x = rnd() * (TILE_PX - w), y = rnd() * (TILE_PX - h);
      const park = rnd() < 0.12;
      c.globalAlpha = park ? 0.5 : 0.55 + rnd() * 0.35;
      c.fillStyle = park ? pal.park : pal.blocks[(rnd() * 4) | 0];
      c.fillRect(x, y, w, h);
      if (!park && rnd() < 0.25) {              // a faint roof inside a few blocks
        c.globalAlpha = 0.14;
        c.fillStyle = pal.roofs[(rnd() * 4) | 0];
        c.fillRect(x + w * 0.2, y + h * 0.2, w * 0.6, h * 0.6);
      }
    }
    c.globalAlpha = 1;
    return cv;
  }

  function drawGround(pal, mx, my) {
    const pw = MAP_W * view.scale;
    const ph = MAP_H * view.scale;
    if (tileName !== pal.name) { tile = makeTile(pal); tileName = pal.name; }
    const pat = ctx.createPattern(tile, 'repeat');
    const s = view.scale * TILE_M / TILE_PX;
    if (pat && pat.setTransform && typeof DOMMatrix === 'function') pat.setTransform(new DOMMatrix([s, 0, 0, s, mx, my]));
    ctx.fillStyle = pat || pal.ground;
    ctx.fillRect(mx, my, pw, ph);
  }

  function drawStreets() {
    const pal = T();
    if (streetsReady()) {
      if (dimCv === null) dimCv = dimStreets(pal) || false;
      ctx.globalCompositeOperation = pal.additive ? 'lighter' : 'source-over';
      ctx.imageSmoothingEnabled = true;
      ctx.globalAlpha = dimCv ? 1 : 0.4;
      P(0, 0);
      ctx.drawImage(dimCv || streetImg, pOut.x, pOut.y, MAP_W * view.scale, MAP_H * view.scale);
      ctx.globalAlpha = 1;
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
    ctx.globalCompositeOperation = pal.additive ? 'lighter' : 'source-over';
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
    const frozen = !!(PG.orders && (PG.orders.selected || PG.orders.hovered));   // a pin under the finger or mouse must not slide away
    if (frozen) {
      zoomEaseUntil += dt;           // the zoom ease waits
    } else if (t < zoomEaseUntil) view.scale += (zoomEaseTo - view.scale) * (1 - Math.exp(-dt * 5));
    if (punch !== 0) {                     // kick decays back; applied as a ratio so user zoom is kept
      const next = Math.abs(punch) < 0.002 ? 0 : punch * Math.exp(-dt * 6);
      view.scale *= (1 + next) / (1 + punch);
      punch = next;
    }
    if (frozen && play) {
      // camera stays put while a pin is selected
    } else if (play && G) {
      const held = t - lastPanClock < PAN_HOLD_S;
      const forced = t < recenterUntil;
      if (!held || forced) {
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

  function popK(age) {                 // ease-out-back: grows past 1 and settles
    if (PG.REDUCED || age >= POP_S) return 1;
    const x = age / POP_S - 1;
    return Math.max(0.01, 1 + 2.7 * x * x * x + 1.7 * x * x);
  }

  // pins that vanished because their time ran out fade out instead of blinking off
  function noteExpired(G, tNow) {
    if (!PG.REDUCED) {
      prevPins.forEach(function (o) {
        if (curPins.has(o) || G.cur === o || G.next === o) return;
        if (G.taken && G.taken.has(o.i)) return;
        // never a silent pop: say why a bright pin went (a rival took it, or its time ran out)
        const cl = G.claim && G.claim.get(o.i);
        let label = '', rival = false;
        if (cl && cl.by !== 'player' && cl.t1 <= G.t) {
          let nick = '';
          for (let i = 0; i < G.rivals.length; i++) if (G.rivals[i].id === cl.by) nick = G.rivals[i].nick || G.rivals[i].name;
          rival = true;
          label = 'Забрав ' + (nick || 'суперник');
        } else if (o.t <= G.t + 30) label = 'Минув час';
        else return;                  // only scrolled or driven out of range: not gone
        if (expired.length >= EXPIRE_N) expired.shift();
        expired.push({ x: o.x0, y: o.y0, c: o.c, t0: tNow, label: rival || prevBright.has(o) ? label : '' });
      });
    }
    let t = prevPins;
    prevPins = curPins;
    curPins = t;
    t = prevBright;
    prevBright = curBright;
    curBright = t;
  }

  // Pins that would sit on top of each other fan out in a small circle around their middle (screen only,
  // the orders keep their real spot; a thin leader line joins each pin to it). Hit areas stay separate.
  function spread(n) {
    const ringOf = function (q) { return q.reach ? 22 : 6; };
    for (let i = 0; i < n; i++) pins[i].cl = -1;
    for (let i = 0; i < n; i++) {
      const a = pins[i];
      if (a.cl >= 0 || !a.reach) continue;      // grey dots stay where they are
      const grp = [a];
      a.cl = i;
      for (let g = 0; g < grp.length; g++) {            // everything that touches anything in the group
        for (let j = 0; j < n; j++) {
          const b = pins[j];
          if (b.cl >= 0 || !b.reach) continue;
          const s = ringOf(grp[g]) + ringOf(b) - 6;
          if (Math.hypot(grp[g].rx - b.rx, grp[g].ry - b.ry) < s) { b.cl = i; grp.push(b); }
        }
      }
      if (grp.length < 2) continue;
      grp.sort(function (u, v) { return u.o.i - v.o.i; });
      let cx = 0, cy = 0;
      for (let k = 0; k < grp.length; k++) { cx += grp[k].rx; cy += grp[k].ry; }
      cx /= grp.length; cy /= grp.length;
      const rad = Math.max(26, 15 * grp.length);
      for (let k = 0; k < grp.length; k++) {
        const ang = -1.5708 + TAU * k / grp.length;
        grp[k].px = cx + Math.cos(ang) * rad;
        grp[k].py = cy + Math.sin(ang) * rad;
      }
    }
  }

  function collectPins(G, tNow) {
    const eng = PG.engine;
    const C = PG.C;
    const orders = G.sh.orders;
    const dk = (eng.DIFF_K && eng.config && eng.DIFF_K[eng.config.difficulty]) || 1;
    const maxLead = Math.max(C.LEAD[0], C.LEAD[1], C.LEAD[2]) * 1.25;
    const horizon = G.t + maxLead + 1800;
    let n = 0;
    faintN = 0;
    edge.length = 0;
    curPins.clear();
    curBright.clear();
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
      if (sx < -margin || sy < -margin || sx > W + margin || sy > H + margin) {
        // while riding, takeable pins are counted from the drop-off and often lie off screen: point to them
        if (G.mode === 'ride' && edge.length < EDGE_MAX && o.t - eng.leadOf(o) <= G.t &&
            Math.hypot(o.x0 - G.x, o.y0 - G.y) <= C.RADIUS[o.c] * dk && eng.reachable(o)) edge.push(o, sx, sy);
        continue;
      }
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
        p.px = p.rx = sx;
        p.py = p.ry = sy;
        p.reach = reach;
        p.fare = o.fare;
        p.r = reach ? 15 : 5;
        p.lw = 0;
        let b = born.get(o);
        if (b === undefined) { b = tNow; born.set(o, b); }
        p.k = popK(tNow - b);
        pins[n - 1] = p;
        curPins.add(o);
        if (reach) curBright.add(o);
      } else if (faintN < MAX_FAINT) {
        faint[faintN * 2] = sx;
        faint[faintN * 2 + 1] = sy;
        faintN++;
      }
    }
    pins.length = n;
    spread(n);
    noteExpired(G, tNow);
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

  // Forgiving pick: nearest pin within rad px (reachable ones win ties), or its price label.
  function nearestPin(px, py, rad) {
    const R = rad || 18;
    let best = null;
    let bs = Infinity;
    for (let i = 0; i < pins.length; i++) {
      const p = pins[i];
      const dx = px - p.px;
      const dy = py - p.py;
      let d = Math.sqrt(dx * dx + dy * dy);
      const lim = p.reach ? Math.max(R, p.r + 8) : Math.min(R, p.r + 10);
      if (p.lw > 0 && px >= p.lx && px <= p.lx + p.lw && py >= p.ly && py <= p.ly + 16) d = Math.min(d, lim * 0.9);
      if (d > lim) continue;
      const sc = d - (p.reach ? 6 : 0);
      if (sc < bs) { bs = sc; best = p; }
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
    ctx.strokeStyle = T().flag;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(px, py);
    ctx.lineTo(px, py - 20);
    ctx.stroke();
    ctx.fillStyle = T().acc;
    ctx.beginPath();
    ctx.moveTo(px, py - 20);
    ctx.lineTo(px + 13, py - 15);
    ctx.lineTo(px, py - 10);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = T().flag;
    ctx.beginPath();
    ctx.arc(px, py, 3, 0, TAU);
    ctx.fill();
  }

  function drawFaint(G) {
    ctx.fillStyle = T().faint;
    for (let i = 0; i < faintN; i++) {
      ctx.fillRect(faint[i * 2] - 1, faint[i * 2 + 1] - 1, 2, 2);
    }
  }

  function ring(x, y, r, w, col, a) {
    ctx.globalAlpha = a;
    ctx.strokeStyle = col;
    ctx.lineWidth = w;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, TAU);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  function drawPinDots(G, tReal) {
    const eng = PG.engine;
    const pal = T();
    ctx.lineWidth = 1;
    ctx.strokeStyle = pal.ink;
    ctx.globalAlpha = 0.5;
    for (let i = pins.length - 1; i >= 0; i--) {       // leader lines of fanned-out pins
      const q = pins[i];
      if (q.px === q.rx && q.py === q.ry) continue;
      ctx.beginPath(); ctx.moveTo(q.rx, q.ry); ctx.lineTo(q.px, q.py); ctx.stroke();
      ctx.beginPath(); ctx.arc(q.rx, q.ry, 2, 0, TAU); ctx.fillStyle = pal.ink; ctx.fill();
    }
    ctx.globalAlpha = 1;
    for (let i = pins.length - 1; i >= 0; i--) {
      const p = pins[i];
      const o = p.o;
      const k = p.k;
      if (!p.reach) {                                   // out of reach: a small grey dot
        ctx.fillStyle = pal.dot;
        ctx.globalAlpha = 0.7 * Math.min(1, k);
        ctx.beginPath();
        ctx.arc(p.px, p.py, p.r, 0, TAU);
        ctx.fill();
        ctx.globalAlpha = 1;
        continue;
      }
      const c = o.c;
      const lead = eng.leadOf(o);
      let frac = (o.t - G.t) / lead;
      if (frac < 0) frac = 0;
      if (frac > 1) frac = 1;
      const low = frac < 0.25;
      const pulse = low ? 0.6 + 0.4 * Math.sin(tReal * 10) : 1;
      if (k !== 1) { ctx.save(); ctx.translate(p.px, p.py); ctx.scale(k, k); ctx.translate(-p.px, -p.py); }
      ctx.fillStyle = pal.pins[c];                      // the coin, then its timer ring (about 44 px across)
      ctx.beginPath();
      ctx.arc(p.px, p.py, p.r, 0, TAU);
      ctx.fill();
      ctx.lineCap = 'round';
      ring(p.px, p.py, p.r + 5.5, 3.5, pal.blue, 0.25);
      if (frac > 0.002) {
        ctx.lineWidth = low ? 4.5 : 3.5;
        ctx.strokeStyle = pal.blue;
        ctx.globalAlpha = pulse;
        ctx.beginPath();
        ctx.arc(p.px, p.py, p.r + 5.5, -Math.PI / 2, -Math.PI / 2 + TAU * frac);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      if (low && !PG.REDUCED) {                         // running out: a ripple leaves the pin
        const ph = (tReal * 1.6) % 1;
        ring(p.px, p.py, p.r + 6 + ph * 14, 2, pal.blue, 0.6 * (1 - ph));
      }
      const fr = Math.round(o.fare);
      ctx.font = FONT_LABEL;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = pal.pinInk;
      ctx.fillText(LABELS[fr] || (LABELS[fr] = '€' + fr), p.px, p.py + 1);
      if (k !== 1) ctx.restore();
    }
    for (let i = expired.length - 1; i >= 0; i--) {     // shrinking, greying ghosts of expired pins
      const e = expired[i];
      const f = (tReal - e.t0) / (e.label ? LABEL_S : EXPIRE_S);
      if (f >= 1) { expired.splice(i, 1); continue; }
      P(e.x, e.y);
      const r = 14 * (1 - f * 0.5);
      ctx.fillStyle = pal.dot;
      ctx.globalAlpha = 0.7 * (1 - f);
      ctx.beginPath();
      ctx.arc(pOut.x, pOut.y, r, 0, TAU);
      ctx.fill();
      ring(pOut.x, pOut.y, r + 4 + f * 10, 2, pal.dot, 0.6 * (1 - f));
      if (e.label) {
        ctx.font = FONT_LABEL;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const w = ctx.measureText(e.label).width + 16;
        ctx.globalAlpha = f < 0.6 ? 1 : 1 - (f - 0.6) / 0.4;
        ctx.fillStyle = pal.card;
        ctx.fillRect(pOut.x - w / 2, pOut.y - 40, w, 20);
        ctx.fillStyle = pal.ink;
        ctx.fillText(e.label, pOut.x, pOut.y - 29);
      }
    }
    ctx.globalAlpha = 1;
  }

  // the route the car is driving now: a dark casing and a bright thick line
  function activeLine(xs, ys, n, col) {
    ctx.setLineDash(NO_DASH);
    ctx.strokeStyle = T().casing;
    ctx.lineWidth = 8;
    strokePts(xs, ys, n);
    ctx.strokeStyle = col;
    ctx.lineWidth = 4.5;
    strokePts(xs, ys, n);
  }

  function drawRoutes(G) {
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    if (G.mode === 'pickup' && G.leg) {
      if (G.leg.path && G.leg.path.n > 1) activeLine(G.leg.path.xs, G.leg.path.ys, G.leg.path.n, T().route);
      else {
        ctx.setLineDash(DASH);
        ctx.strokeStyle = T().route;
        ctx.lineWidth = 3.5;
        dashedLine(G.x, G.y, G.leg.x1, G.leg.y1);
        ctx.setLineDash(NO_DASH);
      }
    } else if (G.mode === 'ride' && G.cur && G.cur.pts) {
      activeLine(G.cur.pts.xs, G.cur.pts.ys, G.cur.pts.n, T().route);
    } else if (G.mode === 'cruise' && G.leg) {
      ctx.setLineDash(DASH);
      ctx.strokeStyle = T().muted;
      ctx.globalAlpha = 0.5;
      ctx.lineWidth = 2;
      if (G.leg.path && G.leg.path.n > 1) strokePts(G.leg.path.xs, G.leg.path.ys, G.leg.path.n);
      else dashedLine(G.x, G.y, G.leg.x1, G.leg.y1);
      ctx.setLineDash(NO_DASH);
      ctx.globalAlpha = 1;
    }
    if (G.next && G.cur) {
      ctx.setLineDash(DASH);
      ctx.strokeStyle = T().next;
      ctx.lineWidth = 2;
      dashedLine(G.cur.x1, G.cur.y1, G.next.x0, G.next.y0);
      ctx.setLineDash(NO_DASH);
    }
  }

  // ---- targets: the booked pickup and drop-off stay on the map ----
  function fareTag(txt, px, py, col) {
    const w = txt.length * 8 + 12;
    const h = 16;
    const x = Math.min(W - w - 2, Math.max(2, px - w * 0.5));
    const y = Math.max(zone.top + 2, py);
    addLabelRect(x, y, w, h);
    ctx.fillStyle = T().card;
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = T().ink;
    ctx.font = FONT_LABEL;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(txt, x + w * 0.5, y + h * 0.5 + 0.5);
  }

  // when a target is off screen: an arrow on the edge that points to it
  function edgeArrow(px, py, col) {
    const m = 18;
    const x = Math.min(W - m, Math.max(m, px));
    const y = Math.min(zone.bottom - m, Math.max(zone.top + m, py));
    if (x === px && y === py) return false;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(Math.atan2(py - H * 0.5, px - W * 0.5));
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.moveTo(13, 0);
    ctx.lineTo(-8, -10);
    ctx.lineTo(-8, 10);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    return true;
  }

  function drawPassenger(o, tReal, strong) {
    const col = T().pins[o.c] || T().pins[0];
    P(o.x0, o.y0);
    const px = pOut.x;
    const py = pOut.y;
    if (edgeArrow(px, py, col)) return;
    const r = strong ? 13 : 11;
    const ph = PG.REDUCED ? 0 : (tReal * 1.1) % 1;
    ring(px, py, r + 4 + ph * 12, 2.5, col, 0.7 * (1 - ph));
    ring(px, py, r + 4, 2.5, col, strong ? 0.95 : 0.6);
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.arc(px, py, r, 0, TAU);
    ctx.fill();
    ctx.fillStyle = T().pinInk;          // a person: head and shoulders
    ctx.beginPath();
    ctx.arc(px, py - r * 0.28, r * 0.26, 0, TAU);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(px, py + r * 0.72, r * 0.52, Math.PI, 0);
    ctx.fill();
    const fr = Math.round(o.fare);
    fareTag(LABELS[fr] || (LABELS[fr] = '€' + fr), px, py - r - 24, col);
  }

  function drawDropoff(o, col, strong, tReal) {
    P(o.x1, o.y1);
    const px = pOut.x;
    const py = pOut.y;
    if (strong && edgeArrow(px, py, col)) return;
    if (strong) {
      const ph = PG.REDUCED ? 0 : (tReal * 1.1) % 1;
      ring(px, py, 8 + ph * 14, 2.5, col, 0.7 * (1 - ph));
    }
    ctx.globalAlpha = strong ? 1 : 0.6;
    drawFlag(o.x1, o.y1);
    ctx.globalAlpha = 1;
    if (strong) {
      const fr = Math.round(o.fare);
      fareTag(LABELS[fr] || (LABELS[fr] = '€' + fr), px - 6, py - 42, col);
    }
  }

  function drawEdgePins() {
    for (let i = 0; i < edge.length; i += 3) {
      const o = edge[i];
      const col = T().pins[o.c] || T().pins[0];
      if (!edgeArrow(edge[i + 1], edge[i + 2], col)) continue;
    }
  }

  function drawTargets(G, tReal) {
    const cur = G.cur;
    if (G.mode === 'pickup' && cur) {
      drawDropoff(cur, T().acc, false, tReal);
      drawPassenger(cur, tReal, true);
    } else if (G.mode === 'ride' && cur) {
      drawDropoff(cur, T().acc, true, tReal);
    }
    if (G.next) drawPassenger(G.next, tReal, false);
  }

  function drawTrail(G) {
    const tr = G.trail;
    if (!tr || tr.length < 4) return;
    const s = view.scale;
    const ox = W * 0.5 - view.cx * s;
    const oy = H * 0.5 - view.cy * s;
    const maxJump = 800;
    ctx.strokeStyle = T().trail;
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
        ctx.strokeStyle = T().ghost;
        ctx.globalAlpha = 0.35 * i / GHOST_TRAIL_N;
        ctx.beginPath();
        ctx.moveTo(ghostTrail[i * 2 - 2] * s + ox, ghostTrail[i * 2 - 1] * s + oy);
        ctx.lineTo(ghostTrail[i * 2] * s + ox, ghostTrail[i * 2 + 1] * s + oy);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      ctx.beginPath();
      ctx.moveTo(ghostTrail[(ghostTrailN - 1) * 2] * s + ox, ghostTrail[(ghostTrailN - 1) * 2 + 1] * s + oy);
      ctx.lineTo(ghostOut.x * s + ox, ghostOut.y * s + oy);
      ctx.stroke();
    }
    const px = ghostOut.x * s + ox;
    const py = ghostOut.y * s + oy;
    const a = PG.cars.turn(8, ghostOut.hx, ghostOut.hy, dtNow, false);
    if (px < -40 || py < -40 || px > W + 40 || py > H + 40) return;
    const len = carLen('ghost');
    PG.cars.draw(ctx, px, py, a, len, T().ghost, 0.6, 'ghost');
    ctx.font = FONT_TAG;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    tag('Привид', px, py - len * 0.5 - 8, T().ghost, py - len * 0.5 - 8 - 12 > zone.top);
  }

  // name tag above a car; skipped when it would sit under the HUD or on another label
  function tag(name, px, py, color, ok) {
    if (!ok || !name) return;
    const w = name.length * 7 + 20;
    const x = px - w * 0.5;
    const y = py - 14;
    if (x < 2 || x + w > W - 2 || !labelFree(x, y, w, TAG_H) || !addLabelRect(x, y, w, TAG_H)) return;
    const pal = T();
    ctx.fillStyle = pal.card;
    ctx.fillRect(x, y, w, TAG_H);
    ctx.fillStyle = color;                              // the car's colour as a dot, the name in ink
    ctx.beginPath();
    ctx.arc(x + 8, y + TAG_H * 0.5, 3.5, 0, TAU);
    ctx.fill();
    ctx.fillStyle = pal.ink;
    ctx.textAlign = 'left';
    ctx.fillText(name, x + 15, y + 12);
    ctx.textAlign = 'center';
  }

  function drawRivals(G, hx0, hy0) {
    const rv = G.rivals;
    if (!rv || !rv.length) return;
    const len = carLen('rival');
    const near = len * 1.1;
    const away = (carLen('hero') + len) * 0.5 + 6;   // where a rival goes when it sits on the hero
    const n = Math.min(rv.length, 8);
    ctx.font = FONT_TAG;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    for (let i = 0; i < n; i++) {         // fan out cars that sit on top of the hero or of each other
      P(rv[i].x, rv[i].y);
      let x = pOut.x;
      let y = pOut.y;
      let c = 0;
      const onHero = Math.hypot(x - hx0, y - hy0) < away;
      for (let j = 0; j < i; j++) if (Math.hypot(x - rx[j], y - ry[j]) < near) c++;
      if (c || onHero) {
        const a = (c + 1) * 2.4 + i * 0.7;
        const d = (onHero ? away : near) + c * 7;
        x += Math.cos(a) * d;
        y += Math.sin(a) * d;
      }
      rx[i] = x;
      ry[i] = y;
    }
    for (let i = 0; i < n; i++) {
      const r = rv[i];
      const px = rx[i];
      const py = ry[i];
      const a = PG.cars.turn(i, r.hx, r.hy, dtNow, false);
      if (px < -40 || py < -40 || px > W + 40 || py > H + 40) continue;
      PG.cars.draw(ctx, px, py, a, len, r.color || '#ffffff', 1, 'rival');
    }
    const peeking = clock() - peekAt < PEEK_S;
    for (let i = 0; i < n; i++) {         // names: rivals near the hero, or the one just tapped or hovered
      const r = rv[i];
      if (rx[i] < -40 || ry[i] < -40 || rx[i] > W + 40 || ry[i] > H + 40) continue;
      const near = Math.hypot(r.x - G.x, r.y - G.y) <= NEAR_M;
      if (!near && !(peeking && Math.hypot(rx[i] - peekX, ry[i] - peekY) <= Math.max(26, len))) continue;
      tag(r.name || r.id || '', rx[i], ry[i] - len * 0.5 - 2, r.color || '#ffffff', ry[i] - len * 0.5 - 14 > zone.top);
    }
  }

  function drawPlayer(G, tReal) {
    P(G.x, G.y);
    const px = pOut.x;
    const py = pOut.y;
    const len = carLen('hero');
    const a = PG.cars.turn(9, G.hx, G.hy, dtNow, false);
    ring(px, py, len * 0.62, 2, T().acc, 0.5);
    PG.cars.draw(ctx, px, py, a, len, T().acc, 1, 'hero');
    ctx.font = FONT_TAG;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    tag('Ти', px, py - len * 0.8 - 3, T().acc, py - len * 0.8 - 3 - 12 > zone.top);
  }

  function updateCenterBtn(show) {
    if (!centerBtn || centerShown === show) return;
    centerShown = show;
    centerBtn.hidden = !show;
    if (zoomBox) zoomBox.hidden = !show || document.body.classList.contains('party-host');
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
    dtNow = dt;

    const G = PG.engine && PG.engine.G;
    const play = PG.screen === 'play' && !!G && !!G.sh;
    updateCamera(dt, G, play);
    updateCenterBtn(play);
    if ((++frameNo & 63) === 0) measureZones();

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
    const pal = T();
    ctx.fillStyle = pal.bg;
    ctx.fillRect(0, 0, W, H);
    // map plate: flat ground, no outline
    P(0, 0);
    if (PG.render.ground !== false) drawGround(pal, pOut.x, pOut.y);

    drawStreets();
    runLayers(now, true);

    if (!G || !G.sh) {
      pins.length = 0;
      runLayers(now, false);
      return;
    }

    labelN = 0;
    collectPins(G, t);
    drawFaint(G);
    drawRoutes(G);
    drawPinDots(G, t);
    drawTargets(G, t);
    drawEdgePins();
    drawTrail(G);
    drawGhost(G);
    P(G.x, G.y);
    const hx = pOut.x;
    const hy = pOut.y;
    const hl = carLen('hero');
    addLabelRect(hx - hl * 0.8, hy - hl * 0.8, hl * 1.6, hl * 1.6);   // keep labels off the player's car
    drawRivals(G, hx, hy);
    drawPlayer(G, t);
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

    zoomBox = document.createElement('div');
    zoomBox.id = 'map-zoom';
    zoomBox.hidden = true;
    zoomBox.setAttribute('data-no-map', '');
    [['+', ZOOM_STEP, 'Збільшити мапу'], ['−', 1 / ZOOM_STEP, 'Зменшити мапу']].forEach(function (d) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = d[0];
      b.setAttribute('aria-label', d[2]);
      b.addEventListener('click', function () { zoomStep(d[1]); });
      zoomBox.appendChild(b);
    });
    stage.appendChild(zoomBox);

    resize();
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(resize).observe(stage);
    root.addEventListener('resize', resize);

    if (PG.bus) {
      PG.bus.on('theme', function () {            // re-tint the streets and the ground for the new theme
        dimCv = null;
        tileName = '';
        for (const k in caches) delete caches[k];
      });
      PG.bus.on('shift:start', function () {
        const G = PG.engine && PG.engine.G;
        measureZones();
        ghostTrailN = 0;
        ghostTrailT = -1e9;
        lastPanClock = -1e9;
        recenterUntil = 0;
        born.clear();
        prevPins.clear();
        prevBright.clear();
        expired.length = 0;
        punch = 0;
        PG.cars.reset();
        resetCamera(G ? G.x : HOME_X, G ? G.y : HOME_Y);
        if (!PG.REDUCED) {                       // ease in from a wider view
          zoomEaseTo = view.scale;
          zoomEaseUntil = clock() + 1.6;
          view.scale *= 0.7;
          clampView();
        }
      });
    }
  }

  PG.render = {
    ground: true,        // false: the ground tile is not drawn (a basemap layer takes its place)
    init: init,
    draw: draw,
    P: P,
    screenToWorld: screenToWorld,
    pins: pins,
    view: view,
    onDraw: onDraw,
    drawsRivals: true,
    zone: zone,
    kick: kick,
    // for other modules (party mode): a car sprite at screen px with a smoothed heading
    carLen: carLen,
    // helpers used by 70_input.js
    nearestPin: nearestPin,
    panBy: panBy,
    zoomAt: zoomAt,
    zoomStep: zoomStep,
    peek: peek,
    recenter: recenter,
  };
})(typeof window !== 'undefined' ? window : globalThis);
