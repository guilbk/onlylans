// Street map: a real city map of Porto built from our own road graph (pipeline/streetmap.py).
// Light ground (day) / navy (night), streets with a casing and a fill, width by class and zoom.
// The basemap (39: river, parks, districts, bridges) and the landmarks (42) stay above the ground.
(function (root) {
  const PG = root.PG = root.PG || {};
  const DAY = {
    ground: '#efe8da',
    casing: ['#d9a63a', '#cdbb90', '#d9d0bd'],
    fill: ['#ffd96a', '#fff1c9', '#fffdf6'],
  };
  const NIGHT = {
    ground: '#0d1631',
    casing: ['#4d3612', '#101a3b', '#0a1230'],
    fill: ['#e7a93d', '#4a5f9e', '#2f3f78'],
  };
  const WIDTH_M = [18, 11, 6];          // street width in metres per class: main, avenue, street
  const MIN_PX = [3, 2, 1], MAX_PX = [10, 6, 3.5];
  let built = null;

  function night() {
    const t = PG.theme && PG.theme.pal;
    return !t || t.name !== 'day';
  }

  function build(S) {      // once: Path2D per class in world metres, a frame allocates nothing
    const u = S.unit_m;
    return S.classes.map(function (polys) {
      const p = new Path2D();
      for (let i = 0; i < polys.length; i++) {
        const f = polys[i];
        p.moveTo(f[0] * u, f[1] * u);
        for (let j = 2; j < f.length; j += 2) p.lineTo(f[j] * u, f[j + 1] * u);
      }
      return p;
    });
  }

  function draw(ctx) {
    const R = PG.render;
    if (!built || !R || !R.P) return;
    const p = night() ? NIGHT : DAY;
    ctx.fillStyle = p.ground;
    ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    const a = R.P(0, 0), x0 = a.x, y0 = a.y;           // P returns one shared object
    const k = Math.abs(R.P(100, 0).x - x0) / 100;      // px per metre
    ctx.save();
    ctx.translate(x0, y0);
    ctx.scale(k, k);
    ctx.lineCap = ctx.lineJoin = 'round';
    for (let c = 2; c >= 0; c--) {                      // streets first, main roads on top
      const w = Math.max(MIN_PX[c], Math.min(MAX_PX[c], WIDTH_M[c] * k)) / k;
      const cas = Math.max(1, Math.min(2.5, w * k * 0.28)) / k;
      ctx.strokeStyle = p.casing[c];
      ctx.lineWidth = w + 2 * cas;
      ctx.stroke(built[c]);
      ctx.strokeStyle = p.fill[c];
      ctx.lineWidth = w;
      ctx.stroke(built[c]);
    }
    ctx.restore();
  }

  function register(tries) {
    const R = PG.render;
    if (R && R.onDraw) {
      R.onDraw(function (ctx) {
        draw(ctx);
      }, -6);
      R.ground = false;               // the old ground tile and street glow are covered by this map
    } else if (tries > 0) {
      setTimeout(function () { register(tries - 1); }, 0);
    }
  }

  const el = root.document && root.document.getElementById('streetmap-data');
  if (el && typeof Path2D !== 'undefined') {
    try {
      PG.streetmap = JSON.parse(el.textContent);
      built = build(PG.streetmap);
      register(50);
    } catch (e) { built = null; }
  }
})(typeof window !== 'undefined' ? window : globalThis);
