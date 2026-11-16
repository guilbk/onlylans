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
      ['#d6bd9c', '#c48a66', '#9fb0a0'], ['#d6c4a6', '#c9a98a', '#b8805e'], ['#c4623f', '#d27a4e']],
    night: [
      ['#6b3a3a', '#6b4d2a', '#2c4570', '#6b3a52'], ['#2c3342', '#5a3428', '#363d4d'],
      ['#34506f', '#3d4b63', '#2e4560'], ['#7d8aa6', '#98a4be', '#6e7a96'],
      ['#3a4150', '#47443f', '#343e54'], ['#5a4d3d', '#573326', '#6a5f4a'],
      ['#66503c', '#563022', '#5f574c'], ['#5c5040', '#583a2c', '#625a4a'], ['#5a3226', '#66402e']],
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
  const R4 = [-0.5, -0.5, 0.5, -0.5, 0.5, 0.5, -0.5, 0.5];
  const LOD_K = 0.12;                // below this zoom (px per metre) every 3rd building is drawn at 1.7x

  function buildBuildings(Bd) {      // once: per tile one Path2D per colour, plain filled rectangles
    const tiles = {}, b = Bd.b;
    const tile = function (x, y) {
      const key = Math.floor(x / TILE) + ',' + Math.floor(y / TILE);
      return tiles[key] || (tiles[key] = {
        x0: Math.floor(x / TILE) * TILE - 80, y0: Math.floor(y / TILE) * TILE - 80,
        fills: {}, lod: {}, trees: new Path2D(),
      });
    };
    let x = 0, y = 0;
    for (let i = 0, n = 0; i < b.length; i += 6, n++) {
      x += b[i]; y += b[i + 1];
      const w = b[i + 2], h = b[i + 3], a = b[i + 4], key = b[i + 5] >> 3;     // district * 8 + colour
      const t = tile(x, y);
      quad(t.fills[key] || (t.fills[key] = new Path2D()), x, y, w, h, a, R4);
      if (n % 3 === 0) quad(t.lod[key] || (t.lod[key] = new Path2D()), x, y, w * 1.7, h * 1.7, a, R4);
    }
    const tr = Bd.trees;
    for (let i = 0; i < tr.length; i += 2) { const t = tile(tr[i], tr[i + 1]); t.trees.moveTo(tr[i] + 4, tr[i + 1]); t.trees.arc(tr[i], tr[i + 1], 4, 0, Math.PI * 2); }
    return Object.keys(tiles).map(function (k) { return tiles[k]; });
  }

  function drawBuildings(ctx, p, night, k, x0, y0) {
    if (!PG.buildings) return;
    if (!bld) bld = buildBuildings(PG.buildings);
    const W = ctx.canvas.clientWidth || 800, H = ctx.canvas.clientHeight || 800, th = night ? 1 : 0;
    const pal = night ? BP.night : BP.day, size = (TILE + 160) * k, lod = k < LOD_K;
    ctx.save();
    ctx.translate(x0, y0);
    ctx.scale(k, k);
    for (let i = 0; i < bld.length; i++) {
      const t = bld[i], sx = x0 + t.x0 * k, sy = y0 + t.y0 * k;
      if (sx > W || sy > H || sx + size < 0 || sy + size < 0) continue;
      ctx.fillStyle = BP.tree[th]; ctx.fill(t.trees);
      const set = lod ? t.lod : t.fills;
      for (const key in set) { ctx.fillStyle = pal[key >> 3][key & 7]; ctx.fill(set[key]); }
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
