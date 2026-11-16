/* 20_engine.js: PG.engine, the game rules of CONTRACT §11 and the events of §12 (tier 0). DOM-free. */
(function (root) {
  const PG = root.PG = root.PG || {};
  const C = PG.C;

  const EPS = 1e-9;          // tolerance for "event time <= step end" and ties
  const TRAIL_EVERY = 10;    // game s between trail samples
  const TRAIL_MAX = 120;     // samples kept
  const FLOAT_MAX = 40;      // floating texts kept
  const MAX_EVENTS_PER_STEP = 200000; // safety net against an endless loop
  const FLOAT_COLOR = '#3df5b0';

  const DIFF_K = C.DIFF_K;
  // E.party = { clock() -> game seconds } in party mode (80_party.js): server clock, no pause or x3, no AI rivals
  const E = PG.engine = { config: { difficulty: 'normal' }, G: null, DIFF_K: DIFF_K, party: null };
  let G = null;

  // reused scratch objects (no per-call allocation)
  const sc = { x: 0, y: 0, t: 0, eta: 0 };
  const pv = { fromX: 0, fromY: 0, eta: 0, wait: 0, ok: false, km: 0, fare: 0 };
  const pt = { x: 0, y: 0, k: 0, hx: 0, hy: -1 };

  /** Emits a bus event when the bus exists. */
  function emit(ev, payload) { if (PG.bus) PG.bus.emit(ev, payload); }

  /** Rounds a euro amount to cents. */
  function r2(x) { return Math.round(x * 100) / 100; }

  /** Formats a euro amount for floats (falls back when PG.util is absent). */
  function eur(x) {
    if (PG.util && PG.util.eur) return PG.util.eur(x);
    return '€' + x.toFixed(2).replace('.', ',');
  }

  /** Real-time clock in ms (only for the message expiry). */
  function nowMs() { return typeof performance !== 'undefined' ? performance.now() : Date.now(); }

  /** Speed (km/h) of the shift at game second t (§11). */
  function speedAt(t) {
    const sh = G.sh;
    return sh.speedByHour[(sh.startHour + Math.floor(t / 3600)) % 24];
  }

  /** Jam slowdown (traffic layer 44_traffic.js) along a straight leg at game second t: 0.5..1, or 1 without it. */
  function jam(x0, y0, x1, y1, t) {
    return PG.traffic ? PG.traffic.leg(x0, y0, x1, y1, G.sh.startHour * 3600 + t) : 1;
  }

  /** Seconds to drive from (fx, fy) to the pickup of o when leaving at game second t, boarding included. */
  function eta(fx, fy, t, o) {
    return Math.hypot(o.x0 - fx, o.y0 - fy) / 1000 * G.sh.detour / (speedAt(t) * jam(fx, fy, o.x0, o.y0, t)) * 3600 + C.BOARD_S;
  }

  /** Seconds a pin is shown before its order time. */
  function leadOf(o) {
    if (G && G.lead) return G.lead[o.i];
    const k = DIFF_K[E.config.difficulty] || 1;
    return C.LEAD[o.c] * k * (PG.rules && PG.rules.leadK ? PG.rules.leadK(o) : 1);
  }

  /** True when the pin of o is on screen now: inside its lead window and the radar radius of the car. */
  function visible(o) {
    if (!G || G.over) return false;
    const t = G.t;
    if (t >= o.t || t < o.t - G.lead[o.i] - EPS) return false;
    return Math.hypot(o.x0 - G.x, o.y0 - G.y) <= C.RADIUS[o.c] * G.diffK;
  }

  // reason codes of feasibility()
  const OK = 0, GONE = 1, LATE = 2;

  /**
   * The single feasibility function behind reachable, preview, startPickup and bookNext.
   * Fills `sc` (from point, from time, eta). `relaxed` skips the radar test (re-validating a booked order).
   */
  function feasibility(o, relaxed) {
    if (G.mode === 'ride') { sc.x = G.cur.x1; sc.y = G.cur.y1; sc.t = G.leg.t1; }
    else { sc.x = G.x; sc.y = G.y; sc.t = G.t; }
    sc.eta = eta(sc.x, sc.y, sc.t, o);
    if (G.over || G.taken.has(o.i)) return GONE;
    const cl = G.claim.get(o.i);
    if (cl && cl.by !== 'player') {
      // rival claims: arrival first; the AI owns the rule (the easy shield, rivals already on board)
      if (PG.ai && PG.ai.claimBlocks) { if (PG.ai.claimBlocks(G, o, sc.t + sc.eta)) return GONE; }
      else if (cl.t1 <= sc.t + sc.eta) return GONE;
    }
    if (relaxed) {
      if (G.t >= o.t) return LATE;
    } else if (!visible(o)) return LATE;
    if (sc.t + sc.eta > o.t + EPS) return LATE;
    return OK;
  }

  /** True when the player can take o now (as the next pickup, or as the booked next order while riding). */
  function reachable(o) { return feasibility(o, false) === OK; }

  /** Read-only preview of o (one reused object): the start point, eta, the slack, price. */
  function preview(o) {
    const code = feasibility(o, false);
    pv.fromX = sc.x; pv.fromY = sc.y; pv.eta = sc.eta;
    pv.wait = o.t - (sc.t + sc.eta);
    pv.ok = code === OK;
    pv.km = o.km; pv.fare = o.fare;
    return pv;
  }

  /** Adds a floating text at (x, y); the oldest one is recycled when the list is full. */
  function addFloat(x, y, text, color, born) {
    const f = G.floats.length >= FLOAT_MAX ? G.floats.shift() : {};
    f.x = x; f.y = y; f.text = text; f.color = color; f.born = born;
    G.floats.push(f);
  }

  /** Appends the car position to the trail (flat [x, y, ...], oldest first, capped). */
  function pushTrail() {
    const tr = G.trail;
    if (tr.length >= 2 * TRAIL_MAX) { tr.copyWithin(0, 2); tr[tr.length - 2] = G.x; tr[tr.length - 1] = G.y; }
    else tr.push(G.x, G.y);
  }

  /** Starts a leg of the given mode from the car to (x1, y1) between game seconds t0 and t1. */
  function beginLeg(mode, x1, y1, t0, t1) {
    const L = G.leg;
    L.t0 = t0; L.t1 = t1; L.x0 = G.x; L.y0 = G.y; L.x1 = x1; L.y1 = y1;
    L.path = PG.roads && PG.roads.enabled ? (PG.roads.route(G.x, G.y, x1, y1) || null) : null;
    const dx = x1 - G.x, dy = y1 - G.y, l = Math.hypot(dx, dy);
    if (l > 1e-6) { L.hx = dx / l; L.hy = dy / l; }
    G.mode = mode;
    if (l > 1e-6) { G.hx = L.hx; G.hy = L.hy; }
  }

  /** Moves the car to its position at G.t (heading included). */
  function updatePos() {
    const m = G.mode;
    if (m === 'ride') { PG.data.ridePos(G.cur, G.t - G.leg.t0, G); return; }
    if (m !== 'pickup' && m !== 'cruise') return;
    const L = G.leg, dur = L.t1 - L.t0;
    let f = dur > 0 ? (G.t - L.t0) / dur : 1;
    if (f < 0) f = 0; else if (f > 1) f = 1;
    if (L.path && PG.roads && PG.roads.enabled) {
      const r = PG.roads.pointAt(L.path, f, pt) || pt;
      G.x = r.x; G.y = r.y;
      if (r.hx !== undefined) { G.hx = r.hx; G.hy = r.hy; }
    } else {
      G.x = L.x0 + (L.x1 - L.x0) * f;
      G.y = L.y0 + (L.y1 - L.y0) * f;
      if (L.hx !== undefined) { G.hx = L.hx; G.hy = L.hy; }
    }
  }

  /** Drops the claim of an order the player gives up, so rivals can take it. */
  function release(o) {
    if (!o) return;
    const cl = G.claim.get(o.i);
    if (cl && cl.by === 'player') G.claim.delete(o.i);
  }

  /** Records a player commitment on o (claim, rival hook). `taken` is set at the pickup. */
  function commit(o, t1) {
    G.claim.set(o.i, { by: 'player', t1: t1 });
    if (PG.ai && PG.ai.onPlayerCommit) PG.ai.onPlayerCommit(G, o);
  }

  /** Shows a message: toast through the bus and G.msg (until = real ms clock). */
  function say(text, ms) {
    if (!G) return;
    G.msg.text = text;
    G.msg.until = nowMs() + (ms || 2500);
    emit('note', { text: text, ms: ms || 2500 });
  }

  /** Refusal message for a feasibility code. */
  function refuse(code) {
    say(code === GONE ? 'Замовлення вже зайняте' : 'Не встигнеш');
  }

  /** Sends the car to pick up o; false (and a toast) when it cannot. Not while riding. */
  function startPickup(o) {
    if (!G || G.over || G.mode === 'ride') return false;
    const code = feasibility(o, false);
    if (code !== OK) { refuse(code); return false; }
    if (G.mode === 'pickup') release(G.cur);
    G.cur = o;
    beginLeg('pickup', o.x0, o.y0, G.t, G.t + sc.eta);
    commit(o, G.t + sc.eta);
    emit('order:book', { o: o, kind: 'pickup' });
    return true;
  }

  /** Books o as the next order while riding; false (and a toast) when it cannot. */
  function bookNext(o) {
    if (!G || G.over || G.mode !== 'ride') return false;
    const code = feasibility(o, false);
    if (code !== OK) { refuse(code); return false; }
    if (G.next) release(G.next);
    G.next = o;
    commit(o, sc.t + sc.eta);
    emit('order:book', { o: o, kind: 'next' });
    return true;
  }

  /** Free drive to a point (metres, clamped to the map). Not while riding; cancels a pickup. */
  function cruiseTo(x, y) {
    if (!G || G.over || G.mode === 'ride') return false;
    x = Math.min(Math.max(x, 0), C.MAP.w);
    y = Math.min(Math.max(y, 0), C.MAP.h);
    if (G.mode === 'pickup') { release(G.cur); G.cur = null; }
    const dist = Math.hypot(x - G.x, y - G.y);
    if (dist < 1) { G.mode = 'idle'; return true; }
    const dur = dist / 1000 * G.sh.detour / (speedAt(G.t) * jam(G.x, G.y, x, y, G.t)) * 3600;
    beginLeg('cruise', x, y, G.t, G.t + dur);
    return true;
  }

  /** Party mode: takes back a booking the server refused. The car stops where it is; a booked next order is dropped. */
  function unbook(o) {
    if (!G || !o) return;
    release(o);
    if (G.mode === 'pickup' && G.cur === o) { G.cur = null; G.mode = 'idle'; G.leg.t0 = G.leg.t1 = G.t; }
    if (G.next === o) G.next = null;
  }

  /** Counts real drivers with more money than the player and updates rank, ghost money and their events. */
  function refreshRace() {
    let n = 0;
    const real = G.real, tot = G.tot;
    for (let i = 0; i < real.length; i++) if (real[i] > tot) n++;
    const rank = Math.min(n + 1, real.length);
    if (rank !== G.rank) {
      const prev = G.rank;
      G.rank = rank;
      emit('rank:change', { rank: rank, prev: prev });
    }
    G.ghostMoney = PG.data.ghostMoney(G.sh, G.t);
    const ahead = tot > G.ghostMoney;
    if (ahead !== G.ahead) {
      G.ahead = ahead;
      emit('ghost:overtake', { ahead: ahead });
    }
  }

  /** The pickup leg of the player has ended: take the fare, start the ride. */
  function onPickup() {
    const o = G.cur, tev = G.leg.t1;
    G.x = o.x0; G.y = o.y0;
    G.tot = r2(G.tot + o.fare);
    G.rides++;
    G.taken.add(o.i);
    G.leg.t0 = tev; G.leg.t1 = tev + o.d;
    G.leg.x0 = o.x0; G.leg.y0 = o.y0; G.leg.x1 = o.x1; G.leg.y1 = o.y1; G.leg.path = null;
    G.mode = 'ride';
    G.dirty = true;
    addFloat(o.x0, o.y0, '+' + eur(o.fare), FLOAT_COLOR, tev);
    emit('pickup', { o: o, fare: o.fare });
  }

  /** The ride has ended: pay the tip (set by rules), then start the booked order or park. */
  function onDropoff() {
    const o = G.cur, tev = G.leg.t1;
    G.x = o.x1; G.y = o.y1;
    const payload = { o: o, fare: o.fare, tip: 0 };
    emit('dropoff', payload);
    if (payload.tip > 0) { G.tot = r2(G.tot + payload.tip); G.dirty = true; }
    G.cur = null;
    G.mode = 'idle';
    G.leg.t0 = G.leg.t1 = tev;
    const nx = G.next;
    if (!nx) return;
    G.next = null;
    release(nx);
    const code = feasibility(nx, true);
    if (code === OK) {
      G.cur = nx;
      beginLeg('pickup', nx.x0, nx.y0, tev, tev + sc.eta);
      commit(nx, tev + sc.eta);
    } else {
      emit('order:lost', { o: nx, by: 'real' });
      say('Замовлення вже не актуальне');
    }
  }

  /** Processes everything due at G.t: real money, spawns, trail, then the player's leg end (repeatedly). */
  function processDue() {
    const orders = G.sh.orders, tt = G.t + EPS;
    while (G.realPtr < orders.length && orders[G.realPtr].t <= tt) {
      const o = orders[G.realPtr++];
      G.real[o.taxi] = r2(G.real[o.taxi] + o.fare);
      G.dirty = true;
    }
    while (G.spawnPtr < G.spawnIdx.length && G.spawnT[G.spawnPtr] <= tt) {
      const o = orders[G.spawnIdx[G.spawnPtr++]];
      if (!G.taken.has(o.i) && Math.hypot(o.x0 - G.x, o.y0 - G.y) <= C.RADIUS[o.c] * G.diffK) emit('order:spawn', { o: o });
    }
    while (G.nextTrail <= tt) { pushTrail(); G.nextTrail += TRAIL_EVERY; }
    for (let guard = 0; guard < 8 && G.mode !== 'idle' && G.leg.t1 <= tt; guard++) {
      if (G.mode === 'pickup') onPickup();
      else if (G.mode === 'ride') onDropoff();
      else { G.x = G.leg.x1; G.y = G.leg.y1; G.mode = 'idle'; }
    }
    if (G.dirty) { G.dirty = false; refreshRace(); }
  }

  /** Earliest event time <= tEnd (never before G.t), or Infinity when only the step end is left. */
  function nextTime(tEnd) {
    let te = Infinity;
    if (G.mode !== 'idle') te = G.leg.t1;
    const orders = G.sh.orders;
    if (G.realPtr < orders.length && orders[G.realPtr].t < te) te = orders[G.realPtr].t;
    if (G.spawnPtr < G.spawnIdx.length && G.spawnT[G.spawnPtr] < te) te = G.spawnT[G.spawnPtr];
    if (G.nextTrail < te) te = G.nextTrail;
    if (te > tEnd + EPS) return Infinity;
    return te < G.t ? G.t : te;
  }

  /** Moves G.t forward to te: idle time, position, then the rivals' interval. */
  function advance(te) {
    const t0 = G.t;
    if (te > t0) {
      if (G.mode === 'idle' || G.mode === 'cruise') G.idleT += te - t0;
      G.t = te;
    }
    updatePos();
    if (te > t0 && PG.ai && PG.ai.tick) { PG.ai.tick(G, t0, te); dropStolen(); }
  }

  /** A rival that arrives first takes the claim (K6 AI): the player's pickup or booked order falls back. */
  function dropStolen() {
    let cl;
    if (G.mode === 'pickup' && G.cur) {
      cl = G.claim.get(G.cur.i);
      if (cl && cl.by !== 'player') {
        G.cur = null; G.mode = 'idle'; G.leg.t0 = G.leg.t1 = G.t;
      }
    }
    if (G.next) {
      cl = G.claim.get(G.next.i);
      if (cl && cl.by !== 'player') G.next = null;
    }
  }

  /** Advances the game by dt game seconds (clamped to the shift end); events are processed in time order. */
  function step(dt) {
    if (!G || G.over) return;
    if (E.party) dt = E.party.clock() - G.t;
    if (!(dt > 0)) return;
    let tEnd = G.t + dt;
    if (tEnd > C.SHIFT - 1e-6) tEnd = C.SHIFT;
    for (let guard = 0; guard < MAX_EVENTS_PER_STEP; guard++) {
      const te = nextTime(tEnd);
      if (te === Infinity) { advance(tEnd); break; }
      advance(te);
      processDue();
    }
    if (tEnd >= C.SHIFT) {
      G.t = C.SHIFT;
      G.over = true;
      emit('shift:end', { result: calcResult() });
    }
  }

  /** Cents of a euro amount, for exact comparisons. */
  function cents(x) { return Math.round(x * 100); }

  /** Result of the shift for the result screen and the save. */
  function calcResult() {
    const sh = G.sh, earned = r2(G.tot), ec = cents(earned);
    let better = 0;
    for (let i = 0; i < sh.ranking.length; i++) if (cents(sh.ranking[i]) > ec) better++;
    let medal = 0;
    if (earned >= sh.thr.legend - 1e-9) medal = 4;
    else if (ec > cents(sh.thr.ghost)) medal = 3;
    else if (ec >= cents(sh.thr.top10)) medal = 2;
    else if (ec >= cents(sh.thr.median)) medal = 1;
    let rp = 1;
    for (let i = 0; i < G.rivals.length; i++) if (cents(G.rivals[i].total) > ec) rp++;
    return {
      earned: earned, rank: Math.min(better + 1, sh.nDrivers), nDrivers: sh.nDrivers, medal: medal, rides: G.rides,
      idlePct: Math.round(100 * G.idleT / C.SHIFT), vsGhost: r2(earned - sh.thr.ghost),
      racePlace: rp, raceSize: 1 + G.rivals.length, tips: G.tips, bestCombo: G.bestCombo,
      shiftId: sh.id, idx: G.idx
    };
  }

  /** Builds the state of a new shift. `config.difficulty` must be set before. */
  function newGame(idx) {
    const sh = PG.data.shifts[idx];
    if (!sh) throw new Error('no shift ' + idx);
    const diff = DIFF_K[E.config.difficulty] ? E.config.difficulty : 'normal';
    const n = sh.orders.length;
    G = E.G = {
      t: 0, sh: sh, idx: idx, mode: 'idle', x: C.HOME.x, y: C.HOME.y, hx: 0, hy: -1,
      leg: { t0: 0, t1: 0, x0: C.HOME.x, y0: C.HOME.y, x1: C.HOME.x, y1: C.HOME.y, path: null, hx: 0, hy: -1 },
      cur: null, next: null, tot: 0, rides: 0, idleT: 0, tips: 0, combo: 0, bestCombo: 0, lastDropT: -1e9,
      trail: [], floats: [], rivals: [], claim: new Map(), taken: new Set(),
      real: new Float64Array(sh.nDrivers), rank: 1, ghostMoney: 0, ahead: false,
      over: false, paused: false, fast: false, msg: { text: '', until: 0 },
      diffK: DIFF_K[diff], difficulty: diff, lead: new Float64Array(n),
      realPtr: 0, spawnPtr: 0, spawnIdx: null, spawnT: null, nextTrail: TRAIL_EVERY, dirty: false
    };
    // lead of every order (rules may depend on G.sh, so G is set first)
    for (let i = 0; i < n; i++) {
      const o = sh.orders[i];
      G.lead[i] = C.LEAD[o.c] * G.diffK * (PG.rules && PG.rules.leadK ? PG.rules.leadK(o) : 1);
    }
    // spawn schedule sorted by spawn time (lead differs per order)
    const idxs = new Array(n);
    for (let i = 0; i < n; i++) idxs[i] = i;
    idxs.sort(function (a, b) {
      const d = (sh.orders[a].t - G.lead[a]) - (sh.orders[b].t - G.lead[b]);
      return d !== 0 ? d : a - b;
    });
    G.spawnIdx = Int32Array.from(idxs);
    G.spawnT = new Float64Array(n);
    for (let k = 0; k < n; k++) G.spawnT[k] = sh.orders[idxs[k]].t - G.lead[idxs[k]];
    while (G.spawnPtr < n && G.spawnT[G.spawnPtr] <= EPS) G.spawnPtr++; // already on screen at the start
    G.trail.push(G.x, G.y);
    if (E.party) {
      const locked = { get: function () { return false; }, set: function () {} };
      Object.defineProperties(G, { paused: locked, fast: locked });
    } else if (PG.ai && PG.ai.init) PG.ai.init(G);
    emit('shift:start', { idx: idx, sh: sh });
    return G;
  }

  E.newGame = newGame;
  E.step = step;
  E.reachable = reachable;
  E.preview = preview;
  E.startPickup = startPickup;
  E.bookNext = bookNext;
  E.cruiseTo = cruiseTo;
  E.unbook = unbook;
  E.say = say;
  E.leadOf = leadOf;
  E.calcResult = function () { return G ? calcResult() : null; };
  // extras used by the renderer and the order card
  E.visible = visible;
  E.eta = function (fx, fy, t, o) { return G ? eta(fx, fy, t, o) : 0; };
})(typeof window !== 'undefined' ? window : globalThis);
