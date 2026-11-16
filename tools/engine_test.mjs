// Node test of the engine (CONTRACT §8 "Node tests", §11): node tools/engine_test.mjs [--data PATH]
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const argv = process.argv.slice(2);
const di = argv.indexOf('--data');
const dataPath = path.resolve(root, di >= 0 ? argv[di + 1] : 'game/fixture/mini.json');
const ri = argv.indexOf('--roads');
const roadsPath = ri >= 0 ? path.resolve(root, argv[ri + 1]) : null;

globalThis.PG = { DATA: JSON.parse(fs.readFileSync(dataPath, 'utf8')) };
if (roadsPath && fs.existsSync(roadsPath)) globalThis.PG.ROADS = JSON.parse(fs.readFileSync(roadsPath, 'utf8'));

const jsDir = path.join(root, 'game', 'src', 'js');
const wanted = ['00_core', '10_data', '12_roads', '20_engine', '22_rules', '25_ai'];
for (const name of wanted) {
  const f = path.join(jsDir, name + '.js');
  if (!fs.existsSync(f)) { console.log('(skip ' + name + '.js: not present)'); continue; }
  vm.runInThisContext(fs.readFileSync(f, 'utf8'), { filename: f });
}
const PG = globalThis.PG;
const E = PG.engine;
const SHIFT = PG.C.SHIFT;

let failures = 0;
let checks = 0;
function check(cond, msg) {
  checks++;
  if (!cond) { failures++; console.log('FAIL: ' + msg); }
}
function near(a, b, tol) { return Math.abs(a - b) <= tol; }

// ---- helpers --------------------------------------------------------------
function newGame(idx, difficulty) {
  E.config.difficulty = difficulty || 'normal';
  return E.newGame(idx);
}

/** Runs `n` steps of size `size` with no input. */
function runNoInput(idx, size) {
  const G = newGame(idx);
  const n = Math.round(SHIFT / size);
  for (let i = 0; i < n && !G.over; i++) E.step(size);
  return G;
}

function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---- the greedy bot ---------------------------------------------------------
/** Best fare per second among reachable near pins; cruise to the nearest upcoming pin when idle. */
function botTick(rec) {
  const G = E.G, orders = G.sh.orders;
  const riding = G.mode === 'ride';
  if (G.mode === 'pickup' || (riding && G.next)) return;
  let best = null, bestScore = -1;
  for (let i = 0; i < orders.length; i++) {
    const o = orders[i];
    if (o.t < G.t) continue;
    if (o.t > G.t + 900) break;
    if (!E.reachable(o)) continue;
    const pv = E.preview(o);
    const score = o.fare / (pv.eta + o.d);
    if (score > bestScore) { bestScore = score; best = o; }
  }
  if (best) {
    const ok = riding ? E.bookNext(best) : E.startPickup(best);
    if (ok) rec.push({ t: G.t, kind: riding ? 'next' : 'pickup', i: best.i });
    return;
  }
  if (riding) return;
  let near = null, nd = Infinity;
  for (let i = 0; i < orders.length; i++) {
    const o = orders[i];
    if (o.t <= G.t) continue;
    if (o.t > G.t + 400) break;
    const d = Math.hypot(o.x0 - G.x, o.y0 - G.y);
    if (d < nd) { nd = d; near = o; }
  }
  if (near && nd > 200 && (G.mode === 'idle' || !G.leg || Math.hypot(G.leg.x1 - near.x0, G.leg.y1 - near.y0) > 50)) {
    if (E.cruiseTo(near.x0, near.y0)) rec.push({ t: G.t, kind: 'cruise', x: near.x0, y: near.y0 });
  }
}

function runBot(idx, rec, difficulty) {
  const G = newGame(idx, difficulty);
  for (let i = 0; i < 1000 && !G.over; i++) { botTick(rec); E.step(7.2); }
  return G;
}

