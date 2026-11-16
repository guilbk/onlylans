// Porto base map: sea, Douro, parks, districts and bridges as flat patches (style A, no outlines).
// Data: PG.basemap from pipeline/basemap.py (hand-placed game-model decoration, not UCI data).
// Drawn translucent so the streets from 40_render.js stay readable; the landmarks (42) go above.
(function (root) {
  const PG = root.PG = root.PG || {};
  const DAY = {
    land: 'rgba(238,234,226,0.7)', sea: 'rgba(104,168,226,0.95)', river: 'rgba(112,176,232,0.95)', park: 'rgba(142,206,138,0.95)',
    d0: 'rgba(226,218,200,0.25)', d1: 'rgba(230,208,180,0.25)', bridge: '#fffaf0', arch: '#8a7f70', text: 'rgba(85,98,127,0.75)',
  };
  const NIGHT = {
    sea: 'rgba(12,32,80,0.92)', river: 'rgba(16,40,90,0.92)', park: 'rgba(18,58,58,0.8)',
    land: null, d0: 'rgba(22,36,77,0.55)', d1: 'rgba(27,44,94,0.5)', bridge: '#b9cdf0', arch: '#5f86c6', text: 'rgba(147,163,204,0.8)',
  };
  const LABEL_LO = 0.03, LABEL_FADE = 0.09;      // px per metre: district names fade out when zoomed in
  // buildings: per district id (see pipeline/buildings.py) colours [day..., night...]; roofs 0 flat 1 hip 2 court 3 L 4 villa 5 shed 6 crane
  const BP = {
    day: [
      ['#e0775a', '#e8a94a', '#5b86c6', '#e993ab'], ['#8b93a0', '#b5694a', '#d29b5e'],
      ['#8fb2d0', '#a7b5c4', '#5f86ad'], ['#f6f2ea', '#fffdf8', '#e6d3b3'],
      ['#9aa0a8', '#b39d86', '#d0743a'], ['#cdb590', '#bf8a68', '#a8573c'],
      ['#d6bd9c', '#c48a66', '#9fb0a0'], ['#d6c4a6', '#c9a98a', '#b8805e']],
    night: [
      ['#6b3a3a', '#6b4d2a', '#2c4570', '#6b3a52'], ['#2c3342', '#5a3428', '#363d4d'],
      ['#34506f', '#3d4b63', '#2e4560'], ['#7d8aa6', '#98a4be', '#6e7a96'],
      ['#3a4150', '#47443f', '#343e54'], ['#5a4d3d', '#573326', '#6a5f4a'],
      ['#66503c', '#563022', '#5f574c'], ['#5c5040', '#583a2c', '#625a4a']],
    garden: ['rgba(140,200,130,0.8)', 'rgba(24,62,52,0.8)'],
    tree: ['#5a9a5a', '#1d4a40'], ridge: ['rgba(255,255,255,0.45)', 'rgba(255,255,255,0.12)'],
    lit: 'rgba(255,208,120,0.9)', crane: ['#e8742a', '#b86030'],
  };
  // dense terraces (PG.buildings.rows): terracotta roof shades per row, darker at night; thin edges between houses
  const ROOF = {
    day: ['#c8693f', '#b95c38', '#d27d4e', '#ad5232', '#d89060', '#c1704a'],
    night: ['#5e3030', '#522a2a', '#6a3b32', '#4a2528', '#5a3a30', '#4f2e2e'],
    edge: ['rgba(110,50,30,0.55)', 'rgba(10,6,16,0.6)'], alt: ['rgba(255,225,190,0.16)', 'rgba(255,200,140,0.07)'],
    win: 'rgba(255,196,110,0.95)',
  };
  const TILE = 700, MARG = 160, ZOOM_HOUSES = 0.14;   // metres per culling tile; margin; px/m where single houses show
  let built = null, bld = null;

  function isNight() {
    if (PG.theme && PG.theme.name) return PG.theme.name === 'night';
    const G = PG.engine && PG.engine.G;
    if (!G || !G.sh) return true;
    const h = Math.floor(G.sh.startHour + (G.t || 0) / 3600) % 24;
    return h >= 22 || h <= 5;
  }

  function path(flat, close) {
    const p = new Path2D();
    p.moveTo(flat[0], flat[1]);
    for (let i = 2; i < flat.length; i += 2) p.lineTo(flat[i], flat[i + 1]);
    if (close) p.closePath();
    return p;
  }

  function build(B) {      // once: Path2D objects in world metres, so a frame allocates nothing
    return {
      sea: path(B.sea, true), river: path(B.river, true),
      parks: B.parks.map(function (q) { return path(q.poly, true); }),
      districts: B.districts.map(function (q) { return path(q.poly, true); }),
      bridges: B.bridges.map(function (q) { return path(q.line, false); }),
      arches: B.bridges.map(function (q) {          // small arch hint: a bow across the deck
        const l = q.line, a = new Path2D(), mx = (l[0] + l[2]) / 2, my = (l[1] + l[3]) / 2;
        if (q.arch) { a.moveTo(l[0], l[1]); a.quadraticCurveTo(mx - (l[3] - l[1]) * 0.14, my + (l[2] - l[0]) * 0.14, l[2], l[3]); }
        return a;
      }),
    };
  }

  function quad(p, x, y, w, h, a, pts) {          // closed polygon from local points rotated by a degrees
    const c = Math.cos(a * Math.PI / 180), n = Math.sin(a * Math.PI / 180);
    for (let i = 0; i < pts.length; i += 2) {
      const lx = pts[i] * w, ly = pts[i + 1] * h, X = x + lx * c - ly * n, Y = y + lx * n + ly * c;
      if (i) p.lineTo(X, Y); else p.moveTo(X, Y);
    }
    p.closePath();
  }
  const R4 = [-0.5, -0.5, 0.5, -0.5, 0.5, 0.5, -0.5, 0.5], R_IN = [-0.25, -0.25, 0.25, -0.25, 0.25, 0.25, -0.25, 0.25];
  const R_L = [-0.5, -0.5, 0.5, -0.5, 0.5, 0, 0, 0, 0, 0.5, -0.5, 0.5];

  function hash(x, y, s) {                         // cheap deterministic [0, 1) per position
    let h = (Math.imul(x | 0, 73856093) ^ Math.imul(y | 0, 19349663) ^ Math.imul(s, 83492791)) >>> 0;
    h = Math.imul(h ^ (h >>> 15), 2246822519) >>> 0; h = Math.imul(h ^ (h >>> 13), 3266489917) >>> 0;
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }

  function houses(t, rw) {           // lazily, per tile: edges between houses, a lighter alternate house, lit windows
    t.div = { edge: new Path2D(), alt: new Path2D(), win: new Path2D() };
    for (let q = 0; q < t.rr.length; q++) {
      const i = t.rr[q], x = rw[i], y = rw[i + 1], L = rw[i + 2], a = rw[i + 3], D = rw[i + 4];
      const c = Math.cos(a * Math.PI / 180), n = Math.sin(a * Math.PI / 180), hx = -n * D / 2, hy = c * D / 2;
      for (let s = 0, k = 0; s < L - 0.5; k++) {
        const wd = Math.min(L - s, 4.6 + 3 * hash(x + k, y, 2)), ex = x + c * s, ey = y + n * s;
        if (s > 0) { t.div.edge.moveTo(ex - hx, ey - hy); t.div.edge.lineTo(ex + hx, ey + hy); }
        const r = hash(x + k, y, 3);
        if (r < 0.28 || r > 0.9) {        // a lighter roof on some houses; a lit window on a few
          const mx = ex + c * wd / 2, my = ey + n * wd / 2;
          if (r < 0.28) { t.div.alt.moveTo(ex - hx, ey - hy); t.div.alt.lineTo(ex + c * wd - hx, ey + n * wd - hy); t.div.alt.lineTo(ex + c * wd + hx, ey + n * wd + hy); t.div.alt.lineTo(ex + hx, ey + hy); t.div.alt.closePath(); }
          else t.div.win.rect(mx - 0.9, my - 0.9, 1.8, 1.8);
        }
        s += wd;
      }
    }
  }

  function buildBuildings(Bd) {       // once: per tile, one Path2D per colour (+ridges, windows, gardens)
    const tiles = {}, b = Bd.b;
    const tile = function (x, y) {
      const key = Math.floor(x / TILE) + ',' + Math.floor(y / TILE);
      return tiles[key] || (tiles[key] = {
        x0: Math.floor(x / TILE) * TILE - MARG, y0: Math.floor(y / TILE) * TILE - MARG, fills: {}, rows: {}, rr: [], div: null,
        ridge: new Path2D(), lit: new Path2D(), garden: new Path2D(), trees: new Path2D(), crane: new Path2D(),
      });
    };
    for (let i = 0; i < b.length; i += 8) {
      const x = b[i], y = b[i + 1], w = b[i + 2], h = b[i + 3], a = b[i + 4], d = b[i + 5], c = b[i + 6], r = b[i + 7];
      const t = tile(x, y);
      if (r === 6) { quad(t.crane, x, y, w, h, a, R4); continue; }
      const key = d * 8 + c;
      const p = t.fills[key] || (t.fills[key] = new Path2D());
      if (r === 4) quad(t.garden, x, y, w + 14, h + 14, a, R4);
      quad(p, x, y, w, h, a, r === 3 ? R_L : R4);
      if (r === 2) quad(p, x, y, w, h, a, R_IN);                 // courtyard hole (evenodd)
      if (r === 1 || r === 4) {                                   // hip roof: ridge along the long side
        const lw = w >= h;
        const c2 = Math.cos(a * Math.PI / 180), s2 = Math.sin(a * Math.PI / 180), L = (lw ? w : h) * 0.3;
        const ux = lw ? c2 : -s2, uy = lw ? s2 : c2;
        t.ridge.moveTo(x - ux * L, y - uy * L); t.ridge.lineTo(x + ux * L, y + uy * L);
      }
      if (d !== 3 && d !== 4 && d !== 7 && (i / 8) % 3 === 0) {   // a lit window at night in dense districts
        t.lit.moveTo(x + 2.5, y); t.lit.arc(x, y, 2.5, 0, Math.PI * 2);
      }
    }
    const rw = Bd.rows || [];
    for (let i = 0; i < rw.length; i += 6) {            // terraced rows: one quad per row, houses cut lazily when zoomed in
      const x = rw[i], y = rw[i + 1], L = rw[i + 2], a = rw[i + 3], D = rw[i + 4];
      const t = tile(x, y), sh = Math.floor(hash(x, y, 1) * 6);
      const c = Math.cos(a * Math.PI / 180), n = Math.sin(a * Math.PI / 180), hx = -n * D / 2, hy = c * D / 2, p = t.rows[sh] || (t.rows[sh] = new Path2D());
      p.moveTo(x - hx, y - hy); p.lineTo(x + c * L - hx, y + n * L - hy); p.lineTo(x + c * L + hx, y + n * L + hy); p.lineTo(x + hx, y + hy); p.closePath();
      t.rr.push(i);
    }
    const tr = Bd.trees;
    for (let i = 0; i < tr.length; i += 2) { const t = tile(tr[i], tr[i + 1]); t.trees.moveTo(tr[i] + 4, tr[i + 1]); t.trees.arc(tr[i], tr[i + 1], 4, 0, Math.PI * 2); }
    const out = [];
    Object.keys(tiles).forEach(function (k) { out.push(tiles[k]); });
    return out;
  }

  function paintTile(ctx, t, night, k) {            // one tile in world metres at k px per metre
    const th = night ? 1 : 0, pal = night ? BP.night : BP.day, roof = night ? ROOF.night : ROOF.day;
    ctx.fillStyle = BP.garden[th]; ctx.fill(t.garden);
    ctx.fillStyle = BP.tree[th]; ctx.fill(t.trees);
    for (const key in t.fills) { ctx.fillStyle = pal[key >> 3][key & 7]; ctx.fill(t.fills[key], 'evenodd'); }
    for (const sh in t.rows) { ctx.fillStyle = roof[sh]; ctx.fill(t.rows[sh]); }
    if (k > ZOOM_HOUSES) {
      if (!t.div) houses(t, PG.buildings.rows);
      ctx.fillStyle = ROOF.alt[th]; ctx.fill(t.div.alt);
      ctx.strokeStyle = ROOF.edge[th]; ctx.lineWidth = 0.7 / k; ctx.stroke(t.div.edge);
      if (night) { ctx.fillStyle = ROOF.win; ctx.fill(t.div.win); }
    }
    ctx.fillStyle = BP.crane[th]; ctx.fill(t.crane);
    if (k > 0.1) { ctx.strokeStyle = BP.ridge[th]; ctx.lineWidth = 0.8 / k; ctx.stroke(t.ridge); }
    if (night && k > 0.05) { ctx.fillStyle = BP.lit; ctx.fill(t.lit); }
  }

  // Up to CACHE_K px/m a tile is drawn from a bitmap (two detail levels, day and night), a couple of new bitmaps per frame:
  // thousands of vector rows were too slow for a 1366 px screen on a slow CPU.
  const CACHE_K = [0.12, 0.3], SPAN = TILE + 2 * MARG;
  let budget = 0;
  function bitmap(t, lvl, night) {
    const slot = lvl * 2 + (night ? 1 : 0), have = t.img || (t.img = []);
    if (have[slot]) return have[slot];
    if (budget <= 0 || typeof document === 'undefined') return null;
    budget--;
    const s = CACHE_K[lvl], c = document.createElement('canvas');
    c.width = c.height = Math.ceil(SPAN * s);
    const g = c.getContext('2d');
    g.scale(c.width / SPAN, c.width / SPAN); g.translate(-t.x0, -t.y0);
    paintTile(g, t, night, s);
    return (have[slot] = c);
  }

  function drawBuildings(ctx, p, night, k, x0, y0) {
    if (!PG.buildings) return;
    if (!bld) bld = buildBuildings(PG.buildings);
    const W = ctx.canvas.clientWidth || 800, H = ctx.canvas.clientHeight || 800, size = SPAN * k;
    const lvl = k <= CACHE_K[0] ? 0 : k <= CACHE_K[1] ? 1 : -1;
    budget = 2;
    ctx.save();
    ctx.translate(x0, y0);
    ctx.scale(k, k);
    for (let i = 0; i < bld.length; i++) {
      const t = bld[i], sx = x0 + t.x0 * k, sy = y0 + t.y0 * k;
      if (sx > W || sy > H || sx + size < 0 || sy + size < 0) continue;
      const img = lvl < 0 ? null : bitmap(t, lvl, night);
      if (img) ctx.drawImage(img, t.x0, t.y0, SPAN, SPAN); else paintTile(ctx, t, night, k);
    }
    ctx.restore();
  }

  function draw(ctx, now) {
    const B = PG.basemap, R = PG.render;
    if (!B || !R || !R.P || typeof Path2D === 'undefined') return;
    if (!built) built = build(B);
    const p = isNight() ? NIGHT : DAY;
    const a = R.P(0, 0), x0 = a.x, y0 = a.y;
    const k = Math.abs(R.P(100, 0).x - x0) / 100;       // px per metre, same helper as PG.fx
    ctx.save();
    ctx.translate(x0, y0);
    ctx.scale(k, k);
    if (p.land) { ctx.fillStyle = p.land; ctx.fillRect(-4000, -4000, 40000, 40000); }
    for (let i = 0; i < built.districts.length; i++) {
      ctx.fillStyle = i % 2 ? p.d1 : p.d0;
      ctx.fill(built.districts[i]);
    }
    ctx.fillStyle = p.park;
    for (let i = 0; i < built.parks.length; i++) ctx.fill(built.parks[i]);
    ctx.fillStyle = p.sea;
    ctx.fill(built.sea);
    ctx.fillStyle = p.river;
    ctx.fill(built.river);
    ctx.lineCap = 'butt';
    ctx.strokeStyle = p.arch; ctx.lineWidth = 8 / k;               // dark casing under the light deck
    for (let i = 0; i < built.bridges.length; i++) ctx.stroke(built.bridges[i]);
    ctx.strokeStyle = p.bridge; ctx.lineWidth = 5.5 / k;
    for (let i = 0; i < built.bridges.length; i++) ctx.stroke(built.bridges[i]);
    ctx.strokeStyle = p.arch; ctx.lineWidth = 2 / k;
    for (let i = 0; i < built.arches.length; i++) ctx.stroke(built.arches[i]);
    ctx.restore();
    drawBuildings(ctx, p, p === NIGHT, k, x0, y0);
    const f = Math.max(0, Math.min(1, (LABEL_FADE - k) / (LABEL_FADE - LABEL_LO)));
    if (f > 0) {
      ctx.save();
      ctx.globalAlpha = f;
      ctx.font = '700 10px Trebuchet MS, Helvetica Neue, system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillStyle = p.text;
      for (let i = 0; i < B.districts.length; i++) {
        const d = B.districts[i];
        ctx.fillText(d.name.toUpperCase(), x0 + d.x * k, y0 + d.y * k);
      }
      ctx.restore();
    }
  }

  // 39 loads before 40_render.js and 99_boot.js only inits known modules: register once PG.render exists
  function register(tries) {
    const R = PG.render;
    if (R && R.onDraw) {
      R.onDraw(draw, -4);             // under the landmarks (z -2), the radio glow and the pins
      if (PG.basemap && typeof R.ground !== 'undefined') R.ground = false;
    } else if (tries > 0) {
      setTimeout(function () { register(tries - 1); }, 0);
    }
  }
  register(50);
})(typeof window !== 'undefined' ? window : globalThis);
