// Porto base map: sea, Douro, parks, districts and bridges as flat patches (style A, no outlines).
// Data: PG.basemap from pipeline/basemap.py (hand-placed game-model decoration, not UCI data).
// Drawn translucent so the streets from 40_render.js stay readable; the landmarks (42) go above.
(function (root) {
  const PG = root.PG = root.PG || {};
  const DAY = {
    sea: 'rgba(122,178,226,0.9)', river: 'rgba(143,192,232,0.9)', park: 'rgba(159,211,160,0.75)',
    d0: 'rgba(236,223,198,0.5)', d1: 'rgba(232,196,160,0.45)', bridge: '#c4552f', text: 'rgba(85,98,127,0.75)',
  };
  const NIGHT = {
    sea: 'rgba(12,32,80,0.92)', river: 'rgba(16,40,90,0.92)', park: 'rgba(18,58,58,0.8)',
    d0: 'rgba(22,36,77,0.55)', d1: 'rgba(27,44,94,0.5)', bridge: '#8fb8ff', text: 'rgba(147,163,204,0.8)',
  };
  const LABEL_LO = 0.03, LABEL_FADE = 0.09;      // px per metre: district names fade out when zoomed in
  // buildings: per district id (see pipeline/buildings.py) colours [day..., night...]; roofs 0 flat 1 hip 2 court 3 L 4 villa 5 shed 6 crane
  const BP = {
    day: [
      ['#d9694a', '#e0953f', '#4f7fc4', '#e58aa6', '#c2542f', '#e7b24a'],
      ['#6f7886', '#c2603f', '#8a919c'], ['#7fa6c9', '#9aa8b8', '#6d8aa8', '#b4c4d2'],
      ['#f4efe6', '#ffffff', '#efe3d0'], ['#8a8f96', '#a39a8c', '#7d8794'],
      ['#c9b08a', '#b5654a', '#d4c3a1', '#a8806a'], ['#d8b894', '#b8714f', '#cdbfae', '#a9856b'],
      ['#cdb99b', '#b77a58', '#d6c8b0', '#9d8b7a']],
    night: [
      ['#6b3a3a', '#6b4d2a', '#2c4570', '#6b3a52', '#5e2e24', '#6b5a30'],
      ['#2c3342', '#5a3428', '#363d4d'], ['#34506f', '#3d4b63', '#2e4560', '#475a72'],
      ['#7d8aa6', '#98a4be', '#6e7a96'], ['#3a4150', '#47443f', '#343e54'],
      ['#5a4d3d', '#573326', '#6a5f4a', '#4b3a35'], ['#66503c', '#563022', '#5f574c', '#4a3a33'],
      ['#5c5040', '#583a2c', '#625a4a', '#473f38']],
    garden: ['rgba(140,200,130,0.8)', 'rgba(24,62,52,0.8)'],
    tree: ['#5a9a5a', '#1d4a40'], ridge: ['rgba(255,255,255,0.45)', 'rgba(255,255,255,0.12)'],
    lit: 'rgba(255,208,120,0.9)', crane: ['#e8742a', '#b86030'],
  };
  const TILE = 700;                              // metres per culling tile
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

  function buildBuildings(Bd) {       // once: per tile, one Path2D per colour (+ridges, windows, gardens)
    const tiles = {}, b = Bd.b;
    const tile = function (x, y) {
      const key = Math.floor(x / TILE) + ',' + Math.floor(y / TILE);
      return tiles[key] || (tiles[key] = {
        x0: Math.floor(x / TILE) * TILE - 80, y0: Math.floor(y / TILE) * TILE - 80, fills: {},
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
    const tr = Bd.trees;
    for (let i = 0; i < tr.length; i += 2) { const t = tile(tr[i], tr[i + 1]); t.trees.moveTo(tr[i] + 4, tr[i + 1]); t.trees.arc(tr[i], tr[i + 1], 4, 0, Math.PI * 2); }
    const out = [];
    Object.keys(tiles).forEach(function (k) { out.push(tiles[k]); });
    return out;
  }

  function drawBuildings(ctx, p, night, k, x0, y0) {
    if (!PG.buildings) return;
    if (!bld) bld = buildBuildings(PG.buildings);
    const W = ctx.canvas.clientWidth || 800, H = ctx.canvas.clientHeight || 800, th = night ? 1 : 0;
    const pal = night ? BP.night : BP.day, size = (TILE + 160) * k;
    ctx.save();
    ctx.translate(x0, y0);
    ctx.scale(k, k);
    for (let i = 0; i < bld.length; i++) {
      const t = bld[i], sx = x0 + t.x0 * k, sy = y0 + t.y0 * k;
      if (sx > W || sy > H || sx + size < 0 || sy + size < 0) continue;
      ctx.fillStyle = BP.garden[th]; ctx.fill(t.garden);
      ctx.fillStyle = BP.tree[th]; ctx.fill(t.trees);
      for (const key in t.fills) { ctx.fillStyle = pal[key >> 3][key & 7]; ctx.fill(t.fills[key], 'evenodd'); }
      ctx.fillStyle = BP.crane[th]; ctx.fill(t.crane);
      if (k > 0.1) { ctx.strokeStyle = BP.ridge[th]; ctx.lineWidth = 1.2; ctx.stroke(t.ridge); }
      if (night && k > 0.05) { ctx.fillStyle = BP.lit; ctx.fill(t.lit); }
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
    ctx.strokeStyle = p.bridge;
    ctx.lineWidth = 4 / k;
    ctx.lineCap = 'butt';
    for (let i = 0; i < built.bridges.length; i++) ctx.stroke(built.bridges[i]);
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