// ---- tests ------------------------------------------------------------------
const nShifts = PG.data.shifts.length;
console.log('data: ' + dataPath + ', ' + nShifts + ' shifts');
check(nShifts > 0, 'data has shifts');

// (0) data checks
{
  const sh = PG.data.shifts[0];
  const o = sh.orders[0];
  check(o.pts.n >= 2 && o.pts.xs.length === o.pts.n && o.pts.tRel[1] === 15, 'order pts shape');
  check(near(o.pts.xs[o.pts.n - 1], o.x1, 0.01) && near(o.pts.ys[o.pts.n - 1], o.y1, 0.01), 'pts end at the drop-off');
  check(sh.ghostOrders.length === 0 || sh.ghostOrders[0] === sh.orders[sh.ghost.orders ? sh.ghost.orders[0] : sh.ghostOrders[0].i], 'ghost orders resolved');
  let ok = true;
  for (let s = 0; s < nShifts; s++) {
    const x = PG.data.shifts[s];
    const gm = PG.data.ghostMoney(x, SHIFT);
    if (!near(gm, x.thr.ghost, 0.011)) ok = false;
  }
  check(ok, 'ghostMoney at the end equals ranking[0] in every shift');
  // ghostAt arrives at every ghost pickup at o.t, and at the drop-off after the ride
  const out = { x: 0, y: 0, hx: 0, hy: 0 };
  let gok = true, hok = true;
  for (let s = 0; s < nShifts; s++) {
    const x = PG.data.shifts[s];
    for (const g of x.ghostOrders) {
      PG.data.ghostAt(x, g.t, out);
      if (Math.hypot(out.x - g.x0, out.y - g.y0) > 1) gok = false;
      PG.data.ghostAt(x, g.t + g.d, out);
      if (Math.hypot(out.x - g.x1, out.y - g.y1) > 1) gok = false;
      if (!near(Math.hypot(out.hx, out.hy), 1, 1e-3)) hok = false;
    }
  }
  check(gok, 'ghostAt is at the pickup at o.t and at the drop-off at the end of the ride');
  check(hok, 'ghostAt heading is a unit vector');
}

// (1) step-size check with no input
{
  const idx = 0;
  const a = runNoInput(idx, 720);
  const ra = { tot: a.tot, rank: a.rank, gm: a.ghostMoney, t: a.t, over: a.over, real: Array.from(a.real) };
  const b = runNoInput(idx, 7.2);
  check(ra.t === SHIFT && b.t === SHIFT, 'both runs end at ' + SHIFT + ' (' + ra.t + ', ' + b.t + ')');
  check(ra.over && b.over, 'both runs are over');
  check(ra.tot === b.tot, 'no input: same tot');
  check(ra.rank === b.rank, 'no input: same rank (' + ra.rank + ' vs ' + b.rank + ')');
  check(ra.gm === b.ghostMoney, 'no input: same ghost money');
  check(JSON.stringify(ra.real) === JSON.stringify(Array.from(b.real)), 'no input: same real drivers money');
  const sh = a.sh;
  check(near(b.ghostMoney, sh.thr.ghost, 0.011), 'ghost money at the end = ghost total');
  check(near(b.real[sh.ghost.taxi], b.ghostMoney, 0.011), 'G.real[ghost taxi] equals ghostMoney');
  console.log('(1) no input: tot ' + b.tot + ', rank ' + b.rank + ', ghost ' + b.ghostMoney);
}

