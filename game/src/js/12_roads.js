(function (root) {
  const PG = root.PG = root.PG || {};

  const CELL = 128;        // snap grid cell, metres
  const SNAP_MAX = 1500;   // farther than this from any edge: no route
  const EPS = 1e-6;

  const R = {
    enabled: false,
    route: route,
    pointAt: pointAt,
    stats: stats,
    load: load
  };
  PG.roads = R;

  // Graph, all in metres.
  let nNodes = 0, nEdges = 0, nSegs = 0;
  let nx = null, ny = null;              // node coordinates
  let ea = null, eb = null, elen = null; // edge end nodes and length
  let es = null;                         // edge e owns points es[e]..es[e+1]-1 (ends included)
  let px = null, py = null, pc = null;   // edge points and cumulative length along their edge
  let segEdge = null;                    // global segment g joins points g and g+1 (same edge)
  let adjStart = null, adjEdge = null, adjTo = null;
  let gx0 = 0, gy0 = 0, gw = 0, gh = 0, cellStart = null, cellSeg = null;
  // A* scratch
  let gs = null, stamp = null, parE = null, parN = null, closed = null, hp = null, hk = null, hn = 0, epoch = 0;
  let pathX = null, pathY = null;        // scratch for path assembly
  let nodeSeq = null;
  const sn0 = { e: 0, g: 0, x: 0, y: 0, d: 0, da: 0, db: 0 };
  const sn1 = { e: 0, g: 0, x: 0, y: 0, d: 0, da: 0, db: 0 };
  const st = { routes: 0, nulls: 0, totalMs: 0, maxMs: 0, expanded: 0 };

  function now() {
    return (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
  }

  function load(data) {
    R.enabled = false;
    if (!data || !data.nodes || !data.edges || data.nodes.length < 4 || !data.edges.length) return false;
    const u = data.unit_m || 1;
    nNodes = data.nodes.length >> 1;
    nEdges = data.edges.length;
    nx = new Float64Array(nNodes); ny = new Float64Array(nNodes);
    for (let i = 0; i < nNodes; i++) { nx[i] = data.nodes[2 * i] * u; ny[i] = data.nodes[2 * i + 1] * u; }
    let total = 0;
    for (let i = 0; i < nEdges; i++) total += 2 + ((data.edges[i][2] || []).length >> 1);
    ea = new Int32Array(nEdges); eb = new Int32Array(nEdges); elen = new Float64Array(nEdges);
    es = new Int32Array(nEdges + 1);
    px = new Float64Array(total); py = new Float64Array(total); pc = new Float64Array(total);
    segEdge = new Int32Array(total);
    let p = 0;
    for (let e = 0; e < nEdges; e++) {
      const ed = data.edges[e], mid = ed[2] || [];
      ea[e] = ed[0]; eb[e] = ed[1];
      es[e] = p;
      px[p] = nx[ed[0]]; py[p] = ny[ed[0]]; pc[p] = 0; p++;
      for (let i = 0; i + 1 < mid.length; i += 2) {
        px[p] = mid[i] * u; py[p] = mid[i + 1] * u;
        pc[p] = pc[p - 1] + Math.hypot(px[p] - px[p - 1], py[p] - py[p - 1]); p++;
      }
      px[p] = nx[ed[1]]; py[p] = ny[ed[1]];
      pc[p] = pc[p - 1] + Math.hypot(px[p] - px[p - 1], py[p] - py[p - 1]); p++;
      elen[e] = pc[p - 1];
      for (let q = es[e]; q < p - 1; q++) segEdge[q] = e;
      segEdge[p - 1] = -1; // last point of an edge starts no segment
    }
    es[nEdges] = p;
    nSegs = p;

    // adjacency (CSR)
    adjStart = new Int32Array(nNodes + 1);
    for (let e = 0; e < nEdges; e++) { adjStart[ea[e] + 1]++; adjStart[eb[e] + 1]++; }
    for (let i = 0; i < nNodes; i++) adjStart[i + 1] += adjStart[i];
    adjEdge = new Int32Array(2 * nEdges); adjTo = new Int32Array(2 * nEdges);
    const fill = adjStart.slice(0, nNodes);
    for (let e = 0; e < nEdges; e++) {
      adjEdge[fill[ea[e]]] = e; adjTo[fill[ea[e]]++] = eb[e];
      adjEdge[fill[eb[e]]] = e; adjTo[fill[eb[e]]++] = ea[e];
    }

    // snap grid over segments (bbox rasterised)
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    for (let i = 0; i < p; i++) {
      if (px[i] < minx) minx = px[i]; if (px[i] > maxx) maxx = px[i];
      if (py[i] < miny) miny = py[i]; if (py[i] > maxy) maxy = py[i];
    }
    gx0 = minx; gy0 = miny;
    gw = Math.floor((maxx - minx) / CELL) + 1; gh = Math.floor((maxy - miny) / CELL) + 1;
    const cnt = new Int32Array(gw * gh + 1);
    for (let pass = 0; pass < 2; pass++) {
      if (pass === 1) {
        for (let i = 0; i < gw * gh; i++) cnt[i + 1] += cnt[i];
        cellSeg = new Int32Array(cnt[gw * gh]);
        cellStart = cnt.slice();
      }
      const w = pass === 1 ? cellStart.slice(0, gw * gh) : null;
      for (let g = 0; g < p; g++) {
        if (segEdge[g] < 0) continue;
        const c0 = Math.floor((Math.min(px[g], px[g + 1]) - gx0) / CELL), c1 = Math.floor((Math.max(px[g], px[g + 1]) - gx0) / CELL);
        const r0 = Math.floor((Math.min(py[g], py[g + 1]) - gy0) / CELL), r1 = Math.floor((Math.max(py[g], py[g + 1]) - gy0) / CELL);
        for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) {
          const ci = r * gw + c;
          if (pass === 0) cnt[ci + 1]++; else cellSeg[w[ci]++] = g;
        }
      }
    }

    gs = new Float64Array(nNodes); stamp = new Int32Array(nNodes); closed = new Int32Array(nNodes);
    parE = new Int32Array(nNodes); parN = new Int32Array(nNodes);
    hp = new Float64Array(1024); hk = new Int32Array(1024); hn = 0; epoch = 0;
    pathX = new Float64Array(p + 8); pathY = new Float64Array(p + 8);
    nodeSeq = new Int32Array(nNodes + 2);
    R.enabled = true;
    return true;
  }

  // Nearest point of any edge segment within SNAP_MAX; fills s, returns false if none.
  function snap(x, y, s) {
    const cx = Math.floor((x - gx0) / CELL), cy = Math.floor((y - gy0) / CELL);
    const maxRing = Math.ceil(SNAP_MAX / CELL) + 1;
    let best = Infinity, bg = -1, bx = 0, by = 0;
    for (let ring = 0; ring <= maxRing; ring++) {
      if (ring > 0 && best <= (ring - 1) * CELL) break;
      for (let r = cy - ring; r <= cy + ring; r++) {
        if (r < 0 || r >= gh) continue;
        const edgeRow = (r === cy - ring || r === cy + ring);
        const step = edgeRow ? 1 : 2 * ring;
        for (let c = cx - ring; c <= cx + ring; c += (step || 1)) {
          if (c < 0 || c >= gw) continue;
          const ci = r * gw + c;
          for (let k = cellStart[ci]; k < cellStart[ci + 1]; k++) {
            const g = cellSeg[k];
            const ax = px[g], ay = py[g], dx = px[g + 1] - ax, dy = py[g + 1] - ay;
            const l2 = dx * dx + dy * dy;
            let t = l2 > 0 ? ((x - ax) * dx + (y - ay) * dy) / l2 : 0;
            t = t < 0 ? 0 : t > 1 ? 1 : t;
            const qx = ax + t * dx, qy = ay + t * dy;
            const d = Math.hypot(x - qx, y - qy);
            if (d < best) { best = d; bg = g; bx = qx; by = qy; }
          }
        }
      }
    }
    if (bg < 0 || best > SNAP_MAX) return false;
    const e = segEdge[bg];
    s.e = e; s.g = bg; s.x = bx; s.y = by; s.d = best;
    s.da = pc[bg] + Math.hypot(bx - px[bg], by - py[bg]);
    s.db = elen[e] - s.da;
    return true;
  }

  // binary min-heap on (key, node); lazy deletion
  function hpush(key, n) {
    if (hn === hp.length) {
      const a = new Float64Array(hn * 2); a.set(hp); hp = a;
      const b = new Int32Array(hn * 2); b.set(hk); hk = b;
    }
    let i = hn++;
    while (i > 0) {
      const par = (i - 1) >> 1;
      if (hp[par] <= key) break;
      hp[i] = hp[par]; hk[i] = hk[par]; i = par;
    }
    hp[i] = key; hk[i] = n;
  }
  let popKey = 0, popNode = 0;
  function hpop() {
    popKey = hp[0]; popNode = hk[0];
    hn--;
    if (hn > 0) {
      const key = hp[hn], n = hk[hn];
      let i = 0;
      for (;;) {
        let c = 2 * i + 1;
        if (c >= hn) break;
        if (c + 1 < hn && hp[c + 1] < hp[c]) c++;
        if (hp[c] >= key) break;
        hp[i] = hp[c]; hk[i] = hk[c]; i = c;
      }
      hp[i] = key; hk[i] = n;
    }
  }

  function relax(n, g, pe, pn, gxp, gyp) {
    if (stamp[n] === epoch && gs[n] <= g) return;
    stamp[n] = epoch; gs[n] = g; parE[n] = pe; parN[n] = pn;
    hpush(g + Math.hypot(nx[n] - gxp, ny[n] - gyp), n);
  }

  let outN = 0;
  function put(x, y) {
    if (outN > 0 && Math.abs(pathX[outN - 1] - x) < EPS && Math.abs(pathY[outN - 1] - y) < EPS) return;
    pathX[outN] = x; pathY[outN] = y; outN++;
  }
  // points of edge e from global point index i to j inclusive, in either direction
  function putRange(i, j) {
    if (i <= j) for (let q = i; q <= j; q++) put(px[q], py[q]);
    else for (let q = i; q >= j; q--) put(px[q], py[q]);
  }

  function route(x0, y0, x1, y1) {
    if (!R.enabled) return null;
    const t0 = now();
    st.routes++;
    const res = routeImpl(x0, y0, x1, y1);
    const ms = now() - t0;
    st.totalMs += ms; if (ms > st.maxMs) st.maxMs = ms;
    if (!res) st.nulls++;
    return res;
  }

  function routeImpl(x0, y0, x1, y1) {
    if (!snap(x0, y0, sn0) || !snap(x1, y1, sn1)) return null;
    const A = sn0, B = sn1;
    // direct option on the same edge
    let bestCost = Infinity, mode = 0; // 0 graph, 1 same-edge direct
    if (A.e === B.e) { bestCost = Math.abs(A.da - B.da); mode = 1; }

    epoch++;
    hn = 0;
    relax(ea[A.e], A.da, -1, -1, B.x, B.y);
    relax(eb[A.e], A.db, -1, -1, B.x, B.y);
    const ga = ea[B.e], gb = eb[B.e];
    let endNode = -1, endVia = 0; // endVia 0: leave through ga, 1: through gb
    let graphCost = Infinity;
    while (hn > 0) {
      hpop();
      const n = popNode, key = popKey;
      if (key >= Math.min(bestCost, graphCost)) break;
      if (closed[n] === epoch) continue;
      const g = gs[n];
      if (key > g + Math.hypot(nx[n] - B.x, ny[n] - B.y) + 1e-9) continue; // stale
      closed[n] = epoch;
      st.expanded++;
      if (n === ga) { const c = g + B.da; if (c < graphCost) { graphCost = c; endNode = n; endVia = 0; } }
      if (n === gb) { const c = g + B.db; if (c < graphCost) { graphCost = c; endNode = n; endVia = 1; } }
      for (let k = adjStart[n]; k < adjStart[n + 1]; k++) {
        const m = adjTo[k];
        if (closed[m] === epoch) continue;
        relax(m, g + elen[adjEdge[k]], adjEdge[k], n, B.x, B.y);
      }
    }
    if (graphCost < bestCost) { bestCost = graphCost; mode = 0; }
    if (bestCost === Infinity) return null;

    outN = 0;
    put(x0, y0);
    put(A.x, A.y);
    if (mode === 1) {
      // same edge: walk between the two snaps along the polyline
      if (A.g < B.g) putRange(A.g + 1, B.g); else if (A.g > B.g) putRange(A.g, B.g + 1);
    } else {
      // collect node chain end -> start
      let cnt = 0, n = endNode;
      while (n >= 0) { nodeSeq[cnt++] = n; n = (stamp[n] === epoch) ? parN[n] : -1; }
      // start edge piece up to first node (chain is reversed: last = first node)
      const first = nodeSeq[cnt - 1];
      if (first === ea[A.e]) putRange(A.g, es[A.e]); else putRange(A.g + 1, es[A.e + 1] - 1);
      for (let i = cnt - 1; i > 0; i--) {
        const u = nodeSeq[i], v = nodeSeq[i - 1], e = parE[v];
        if (ea[e] === u) putRange(es[e], es[e + 1] - 1); else putRange(es[e + 1] - 1, es[e]);
      }
      if (endVia === 0) putRange(es[B.e], B.g); else putRange(es[B.e + 1] - 1, B.g + 1);
    }
    put(B.x, B.y);
    put(x1, y1);
    if (outN < 2) { pathX[outN] = x1; pathY[outN] = y1; outN++; }

    const n = outN;
    const xs = new Float64Array(n), ys = new Float64Array(n), cum = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      xs[i] = pathX[i]; ys[i] = pathY[i];
      if (i > 0) cum[i] = cum[i - 1] + Math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]);
    }
    return { xs: xs, ys: ys, n: n, len: cum[n - 1], cum: cum };
  }

  // Position at fraction f (0..1) of the path length; k = segment index, (hx, hy) = unit heading.
  function pointAt(path, f, out) {
    const n = path.n, cum = path.cum;
    f = f < 0 ? 0 : f > 1 ? 1 : f;
    const d = f * path.len;
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (cum[mid] <= d) lo = mid; else hi = mid;
    }
    // skip zero-length segments for a usable heading
    let k = lo;
    const dx = path.xs[k + 1] - path.xs[k], dy = path.ys[k + 1] - path.ys[k];
    const sl = cum[k + 1] - cum[k];
    const t = sl > 0 ? (d - cum[k]) / sl : 0;
    out.x = path.xs[k] + t * dx;
    out.y = path.ys[k] + t * dy;
    out.k = k;
    if (sl > 0) { out.hx = dx / sl; out.hy = dy / sl; } else { out.hx = 1; out.hy = 0; }
    return out;
  }

  function stats() {
    return {
      enabled: R.enabled, nodes: nNodes, edges: nEdges, points: nSegs,
      routes: st.routes, nulls: st.nulls, expanded: st.expanded,
      avgMs: st.routes ? st.totalMs / st.routes : 0, maxMs: st.maxMs
    };
  }

  let data = PG.ROADS;
  if (!data && typeof document !== 'undefined') {
    const el = document.getElementById('roads-data');
    if (el) { try { data = JSON.parse(el.textContent); } catch (e) { data = null; } }
  }
  if (data) load(data);
})(typeof window !== 'undefined' ? window : globalThis);
