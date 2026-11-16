/* 10_data.js: PG.data, the game data of CONTRACT §4 turned into the JS shapes of §10 (metres, typed arrays). */
(function (root) {
  const PG = root.PG = root.PG || {};

  const RIDE_STEP = 15; // seconds between two GPS points of a ride (§4)

  /** Reads the raw game data: PG.DATA, else the #game-data script (the one DOM access of the core, §8). */
  function readRaw() {
    if (PG.DATA) return PG.DATA;
    if (typeof document !== 'undefined' && document.getElementById) {
      const el = document.getElementById('game-data');
      if (el && el.textContent) return JSON.parse(el.textContent);
    }
    return null;
  }

  /** Turns one compact order array into an order object (metres). */
  function buildOrder(a, i, u) {
    const x0 = a[1], y0 = a[2];
    const d = a[5];
    const n = (d.length >> 1) + 1;
    const xs = new Float32Array(n);
    const ys = new Float32Array(n);
    const tRel = new Float32Array(n);
    let cx = x0, cy = y0;
    xs[0] = cx * u; ys[0] = cy * u; tRel[0] = 0;
    for (let k = 1; k < n; k++) {
      cx += d[2 * k - 2]; cy += d[2 * k - 1];
      xs[k] = cx * u; ys[k] = cy * u; tRel[k] = RIDE_STEP * k;
    }
    return {
      i: i, t: a[0], x0: x0 * u, y0: y0 * u, x1: a[3] * u, y1: a[4] * u,
      pts: { xs: xs, ys: ys, tRel: tRel, n: n },
      d: a[6] > 0 ? a[6] : RIDE_STEP * (n - 1), km: a[7], fare: a[8], c: a[9], stand: a[10], taxi: a[11]
    };
  }

  /** Builds one shift object of §10 from the raw shift. */
  function buildShift(r, u) {
    const orders = new Array(r.orders.length);
    for (let i = 0; i < orders.length; i++) orders[i] = buildOrder(r.orders[i], i, u);
    const ghostOrders = [];
    const gi = r.ghost && r.ghost.orders ? r.ghost.orders : [];
    for (let k = 0; k < gi.length; k++) ghostOrders.push(orders[gi[k]]);
    const ranking = r.ranking;
    const gTotal = ranking.length ? ranking[0] : 0;
    const sh = {
      id: r.id, name: r.name, day: r.day, slot: r.slot, startLocal: r.start_local, startHour: r.start_hour,
      difficulty: r.difficulty, nDrivers: r.nDrivers, taxis: r.taxis, ranking: ranking,
      median: r.median, top10: r.top10, speedByHour: r.speed_by_hour, detour: r.detour,
      hotM: (r.hot || []).map(function (h) { return { x: h.x * u, y: h.y * u, w: h.w, name: h.name }; }),
      surgesM: (r.surges || []).map(function (s) {
        return { x: s.x * u, y: s.y * u, r: s.r * u, t0: s.t0, t1: s.t1, n: s.n, name: s.name };
      }),
      orders: orders, ghostOrders: ghostOrders,
      ghost: { taxi: r.ghost ? r.ghost.taxi : 0, total: gTotal },
      thr: { median: r.median, top10: r.top10, ghost: gTotal, legend: 1.25 * gTotal },
      _gh: null
    };
    return sh;
  }

  /** Writes the unit heading (dx, dy) into out, or keeps the old heading when the segment is a point. */
  function setHeading(out, dx, dy) {
    const l = Math.sqrt(dx * dx + dy * dy);
    if (l > 1e-6) { out.hx = dx / l; out.hy = dy / l; }
    else if (!(Math.abs(out.hx) + Math.abs(out.hy) > 0)) { out.hx = 0; out.hy = -1; }
    return out;
  }

  /** Position and heading on an order's route `f` seconds after pickup (clamped); writes into out. */
  function ridePos(o, f, out) {
    const p = o.pts, n = p.n;
    if (n < 2) { out.x = o.x0; out.y = o.y0; return setHeading(out, 0, 0); }
    if (f <= 0) f = 0;
    let i = Math.floor(f / RIDE_STEP);
    if (i > n - 2) i = n - 2;
    let fr = (f - p.tRel[i]) / RIDE_STEP;
    if (fr > 1) fr = 1;
    const ax = p.xs[i], ay = p.ys[i], bx = p.xs[i + 1], by = p.ys[i + 1];
    out.x = ax + (bx - ax) * fr;
    out.y = ay + (by - ay) * fr;
    if (bx === ax && by === ay) {
      // look for the next moving segment so a stop does not flip the heading
      for (let j = i + 1; j < n - 1; j++) {
        if (p.xs[j + 1] !== p.xs[j] || p.ys[j + 1] !== p.ys[j]) return setHeading(out, p.xs[j + 1] - p.xs[j], p.ys[j + 1] - p.ys[j]);
      }
    }
    return setHeading(out, bx - ax, by - ay);
  }

  /** Per-shift ghost schedule: ride start/end times, cumulative money, cached gap paths. */
  function ghostPlan(sh) {
    if (sh._gh) return sh._gh;
    const go = sh.ghostOrders, n = go.length;
    const t = new Float64Array(n), cum = new Float64Array(n);
    let sum = 0;
    for (let k = 0; k < n; k++) {
      t[k] = go[k].t;
      sum = Math.round((sum + go[k].fare) * 100) / 100;
      cum[k] = sum;
    }
    sh._gh = { t: t, cum: cum, n: n, gapPath: new Array(n), gapState: new Uint8Array(n), gapDepart: new Float64Array(n).fill(NaN) };
    return sh._gh;
  }

  /** Index of the last ghost order with t <= tt, or -1. */
  function lastIdx(g, tt) {
    let lo = 0, hi = g.n - 1, k = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (g.t[mid] <= tt + 1e-9) { k = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return k;
  }

  /** Speed (km/h) of the shift at game second t. */
  function speedAt(sh, t) {
    const h = (sh.startHour + Math.floor(t / 3600)) % 24;
    return sh.speedByHour[h];
  }

  /** Ghost position between ride k and ride k + 1: waits, then drives so as to arrive exactly at the next pickup. */
  function gapPos(sh, g, k, tt, out) {
    const a = sh.ghostOrders[k], b = sh.ghostOrders[k + 1];
    const tEnd = a.t + a.d;
    if (isNaN(g.gapDepart[k])) {
      const dist = Math.hypot(b.x0 - a.x1, b.y0 - a.y1);
      const drive = dist / 1000 * sh.detour / speedAt(sh, tEnd) * 3600;
      g.gapDepart[k] = Math.max(tEnd, b.t - drive);
    }
    const dep = g.gapDepart[k];
    const roadsOn = !!(PG.roads && PG.roads.enabled);
    if (roadsOn && g.gapState[k] < 2) {
      g.gapPath[k] = PG.roads.route(a.x1, a.y1, b.x0, b.y0) || null;
      g.gapState[k] = 2;
    } else if (g.gapState[k] === 0) {
      g.gapPath[k] = null; g.gapState[k] = 1;
    }
    let f = (tt - dep) / (b.t - dep);
    if (!(f > 0)) f = 0; else if (f > 1) f = 1;
    const path = g.gapPath[k];
    if (path && roadsOn) {
      const r = PG.roads.pointAt(path, f, out);
      if (r !== out) { out.x = r.x; out.y = r.y; out.hx = r.hx; out.hy = r.hy; }
      return out;
    }
    out.x = a.x1 + (b.x0 - a.x1) * f;
    out.y = a.y1 + (b.y0 - a.y1) * f;
    return setHeading(out, b.x0 - a.x1, b.y0 - a.y1);
  }

  /** Where the ghost (best real driver of the shift) is at game second t; no allocation. */
  function ghostAt(sh, t, out) {
    const g = ghostPlan(sh), go = sh.ghostOrders;
    if (g.n === 0) {
      const hm = PG.C && PG.C.HOME ? PG.C.HOME : { x: 9110, y: 12443 };
      out.x = hm.x; out.y = hm.y;
      return setHeading(out, 0, 0);
    }
    const k = lastIdx(g, t);
    if (k < 0) {
      const o = go[0];
      out.x = o.x0; out.y = o.y0;
      ridePos(o, 0, out);
      return out;
    }
    const o = go[k], f = t - o.t;
    if (f < o.d) return ridePos(o, f, out);
    if (k === g.n - 1) return ridePos(o, o.d, out);
    return gapPos(sh, g, k, t, out);
  }

  /** Money (€) the ghost has earned by game second t (pickups with o.t <= t). */
  function ghostMoney(sh, t) {
    const g = ghostPlan(sh);
    const k = lastIdx(g, t);
    return k < 0 ? 0 : g.cum[k];
  }

  const raw = readRaw();
  const u = raw ? raw.unit_m : 5;
  const b = raw ? raw.bounds : [0, 0, 0, 0];
  PG.data = {
    version: raw ? raw.version : 0,
    unitM: u,
    bounds: [b[0] * u, b[1] * u, b[2] * u, b[3] * u],
    shifts: raw ? raw.shifts.map(function (r) { return buildShift(r, u); }) : [],
    ghostAt: ghostAt,
    ghostMoney: ghostMoney,
    ridePos: ridePos
  };
})(typeof window !== 'undefined' ? window : globalThis);