// (2) scripted plan: same commits at the same times give the same state for every step size
{
  const idx = 0;
  const rec = [];
  runBot(idx, rec);
  const plan = [];
  let nOrders = 0;
  for (const r of rec) { plan.push(r); if (r.kind !== 'cruise' && ++nOrders >= 5) break; }
  check(nOrders >= 3, 'the bot made at least 3 commits for the plan (' + nOrders + ')');
  const results = [];
  for (const size of [720, 7.2, 36, 100]) {
    const G = newGame(idx);
    let k = 0, allOk = true;
    while (!G.over) {
      const nextT = k < plan.length ? plan[k].t : Infinity;
      if (nextT - G.t < 1e-6 && k < plan.length) {
        const p = plan[k++];
        const o = G.sh.orders[p.i];
        let ok = true;
        if (p.kind === 'pickup') ok = E.startPickup(o);
        else if (p.kind === 'next') ok = E.bookNext(o);
        else ok = E.cruiseTo(p.x, p.y);
        if (!ok) allOk = false;
        continue;
      }
      E.step(Math.min(size, nextT - G.t));
    }
    check(allOk, 'plan commits all accepted at step ' + size);
    results.push({ size, tot: G.tot, rank: G.rank, gm: G.ghostMoney, rides: G.rides, idle: Math.round(G.idleT * 1000) / 1000 });
  }
  const r0 = results[0];
  for (const r of results) {
    check(r.tot === r0.tot && r.rank === r0.rank && r.gm === r0.gm && r.rides === r0.rides && near(r.idle, r0.idle, 1e-3),
      'plan: step ' + r.size + ' equals step ' + r0.size + ' ' + JSON.stringify(r) + ' vs ' + JSON.stringify(r0));
  }
  check(r0.tot > 0, 'plan earns money (' + r0.tot + ')');
  console.log('(2) plan: ' + plan.length + ' actions, tot ' + r0.tot + ', rides ' + r0.rides);
}

// (3) greedy bot on every shift
{
  console.log('(3) bot per shift:');
  console.log('shift'.padEnd(12) + 'bot €'.padStart(8) + 'median'.padStart(8) + 'top10'.padStart(8) + 'ghost'.padStart(8) + ' medal rank/n  rides idle%');
  for (let s = 0; s < nShifts; s++) {
    const rec1 = [], rec2 = [];
    let overEvents = 0, rankEvents = 0, lastRank = -1, badRank = false;
    const onEnd = () => { overEvents++; };
    const onRank = (p) => { rankEvents++; if (lastRank !== -1 && p.prev !== lastRank) badRank = true; lastRank = p.rank; if (p.rank === p.prev) badRank = true; };
    PG.bus.on('shift:end', onEnd);
    PG.bus.on('rank:change', onRank);
    let G, res, threw = null;
    try { G = runBot(s, rec1); res = E.calcResult(); } catch (e) { threw = e; }
    PG.bus.off('shift:end', onEnd);
    PG.bus.off('rank:change', onRank);
    check(!threw, 'shift ' + s + ' no exception ' + (threw && threw.stack));
    if (threw) continue;
    const sh = G.sh;
    check(G.t === SHIFT && G.over, 'shift ' + sh.id + ' ends at ' + SHIFT + ' (' + G.t + ')');
    check(overEvents === 1, 'shift ' + sh.id + ' emits shift:end once (' + overEvents + ')');
    check(res.earned > 0, 'shift ' + sh.id + ' bot earned > 0');
    check(res.rank >= 1 && res.rank <= sh.nDrivers, 'shift ' + sh.id + ' rank in 1..nDrivers (' + res.rank + ')');
    check(res.medal >= 0 && res.medal <= 4, 'shift ' + sh.id + ' medal 0..4');
    check(!badRank, 'shift ' + sh.id + ' rank:change fires only on change, chained');
    check(G.trail.length <= 240 && G.floats.length <= 40, 'shift ' + sh.id + ' trail and floats are capped');
    const G2 = runBot(s, rec2);
    check(G2.tot === G.tot, 'shift ' + sh.id + ' same total on two runs');
    console.log(sh.id.padEnd(12) + G.tot.toFixed(2).padStart(8) + sh.median.toFixed(2).padStart(8) + sh.top10.toFixed(2).padStart(8) +
      sh.thr.ghost.toFixed(2).padStart(8) + '  ' + res.medal + '    ' + (res.rank + '/' + sh.nDrivers).padEnd(8) + String(res.rides).padStart(4) + String(res.idlePct).padStart(6));
  }
}

