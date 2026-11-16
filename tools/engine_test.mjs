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
/** Best fare per second among the pins on the radar (E.reachable); cruise to the best hotspot when none is takeable. */
function botTick(rec, delay) {
  const G = E.G, orders = G.sh.orders;
  const riding = G.mode === 'ride';
  if (G.mode === 'pickup' || (riding && G.next)) return;
  let best = null, bestScore = -1;
  for (let i = 0; i < orders.length; i++) {
    const o = orders[i];
    if (o.t < G.t) continue;
    if (o.t > G.t + 900) break;
    if (delay && G.t < o.t - E.leadOf(o) + delay) continue;
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
  // nothing takeable on the radar: drive to the best hotspot (weight / distance); the bot never drives to a pin it cannot see
  let spot = null, ss = -1;
  for (const h of (G.ai ? G.ai.hot : [])) {
    const sc = h.w / (1 + Math.hypot(h.x - G.x, h.y - G.y) / 3000);
    if (sc > ss) { ss = sc; spot = h; }
  }
  if (spot && Math.hypot(spot.x - G.x, spot.y - G.y) > 200 && (G.mode === 'idle' || !G.leg || Math.hypot(G.leg.x1 - spot.x, G.leg.y1 - spot.y) > 50)) {
    if (E.cruiseTo(spot.x, spot.y)) rec.push({ t: G.t, kind: 'cruise', x: spot.x, y: spot.y });
  }
}

function runBot(idx, rec, difficulty, delay, onTick) {
  const G = newGame(idx, difficulty);
  for (let i = 0; i < 1000 && !G.over; i++) { botTick(rec, delay); E.step(7.2); if (onTick) onTick(G); }
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

// (6) the 7 rivals: per difficulty, a bot that reacts after 200 game s plays every shift
const RIV_IDS = PG.ai ? PG.ai.RIVALS.map(r => r.id) : [];
const rivalTable = {};
if (PG.ai) {
  console.log('(6) rivals; greedy bot reacting after 200 game s, all ' + nShifts + ' shifts:');
  for (const diff of ['easy', 'normal', 'hard']) {
    const st = {}; for (const id of RIV_IDS) st[id] = { eur: 0, rides: 0, fares: 0, pickups: 0, km: 0, maxKm: 0, air: 0, stand: 0, near: 0, surge: 0, react: 0, dist: 0, ticks: 0, work: 0, picks: 0 };
    // what each rival picks, seen from outside: a new target is noticed at the next bot tick
    let seen = {};
    const onTick = (G) => {
      for (const rv of G.rivals) {
        const a = st[rv.id];
        a.ticks++; if (rv.mode !== 'break') a.work++;
        const o = rv.target;
        if (!o || rv.mode !== 'pickup' || seen[rv.id] === o) continue;
        seen[rv.id] = o;
        a.picks++; a.km += o.km; a.maxKm = Math.max(a.maxKm, o.km); a.stand += o.c === 1 ? 1 : 0;
        a.near += Math.hypot(o.x0 - G.x, o.y0 - G.y) < 1500 ? 1 : 0;
        a.air += Math.hypot(o.x0 - 3232, o.y0 - 1323) <= 2500 || Math.hypot(o.x1 - 3232, o.y1 - 1323) <= 2500 ? 1 : 0;
        for (const w of G.sh.surgesM || []) if (o.t >= w.t0 && o.t <= w.t1 && Math.hypot(o.x0 - w.x, o.y0 - w.y) <= w.r) { a.surge++; break; }
        a.react += rv.p.lt0 - Math.max(o.t - E.leadOf(o), rv.p.idleSince);
        a.dist += Math.hypot(o.x0 - rv.p.lx0, o.y0 - rv.p.ly0) / 1000;
      }
    };
    let medals = [0, 0, 0, 0, 0], lostToRivals = 0, rivalLost = 0, places = 0, botEur = 0, badPlace = 0, n = 0;
    const onLost = (p) => { if (p.by !== 'real') lostToRivals++; };
    const onRL = () => { rivalLost++; };
    const onRP = (p) => { st[p.rival.id].fares = Math.round((st[p.rival.id].fares + p.fare) * 100) / 100; st[p.rival.id].pickups++; };
    PG.bus.on('order:lost', onLost); PG.bus.on('rival:lost', onRL); PG.bus.on('rival:pickup', onRP);
    for (let s = 0; s < nShifts; s++) {
      seen = {};
      const G = runBot(s, [], diff, 200, onTick);
      const res = E.calcResult();
      n++; medals[res.medal]++; botEur += res.earned; places += res.racePlace;
      if (res.raceSize !== 8 || res.racePlace < 1 || res.racePlace > 8) badPlace++;
      check(G.rivals.length === 7, diff + ' shift ' + s + ': 7 rivals drive');
      for (const rv of G.rivals) {
        st[rv.id].eur += rv.total; st[rv.id].rides += rv.rides;
        check(Math.abs(rv.total * 100 - Math.round(rv.total * 100)) < 1e-6, diff + ' ' + rv.id + ' total in cents');
        check(isFinite(rv.x) && isFinite(rv.y) && rv.x >= -1 && rv.x <= PG.C.MAP.w + 1 && rv.y >= -1 && rv.y <= PG.C.MAP.h + 1, diff + ' ' + rv.id + ' stays on the map');
      }
    }
    PG.bus.off('order:lost', onLost); PG.bus.off('rival:lost', onRL); PG.bus.off('rival:pickup', onRP);
    check(badPlace === 0, diff + ': racePlace in 1..8 and raceSize 8');
    let mn = 1e9, mx = -1, weakest = '';
    for (const id of RIV_IDS) {
      const avg = st[id].eur / n;
      check(st[id].rides > 0, diff + ': ' + id + ' drives (rides ' + st[id].rides + ')');
      check(st[id].pickups === st[id].rides, diff + ': ' + id + ' rival:pickup events equal rides');
      check(Math.abs(st[id].fares - st[id].eur) < 0.011 * n, diff + ': ' + id + ' totals are the sum of fares at pickup');
      if (avg < mn) { mn = avg; weakest = id; }
      if (avg > mx) mx = avg;
    }
    check(mx - mn > 1, diff + ': the 7 differ in average € (spread ' + (mx - mn).toFixed(2) + ')');
    // hard with the long pin lifetimes (LEAD 1200/1200/900): Руй, who only takes long trips, can fall below Нуну
    check(weakest === 'nuno' || (diff === 'hard' && weakest === 'rui'), diff + ': Нуну is the weakest (weakest: ' + weakest + ')');
    // every tactic of CONTRACT §11 shows in the numbers
    const m = (id, k) => st[id][k] / Math.max(1, st[id].picks);
    const others = (id, f) => RIV_IDS.filter(x => x !== id).reduce((acc, x) => acc + f(x), 0) / 6;
    const eph = (id) => st[id].eur / Math.max(1, st[id].work * 7.2 / 3600);
    check(m('rui', 'km') > 1.4 * others('rui', x => m(x, 'km')), diff + ': Руй takes long trips (' + m('rui', 'km').toFixed(1) + ' km vs ' + others('rui', x => m(x, 'km')).toFixed(1) + ')');
    check(m('rui', 'air') > 2 * others('rui', x => m(x, 'air')), diff + ': Руй flies to the airport (' + m('rui', 'air').toFixed(2) + ' vs ' + others('rui', x => m(x, 'air')).toFixed(2) + ')');
    check(m('fatima', 'stand') > 0.65 && m('fatima', 'stand') > 1.25 * others('fatima', x => m(x, 'stand')), diff + ': Фатіма stays on stand calls (' + m('fatima', 'stand').toFixed(2) + ' vs ' + others('fatima', x => m(x, 'stand')).toFixed(2) + ')');
    check(m('ines', 'react') < 0.6 * others('ines', x => m(x, 'react')), diff + ': Інеш reacts fastest (' + m('ines', 'react').toFixed(0) + ' s vs ' + others('ines', x => m(x, 'react')).toFixed(0) + ' s)');
    check(st.ines.maxKm <= 5 && st.nuno.maxKm <= 4, diff + ': Інеш takes short rides, Нуну nothing long (' + st.ines.maxKm.toFixed(1) + ', ' + st.nuno.maxKm.toFixed(1) + ' km)');
    check(m('nuno', 'dist') < others('nuno', x => m(x, 'dist')), diff + ': Нуну takes the nearest (' + m('nuno', 'dist').toFixed(2) + ' km to the pickup)');
    check(m('lurdes', 'surge') > 1.5 * others('lurdes', x => m(x, 'surge')), diff + ': Лурдеш rides the demand waves (' + m('lurdes', 'surge').toFixed(2) + ' vs ' + others('lurdes', x => m(x, 'surge')).toFixed(2) + ')');
    if (diff !== 'easy') check(m('tiago', 'near') > 0.8, diff + ': Тіаго hunts near the player (' + m('tiago', 'near').toFixed(2) + ')');
    check(eph('ze') >= 0.97 * Math.max(...RIV_IDS.filter(x => x !== 'ze').map(eph)), diff + ': Зé earns the most per working hour (' + eph('ze').toFixed(1) + ' €/h)');
    check(RIV_IDS.every(id => 1 - st[id].work / st[id].ticks <= (diff === 'easy' ? 0.55 : 0.15)), diff + ': breaks are short (' + RIV_IDS.map(id => (100 * (1 - st[id].work / st[id].ticks)).toFixed(0) + '%').join(' ') + ')');
    if (diff === 'easy') check(lostToRivals === 0, 'easy shields the player: no order lost to a rival (' + lostToRivals + ')');
    rivalTable[diff] = st;
    const sh = (k) => (100 * k / n).toFixed(0) + '%';
    console.log('  ' + diff.padEnd(7) + 'bot avg €' + (botEur / n).toFixed(1) + ' | medals>=bronze ' + sh(n - medals[0]) + ' (none ' + medals[0] + ', bronze ' + medals[1] + ', silver ' + medals[2] + ', gold ' + medals[3] + ', legend ' + medals[4] +
      ') | orders lost to rivals ' + (lostToRivals / n).toFixed(1) + '/shift | rivals lost target ' + (rivalLost / n).toFixed(1) + '/shift | avg race place ' + (places / n).toFixed(1) + '/8');
    console.log('     ' + RIV_IDS.map(id => id + ' €' + (st[id].eur / n).toFixed(1) + ' r' + (st[id].rides / n).toFixed(1)).join(' | '));
  }

  // (7) no input: rivals do not depend on the step size
  for (const diff of ['easy', 'normal', 'hard']) {
    E.config.difficulty = diff;
    const snap = (size) => {
      const G = newGame(1 % nShifts, diff);
      for (let i = 0; i < Math.round(SHIFT / size) && !G.over; i++) E.step(size);
      return JSON.stringify(G.rivals.map(r => [r.id, r.total, r.rides])) + JSON.stringify(Array.from(G.claim, ([i, c]) => [i, c.by, Math.round(c.t1)]));
    };
    check(snap(720) === snap(7.2) && snap(7.2) === snap(37.3), diff + ': no input, rivals identical at steps 720 / 7.2 / 37.3');
  }

  // (8) claims through the hooks: arrival first, the easy shield, a player commit sends the rival back
  {
    const G = newGame(3 % nShifts, 'normal');
    let found = null;
    for (let i = 0; i < 2000 && !found; i++) { E.step(5); found = G.rivals.find(r => r.mode === 'pickup'); }
    check(!!found, 'a rival goes to a pickup in a no-input shift');
    if (found) {
      const o = found.target, c = G.claim.get(o.i);
      check(c && c.by === found.id, 'the rival holds the claim on its target');
      check(PG.ai.claimBlocks(G, o, c.t1 + 1) === true && PG.ai.claimBlocks(G, o, c.t1 - 1) === false, 'normal: the earlier arrival wins');
      let lost = 0; const onRL = (p) => { if (p.rival === found && p.o === o) lost++; };
      PG.bus.on('rival:lost', onRL);
      G.claim.set(o.i, { by: 'player', t1: G.t + 1 }); G.cur = o; G.mode = 'pickup';
      PG.ai.onPlayerCommit(G, o);
      PG.bus.off('rival:lost', onRL);
      check(lost === 1 && found.mode === 'idle' && found.target === null, 'a player commit sends the rival back to idle (rival:lost)');
      G.cur = null; G.mode = 'idle';
      const GE = newGame(3 % nShifts, 'easy');
      GE.claim.set(7, { by: 'ze', t1: 100, boarded: false });
      check(PG.ai.claimBlocks(GE, GE.sh.orders[7], 5000) === false, 'easy: a rival on its way does not block the player');
      GE.claim.get(7).boarded = true;
      check(PG.ai.claimBlocks(GE, GE.sh.orders[7], 5000) === true, 'easy: a rival already on board still blocks');
    }
  }

  // (9) Лурдеш: chases a surge from t0 - 240, and camps at hotspots when there are no surges
  {
    let si = -1;
    for (let s = 0; s < nShifts && si < 0; s++) if (PG.data.shifts[s].surgesM && PG.data.shifts[s].surgesM.length) si = s;
    check(si >= 0, 'some shift has surges for the Лурдеш test');
    if (si >= 0) {
      // pickups inside an active surge circle: Лурдеш against the mean of the other six
      const inside = {}; for (const id of RIV_IDS) inside[id] = 0;
      const onRP = (p) => {
        const o = p.o;
        for (const w of E.G.sh.surgesM) {
          if (o.t >= w.t0 && o.t <= w.t1 && Math.hypot(o.x0 - w.x, o.y0 - w.y) <= w.r) { inside[p.rival.id]++; break; }
        }
      };
      PG.bus.on('rival:pickup', onRP);
      for (let s = si; s < Math.min(nShifts, si + 12); s++) {
        newGame(s, 'normal');
        while (!E.G.over) E.step(20);
      }
      PG.bus.off('rival:pickup', onRP);
      let others = 0; for (const id of RIV_IDS) if (id !== 'lurdes') others += inside[id] / 6;
      if (nShifts >= 8) check(inside.lurdes > 1.5 * others, 'Лурдеш takes more surge pickups than the others (' + inside.lurdes + ' vs mean ' + others.toFixed(1) + ')');
    }
    const sh0 = PG.data.shifts[0], saved = sh0.surgesM;
    sh0.surgesM = [];
    const G0 = newGame(0, 'normal');
    const hot = (G0.ai && G0.ai.hot) || [];
    let minH = Infinity, n0 = 0;
    while (!G0.over) {
      E.step(10);
      const L = G0.rivals.find(r => r.id === 'lurdes');
      if (L.mode === 'idle' || L.mode === 'cruise') { n0++; for (const h of hot) minH = Math.min(minH, Math.hypot(L.x - h.x, L.y - h.y)); }
    }
    sh0.surgesM = saved;
    check(hot.length > 0 && minH < 900, 'no surges: Лурдеш camps at hotspots (closest ' + Math.round(minH) + ' m over ' + n0 + ' idle samples)');
  }
}

console.log(failures === 0 ? 'ALL OK (' + checks + ' checks)' : failures + ' FAILED of ' + checks + ' checks');
process.exit(failures === 0 ? 0 : 1);
