// Porto base map: sea, Douro, parks, districts and bridges as flat patches (style A, no outlines).
// Data: PG.basemap from pipeline/basemap.py (hand-placed game-model decoration, not UCI data).
// Drawn translucent so the streets from 40_render.js stay readable; the landmarks (42) go above.
(function (root) {
  const PG = root.PG = root.PG || {};
  // Every district has its own ground colour so the player learns the city by sight (day, night).
  // order of ids = pipeline/buildings.py: Ribeira, Baixa, Boavista, Foz, Matosinhos, Campanhã, Bonfim
  const GROUND = {
    Ribeira: ['#efc19a', '#3d2a46'], Baixa: ['#f2dc9e', '#2a3560'], Boavista: ['#d3dbe6', '#1f3b5c'],
    Foz: ['#e4edcd', '#1c4046'], Matosinhos: ['#c7dbe3', '#173a52'], 'Campanhã': ['#dccdc4', '#33284e'],
    Bonfim: ['#eab9aa', '#4a2a44'],
  };
  const DAY = {
    land: '#f1e9d8', sea: '#5d9fdc', shore: '#a9d2f2', river: '#6fb2ea', bank: '#b4d9f4', park: '#a9d98e', bridge: '#fffdf6', arch: '#7a6f60',
    casing: '#bda57a', main: '#fffaf0', mid: '#e8dcc2', minor: '#e8dcc2', text: 'rgba(60,48,40,0.85)', halo: 'rgba(255,250,240,0.8)',
  };
  const NIGHT = {
    land: '#0c1634', sea: '#0a2a62', shore: '#1b4a96', river: '#0f3a80', bank: '#1f5cb0', park: '#12483f', bridge: '#cfe0ff', arch: '#6b90d0',
    casing: '#07102a', main: '#6fb4ff', mid: '#27508f', minor: '#18305f', text: 'rgba(214,226,255,0.9)', halo: 'rgba(8,15,36,0.7)',
  };
  const STREET_PX = {main: [18, 3.4], mid: [5, 0.9], minor: [3, 0.5]};   // [width in metres, minimum width in px]
  const LABEL_LO = 0.05, LABEL_FADE = 0.12;      // px per metre: district names fade out when zoomed in
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
  const SHOW_BUILDINGS = false;                  // calm map: no building texture (data stays for a later look)
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

  function multi(lines) {        // many polylines in one Path2D (one stroke call per class)
    const p = new Path2D();
    for (let i = 0; i < lines.length; i++) {
      const f = lines[i];
      p.moveTo(f[0], f[1]);
      for (let j = 2; j < f.length; j += 2) p.lineTo(f[j], f[j + 1]);
    }
    return p;
  }

  function build(B) {      // once: Path2D objects in world metres, so a frame allocates nothing
    return {
      sea: path(B.sea, true), river: path(B.river, true),
      parks: B.parks.map(function (q) { return path(q.poly, true); }),
      districts: B.districts.map(function (q) { return path(q.poly, true); }),
      streets: PG.streets ? {main: multi(PG.streets.main), mid: multi(PG.streets.mid), minor: multi(PG.streets.minor)} : null,
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
    ctx.fillStyle = p.land; ctx.fillRect(-4000, -4000, 40000, 40000);
    const th = p === NIGHT ? 1 : 0;
    for (let i = 0; i < built.districts.length; i++) {
      const col = (GROUND[B.districts[i].name] || [p.land, p.land])[th];
      ctx.fillStyle = col; ctx.strokeStyle = col; ctx.lineJoin = 'round';
      ctx.globalAlpha = 0.8; ctx.fill(built.districts[i]);       // soft edge: wide faint strokes of the same tint feather the outline
      const feather = [260, 160, 80];
      for (let j = 0; j < feather.length; j++) { ctx.globalAlpha = 0.1; ctx.lineWidth = feather[j]; ctx.stroke(built.districts[i]); }
      ctx.globalAlpha = 1;
    }
    ctx.fillStyle = p.park;
    for (let i = 0; i < built.parks.length; i++) ctx.fill(built.parks[i]);
    ctx.lineJoin = 'round';
    ctx.strokeStyle = p.shore; ctx.lineWidth = 26 / k; ctx.stroke(built.sea);       // light shallows along the coast
    ctx.fillStyle = p.sea;
    ctx.fill(built.sea);
    ctx.strokeStyle = p.bank; ctx.lineWidth = 12 / k; ctx.stroke(built.river);      // light banks of the Douro
    ctx.fillStyle = p.river;
    ctx.fill(built.river);
    ctx.lineCap = 'round';
    if (built.streets) {
      const S = built.streets, wpx = function (c) { return Math.max(STREET_PX[c][0] * k, STREET_PX[c][1]) / k; };
      if (k > 0.1) { ctx.strokeStyle = p.minor; ctx.lineWidth = wpx('minor'); ctx.stroke(S.minor); }
      ctx.strokeStyle = p.mid; ctx.lineWidth = wpx('mid'); ctx.stroke(S.mid);
      ctx.strokeStyle = p.casing; ctx.lineWidth = wpx('main') + 2.4 / k; ctx.stroke(S.main);   // arteries: lighter and wider, with a thin edge
      ctx.strokeStyle = p.main; ctx.lineWidth = wpx('main'); ctx.stroke(S.main);
    }
    ctx.lineCap = 'butt';
    ctx.strokeStyle = p.arch; ctx.lineWidth = 11 / k;               // dark casing under the light deck
    for (let i = 0; i < built.bridges.length; i++) ctx.stroke(built.bridges[i]);
    ctx.strokeStyle = p.bridge; ctx.lineWidth = 8 / k;
    for (let i = 0; i < built.bridges.length; i++) ctx.stroke(built.bridges[i]);
    ctx.strokeStyle = p.arch; ctx.lineWidth = 3 / k;
    for (let i = 0; i < built.arches.length; i++) ctx.stroke(built.arches[i]);
    ctx.restore();
    if (SHOW_BUILDINGS) drawBuildings(ctx, p, p === NIGHT, k, x0, y0);
    const f = Math.max(0, Math.min(1, (LABEL_FADE - k) / (LABEL_FADE - LABEL_LO)));
    if (f > 0) {
      ctx.save();
      ctx.globalAlpha = f;
      ctx.font = '800 12px Trebuchet MS, Helvetica Neue, system-ui, sans-serif';
      ctx.lineJoin = 'round'; ctx.lineWidth = 3.5; ctx.strokeStyle = p.halo;
      ctx.textAlign = 'center';
      ctx.fillStyle = p.text;
      for (let i = 0; i < B.districts.length; i++) {
        const d = B.districts[i];
        const tx = (d.ua || d.name).toUpperCase();
        ctx.strokeText(tx, x0 + d.x * k, y0 + d.y * k);
        ctx.fillText(tx, x0 + d.x * k, y0 + d.y * k);
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