// (4) reachable(o) equals what startPickup / bookNext would do, at x1 and x3 step sizes
{
  const rnd = mulberry32(12345);
  let yes = 0, no = 0, yesNext = 0, noNext = 0, bad = 0;
  const target = 500;
  let samples = 0;
  const shiftsToUse = Math.min(nShifts, 4);
  for (let s = 0; s < shiftsToUse && samples < target; s++) {
    for (const [size, diff] of [[7.2, 'normal'], [21.6, 'normal'], [7.2, 'easy'], [21.6, 'hard']]) {
      const G = newGame(s, diff);
      const per = Math.ceil(target / shiftsToUse / 4) + 40;
      for (let k = 0; k < per && !G.over; k++) {
        E.step(size * (1 + Math.floor(rnd() * 4)));
        const orders = G.sh.orders;
        // pick among visible orders (and now and then any order near in time)
        const cand = [];
        for (let i = 0; i < orders.length; i++) {
          const o = orders[i];
          if (o.t < G.t - 5 || o.t > G.t + 900) continue;
          if (E.visible(o) || rnd() < 0.1) cand.push(o);
        }
        if (!cand.length) continue;
        const o = cand[Math.floor(rnd() * cand.length)];
        const riding = G.mode === 'ride';
        const snap = { mode: G.mode, cur: G.cur, next: G.next, t1: G.leg.t1, tot: G.tot };
        const r1 = E.reachable(o), r2 = E.reachable(o);
        const pvOk = E.preview(o).ok;
        const a = riding ? E.bookNext(o) : E.startPickup(o);
        samples++;
        if (r1 !== r2 || r1 !== a || pvOk !== a) { bad++; console.log('MISMATCH shift ' + s + ' t=' + G.t + ' mode=' + snap.mode + ' reachable=' + r1 + ' preview.ok=' + pvOk + ' action=' + a); }
        if (!a) {
          if (G.mode !== snap.mode || G.cur !== snap.cur || G.next !== snap.next || G.leg.t1 !== snap.t1) { bad++; console.log('refused action changed the state'); }
          riding ? noNext++ : no++;
        } else riding ? yesNext++ : yes++;
      }
    }
  }
  check(bad === 0, 'reachable == action result for all samples (' + bad + ' mismatches)');
  check(samples >= Math.min(500, 100), 'enough feasibility samples (' + samples + ')');
  check(yes > 0 && no > 0, 'both outcomes seen for startPickup (' + yes + '/' + no + ')');
  console.log('(4) feasibility: ' + samples + ' samples; startPickup yes/no ' + yes + '/' + no + ', bookNext yes/no ' + yesNext + '/' + noNext);
}

// (5) events and extras
{
  const G = newGame(0);
  const seen = { spawn: 0, book: 0, pickup: 0, dropoff: 0 };
  PG.bus.on('order:spawn', () => seen.spawn++);
  PG.bus.on('order:book', () => seen.book++);
  PG.bus.on('pickup', () => seen.pickup++);
  PG.bus.on('dropoff', () => seen.dropoff++);
  const rec = [];
  for (let i = 0; i < 1000 && !G.over; i++) { botTick(rec); E.step(7.2); }
  check(seen.spawn > 0, 'order:spawn events fire (' + seen.spawn + ')');
  check(seen.book === rec.filter(r => r.kind !== 'cruise').length, 'order:book once per accepted commit');
  check(seen.pickup === G.rides, 'pickup events equal rides');
  check(seen.dropoff >= G.rides - 1 && seen.dropoff <= G.rides, 'dropoff events follow rides');
  check(G.sh.thr.legend === 1.25 * G.sh.thr.ghost, 'thr.legend = 1.25 x ghost');
}

console.log(failures === 0 ? 'ALL OK (' + checks + ' checks)' : failures + ' FAILED of ' + checks + ' checks');
process.exit(failures === 0 ? 0 : 1);
