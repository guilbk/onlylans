// Node test for game/src/js/12_roads.js. Usage: node tools/roads_test.mjs [--roads PATH]
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(here, '..', 'game', 'src', 'js', '12_roads.js'), 'utf8');
const args = process.argv.slice(2);
const ri = args.indexOf('--roads');
const roadsPath = ri >= 0 ? args[ri + 1] : null;

let fails = 0, checks = 0;
function ok(cond, msg) { checks++; if (!cond) { fails++; console.log('FAIL: ' + msg); } }
function near(a, b, tol, msg) { ok(Math.abs(a - b) <= tol, `${msg}: got ${a}, want ${b}`); }

function loadRoads(json) {
  globalThis.PG = { ROADS: json };
  vm.runInThisContext(src, { filename: '12_roads.js' });
  return globalThis.PG.roads;
}

// deterministic rng
function rng(seed) {
  let s = seed >>> 0;
  return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

// ---- 1. synthetic 3x3 grid, spacing 1000 m = 400 units (unit_m 2.5) ----
{
  const S = 400, nodes = [];
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) nodes.push(c * S, r * S);
  const edges = [];
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) {
    const i = r * 3 + c;
    if (c < 2) edges.push([i, i + 1, []]);
    if (r < 2) edges.push([i, i + 3, []]);
  }
  // make edge 0-1 curved: interior point bulging 200 m (80 units) south
  edges[0][2] = [S / 2, 80];
  const R = loadRoads({ v: 1, unit_m: 2.5, nodes, edges });
  ok(R.enabled, 'grid enabled');
  // node to node, opposite corners: Manhattan 4000 m, but the 0-1 edge is curved (longer)
  const curved = 2 * Math.hypot(500, 200);
  let p = R.route(0, 0, 2000, 2000);
  ok(p && p.n >= 2, 'corner route exists');
  near(p.len, Math.min(4000 + curved - 1000, 4000), 1e-6, 'corner len picks the straight way');
  near(p.len, 4000, 1e-6, 'corner len = 4000');
  ok(p.xs[0] === 0 && p.ys[0] === 0 && p.xs[p.n - 1] === 2000 && p.ys[p.n - 1] === 2000, 'ends exact');
  // along the curved edge only
  p = R.route(0, 0, 1000, 0);
  near(p.len, Math.min(curved, 3000), 1e-6, 'curved edge or detour');
  ok(Math.abs(p.len - curved) < 1e-6 && p.len < 3000, 'takes the curved edge (' + p.len.toFixed(1) + ')');
  // snap: off-road points add the connector
  p = R.route(300, 40, 1700, 1040); // 40 m off the bottom... y=40 is off edge y=0 by 40; x=1700,y=1040 off by 40 from y=1000
  ok(p !== null, 'snapped route exists');
  ok(p.xs[0] === 300 && p.ys[0] === 40, 'starts at query point');
  ok(p.xs[p.n - 1] === 1700 && p.ys[p.n - 1] === 1040, 'ends at query point');
  // same-edge route: straight along edge 3-4 (y=1000)
  p = R.route(1200, 1000, 1700, 1000);
  near(p.len, 500, 1e-6, 'same-edge len');
  // same point
  p = R.route(1000, 1000, 1000, 1000);
  ok(p && p.len === 0, 'zero route');
  // too far
  ok(R.route(0, 0, 2000 + 1600, 0) === null, 'null when far from any road');
  ok(R.route(-1600, -1600, 1000, 1000) === null, 'null when start far');
  ok(R.route(0, 0, 2000 + 1400, 0) !== null, 'ok at 1400 m');
  // pointAt
  p = R.route(0, 1000, 2000, 1000); // straight along y=1000
  const out = { x: 0, y: 0, k: 0, hx: 0, hy: 0 };
  R.pointAt(p, 0, out); ok(out.x === 0 && out.y === 1000, 'pointAt 0');
  R.pointAt(p, 0.25, out); near(out.x, 500, 1e-9, 'pointAt .25 x'); near(out.hx, 1, 1e-9, 'heading x'); near(out.hy, 0, 1e-9, 'heading y');
  R.pointAt(p, 1, out); near(out.x, 2000, 1e-9, 'pointAt 1');
  R.pointAt(p, 1.5, out); near(out.x, 2000, 1e-9, 'pointAt clamp');
  // pointAt walks the whole path monotonically
  p = R.route(0, 0, 2000, 2000);
  let prev = 0, tot = 0;
  for (let i = 1; i <= 100; i++) {
    const ox = out.x, oy = out.y;
    R.pointAt(p, i / 100, out);
    if (i > 1) tot += Math.hypot(out.x - ox, out.y - oy);
    prev = out.k;
  }
  ok(tot <= p.len + 1e-6 && tot > p.len * 0.9, 'pointAt samples cover the path');
  const s = R.stats();
  ok(s.nodes === 9 && s.edges === 12, 'stats counts');
  // no data: disabled
  globalThis.PG = {};
  vm.runInThisContext(src, { filename: '12_roads.js' });
  ok(globalThis.PG.roads.enabled === false && globalThis.PG.roads.route(0, 0, 1, 1) === null, 'disabled without data');
}

