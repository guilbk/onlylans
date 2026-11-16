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
  let built = null;

  function isNight() {
    if (PG.theme === 'night') return true;
    if (PG.theme === 'day') return false;
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
