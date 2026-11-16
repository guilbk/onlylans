// Invented rush-hour jams (rules from pipeline/traffic.py, data in 43_traffic_data.js, same every day).
// PG.traffic.mul(x, y, tod): speed factor 0.5..1 at a point; leg(x0, y0, x1, y1, tod): the same along a straight
// leg (harmonic mean, i.e. the real time cost). tod = seconds since midnight. Draws the jams above the streets.
(function (root) {
  const PG = root.PG = root.PG || {};
  const D = PG.trafficData;
  if (!D) return;
  const CELL = 40;                         // metres per lookup cell
  const HIT_M = 28;                        // a street counts as jammed this close to its line
  const SAMPLE_M = 150;                    // spacing of the samples along a leg
  const MAX_SAMPLES = 40;
  const DASH_SPEED = 14;                   // metres per second the dashes crawl
  const COL = {
    day: { 1: 'rgba(240,170,20,0.45)', 2: 'rgba(214,40,52,0.45)', dash: 'rgba(255,255,255,0.4)' },
    night: { 1: 'rgba(255,196,60,0.5)', 2: 'rgba(255,72,88,0.5)', dash: 'rgba(255,255,255,0.45)' },
  };
  const cells = new Map();                 // cell key -> [[segment, ...]]
  const paths = [];                        // [window][level] -> Path2D
  let built = false;

  function key(cx, cy) { return cx * 4096 + cy; }

  function mark(si) {
    const p = D.segs[si].p, r = Math.ceil(HIT_M / CELL);
    for (let i = 0; i + 3 < p.length; i += 2) {
      const dx = p[i + 2] - p[i], dy = p[i + 3] - p[i + 1], n = Math.max(1, Math.ceil(Math.hypot(dx, dy) / (CELL / 2)));
      for (let k = 0; k <= n; k++) {
        const x = p[i] + dx * k / n, y = p[i + 1] + dy * k / n, cx = Math.floor(x / CELL), cy = Math.floor(y / CELL);
        for (let a = -r; a <= r; a++) for (let b = -r; b <= r; b++) {
          const q = key(cx + a, cy + b);
          let list = cells.get(q);
          if (!list) cells.set(q, list = []);
          if (list.indexOf(si) < 0) list.push(si);
        }
      }
    }
  }

  function dist(si, x, y) {
    const p = D.segs[si].p;
    let best = Infinity;
    for (let i = 0; i + 3 < p.length; i += 2) {
      const dx = p[i + 2] - p[i], dy = p[i + 3] - p[i + 1], L = dx * dx + dy * dy;
      const t = L ? Math.max(0, Math.min(1, ((x - p[i]) * dx + (y - p[i + 1]) * dy) / L)) : 0;
      best = Math.min(best, Math.hypot(x - p[i] - t * dx, y - p[i + 1] - t * dy));
    }
    return best;
  }

  function strength(w, tod) {            // 0..1: how far window w has ramped in at time of day tod
    const s = D.windows[w][0] * 3600, e = D.windows[w][1] * 3600, t = ((tod % 86400) + 86400) % 86400;
    if (t < s || t >= e) return 0;
    return Math.min(1, (t - s) / D.ramp[0], (e - t) / D.ramp[1] + 0.0001);
  }

  function init() {
    if (built) return;
    built = true;
    for (let i = 0; i < D.segs.length; i++) mark(i);
  }

  function mul(x, y, tod) {
    init();
    const list = cells.get(key(Math.floor(x / CELL), Math.floor(y / CELL)));
    if (!list) return 1;
    let m = 1;
    for (let w = 0; w < D.windows.length; w++) {
      const f = strength(w, tod);
      if (f <= 0) continue;
      for (let j = 0; j < list.length; j++) {
        const lv = D.segs[list[j]].l[w];
        if (!lv || dist(list[j], x, y) > HIT_M) continue;
        m = Math.min(m, 1 - (1 - D.mul[lv]) * f);
      }
    }
    return m;
  }

  function leg(x0, y0, x1, y1, tod) {
    const n = Math.min(MAX_SAMPLES, Math.max(1, Math.round(Math.hypot(x1 - x0, y1 - y0) / SAMPLE_M)));
    let inv = 0;
    for (let i = 0; i < n; i++) {
      const f = (i + 0.5) / n;
      inv += 1 / mul(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, tod);
    }
    return n / inv;
  }

  function buildPaths() {
    for (let w = 0; w < D.windows.length; w++) {
      paths[w] = { 1: new Path2D(), 2: new Path2D() };
      for (let i = 0; i < D.segs.length; i++) {
        const lv = D.segs[i].l[w];
        if (!lv) continue;
        const p = D.segs[i].p, q = paths[w][lv];
        q.moveTo(p[0], p[1]);
        for (let j = 2; j < p.length; j += 2) q.lineTo(p[j], p[j + 1]);
      }
    }
  }

  function draw(ctx, now) {
    const G = PG.engine && PG.engine.G, R = PG.render;
    if (!G || !G.sh || !R || !R.P || typeof Path2D === 'undefined') return;
    const tod = G.sh.startHour * 3600 + (G.t || 0);
    let any = false;
    for (let w = 0; w < D.windows.length; w++) if (strength(w, tod) > 0) any = true;
    if (!any) return;
    if (!paths.length) buildPaths();
    const night = PG.theme && PG.theme.name === 'night', c = night ? COL.night : COL.day;
    const a = R.P(0, 0), ax = a.x, ay = a.y, k = Math.abs(R.P(100, 0).x - ax) / 100, width = Math.max(15 * k, 3.2) / k;
    ctx.save();
    ctx.translate(ax, ay);
    ctx.scale(k, k);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    const crawl = PG.REDUCED ? 0 : -(now / 1000) * DASH_SPEED;
    for (let w = 0; w < D.windows.length; w++) {
      const f = strength(w, tod);
      if (f <= 0) continue;
      for (let lv = 1; lv <= 2; lv++) {
        ctx.globalAlpha = 0.25 + 0.75 * f;
        ctx.strokeStyle = c[lv]; ctx.lineWidth = width; ctx.setLineDash([]);
        ctx.stroke(paths[w][lv]);
        ctx.globalAlpha = f;                       // short dashes crawl slowly along the street
        ctx.strokeStyle = c.dash; ctx.lineWidth = width * 0.22;
        ctx.setLineDash([width * 0.9, width * 2.2]); ctx.lineDashOffset = crawl;
        ctx.stroke(paths[w][lv]);
      }
    }
    ctx.restore();
  }

  PG.traffic = { mul: mul, leg: leg };
  (function register(tries) {
    const R = PG.render;
    if (R && R.onDraw) R.onDraw(draw, -3);
    else if (tries > 0) setTimeout(function () { register(tries - 1); }, 0);
  })(50);
})(typeof window !== 'undefined' ? window : globalThis);