// ---- 2. build a ~2000-node random street grid, check vs Dijkstra, time routes ----
function bigGrid(W, H, seed) {
  const rnd = rng(seed), U = 2.5, SP = 120 / U; // 120 m blocks
  const id = (c, r) => r * W + c, nodes = [];
  for (let r = 0; r < H; r++) for (let c = 0; c < W; c++)
    nodes.push(Math.round(c * SP + (rnd() - 0.5) * SP * 0.4), Math.round(r * SP + (rnd() - 0.5) * SP * 0.4));
  const cand = [];
  for (let r = 0; r < H; r++) for (let c = 0; c < W; c++) {
    if (c + 1 < W) cand.push([id(c, r), id(c + 1, r)]);
    if (r + 1 < H) cand.push([id(c, r), id(c, r + 1)]);
  }
  for (let i = cand.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [cand[i], cand[j]] = [cand[j], cand[i]]; }
  const par = Array.from({ length: W * H }, (_, i) => i);
  const find = (a) => { while (par[a] !== a) { par[a] = par[par[a]]; a = par[a]; } return a; };
  const edges = [];
  for (const [a, b] of cand) {
    const ra = find(a), rb = find(b), keep = ra !== rb || rnd() < 0.6; // spanning tree + 60% of the rest
    if (!keep) continue;
    if (ra !== rb) par[ra] = rb;
    const mid = [];
    if (rnd() < 0.5) { // one wiggle point
      mid.push(Math.round((nodes[2 * a] + nodes[2 * b]) / 2 + (rnd() - 0.5) * 10), Math.round((nodes[2 * a + 1] + nodes[2 * b + 1]) / 2 + (rnd() - 0.5) * 10));
    }
    edges.push(a < b ? [a, b, mid] : [b, a, mid.length ? mid : mid]);
  }
  edges.sort((p, q) => p[0] - q[0] || p[1] - q[1]);
  return { v: 1, unit_m: U, nodes, edges };
}

function dijkstraAll(json, src0) {
  const n = json.nodes.length / 2, U = json.unit_m, adj = Array.from({ length: n }, () => []);
  const poly = (e) => { const a = e[0], b = e[1], pts = [[json.nodes[2 * a] * U, json.nodes[2 * a + 1] * U]]; for (let i = 0; i < e[2].length; i += 2) pts.push([e[2][i] * U, e[2][i + 1] * U]); pts.push([json.nodes[2 * b] * U, json.nodes[2 * b + 1] * U]); return pts; };
  for (const e of json.edges) {
    const pts = poly(e); let l = 0;
    for (let i = 1; i < pts.length; i++) l += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    adj[e[0]].push([e[1], l]); adj[e[1]].push([e[0], l]);
  }
  const d = new Float64Array(n).fill(Infinity), done = new Uint8Array(n); d[src0] = 0;
  for (let it = 0; it < n; it++) {
    let u = -1, bd = Infinity;
    for (let i = 0; i < n; i++) if (!done[i] && d[i] < bd) { bd = d[i]; u = i; }
    if (u < 0) break; done[u] = 1;
    for (const [v, l] of adj[u]) if (d[u] + l < d[v]) d[v] = d[u] + l;
  }
  return d;
}

function timeRoutes(R, bounds, nodesM, count, seed, label) {
  const rnd = rng(seed);
  let worst = 0, sum = 0, nulls = 0, bad = 0;
  for (let i = 0; i < 100; i++) { // warm-up
    const a = Math.floor(rnd() * nodesM.length / 2) * 2, b = Math.floor(rnd() * nodesM.length / 2) * 2;
    R.route(nodesM[a] + 30, nodesM[a + 1] - 20, nodesM[b] - 25, nodesM[b + 1] + 10);
  }
  for (let i = 0; i < count; i++) {
    const a = Math.floor(rnd() * nodesM.length / 2) * 2, b = Math.floor(rnd() * nodesM.length / 2) * 2;
    const x0 = nodesM[a] + (rnd() - 0.5) * 200, y0 = nodesM[a + 1] + (rnd() - 0.5) * 200;
    const x1 = nodesM[b] + (rnd() - 0.5) * 200, y1 = nodesM[b + 1] + (rnd() - 0.5) * 200;
    const t = process.hrtime.bigint();
    const p = R.route(x0, y0, x1, y1);
    const ms = Number(process.hrtime.bigint() - t) / 1e6;
    sum += ms; if (ms > worst) worst = ms;
    if (!p) { nulls++; continue; }
    if (p.len + 1e-6 < Math.hypot(x1 - x0, y1 - y0)) bad++;
    if (ms >= 2) bad++;
  }
  console.log(`${label}: ${count} routes, avg ${(sum / count).toFixed(3)} ms, max ${worst.toFixed(3)} ms, nulls ${nulls}`);
  ok(nulls === 0, label + ': none null');
  ok(worst < 2, label + `: each route < 2 ms (max ${worst.toFixed(3)})`);
  ok(bad === 0, label + ': path never shorter than straight line, none slow');
}

{
  const json = bigGrid(46, 44, 11); // 2024 nodes
  const R = loadRoads(json);
  ok(R.enabled, 'big enabled');
  const U = json.unit_m, nodesM = json.nodes.map((v) => v * U);
  // correctness: node-to-node routes equal Dijkstra distances (query exactly on nodes)
  const rnd = rng(5);
  for (let t = 0; t < 8; t++) {
    const a = Math.floor(rnd() * (json.nodes.length / 2));
    const d = dijkstraAll(json, a);
    for (let k = 0; k < 15; k++) {
      const b = Math.floor(rnd() * (json.nodes.length / 2));
      const p = R.route(nodesM[2 * a], nodesM[2 * a + 1], nodesM[2 * b], nodesM[2 * b + 1]);
      ok(p !== null, 'node route exists');
      if (p) near(p.len, d[b], 1e-6, `A* = Dijkstra (${a}->${b})`);
    }
  }
  timeRoutes(R, null, nodesM, 1000, 21, 'synthetic 2000-node grid');
  const s = R.stats(); ok(s.nodes === 2024, 'big stats nodes');
}

// ---- 3. optional real roads.json ----
if (roadsPath) {
  const json = JSON.parse(fs.readFileSync(roadsPath, 'utf8'));
  const R = loadRoads(json);
  ok(R.enabled, 'real roads enabled');
  const U = json.unit_m, nodesM = json.nodes.map((v) => v * U);
  console.log('real roads:', JSON.stringify(R.stats()));
  timeRoutes(R, null, nodesM, 1000, 33, 'real roads');
}

console.log(`${checks - fails}/${checks} checks passed`);
process.exit(fails ? 1 : 0);
