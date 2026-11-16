// 25_ai.js: the 7 AI rivals («7 ланосів»). DOM-free. Hooks: PG.ai.init / tick / onPlayerCommit.
(function (root) {
  const PG = root.PG = root.PG || {};

  // ---- static tables ------------------------------------------------------------------------
  // f = true for female rivals (verb forms in toasts).
  const RIVALS = [
    { id: 'ze', name: 'Ашот', nick: 'Акула', color: '#ff8a3d', f: false },
    { id: 'fatima', name: 'Тьотя Валя', nick: 'Королева стоянки', color: '#f4d03f', f: true },
    { id: 'rui', name: 'Камран', nick: 'Сова', color: '#4db8ff', f: false },
    { id: 'ines', name: 'Зіна', nick: 'Блискавка', color: '#ff4d6a', f: true },
    { id: 'tiago', name: 'ОлеКсій', nick: 'Снайпер', color: '#ff6ec7', f: false },
    { id: 'lurdes', name: 'Люда', nick: 'Хвиля', color: '#a0e85b', f: true },
    { id: 'nuno', name: 'Стьопа', nick: 'Новачок', color: '#ffffff', f: false },
  ];

  // react scales the personal reaction, attn = share of pins a rival ever notices, duty = share of the
  // shift it works, near = pins within this many metres of the player are always noticed with nearReact.
  const DIFF = {
    easy: { react: 2.4, radius: 0.7, attn: 0.14, duty: 0.5, speed: 1, near: 0, nearReact: 1 },
    normal: { react: 1.0, radius: 1.0, attn: 0.35, duty: 0.88, speed: 1.15, near: 2500, nearReact: 0.5 },
    hard: { react: 0.55, radius: 1.25, attn: 0.5, duty: 0.9, speed: 1.6, near: 5000, nearReact: 0.35 },
  };

  const HUNT_M = 1500;       // ОлеКсій only takes pins this close to the player
  const SHORT_KM = 5;        // Зіна takes nothing longer
  const NUNO_KM = 4;         // Стьопа takes nothing longer
  const LONG_KM = 3.5;       // Камран takes nothing shorter (unless it touches the airport)
  const STAND_ETA = 120;     // Тьотя Валя leaves her stand for a street pin only this close in time
  const STAND_WAIT = 420;    // ... and for a stand call at most this far away in time

  // S = per-candidate scratch: S.pdist (pickup to player, m), S.inSurge, S.live (a surge runs or is about
  // to), S.air, S.diff. score() <= 0 means "never"; att() scales the share of pins the rival notices.
  // `repos` = seconds between repositioning drives while idle.
  const PERS = {
    ze: {
      react: 16, repos: 150, travel: 0.85,
      att() { return 2.5; },
      score(o, eta) { return o.fare / (eta + o.d + 30); },
    },
    fatima: {
      react: 40, repos: 600, travel: 1,
      att(o) { return o.c === 1 ? 3 : 0.5; },
      score(o, eta) {
        const b = o.fare / (eta + o.d + 30);
        if (o.c === 1) return eta < STAND_WAIT ? b * 1.6 : 0;
        return eta < STAND_ETA ? b * 0.5 : 0;
      },
    },
    rui: {
      react: 34, repos: 300, travel: 1,
      att(o, S, night) { return (night ? 1.4 : 1) * (S.air ? 2 : 1) * (o.km >= 6 ? 1.5 : 1); },
      score(o, eta, S) {
        if (o.km < LONG_KM && !S.air) return 0;
        return o.fare / (eta + o.d + 30) * (1 + o.km / 4) * (S.air ? 2.5 : 1);
      },
    },
    ines: {
      react: 8, repos: 120, travel: 1,
      att() { return 1.4; },
      score(o, eta) { return o.km > SHORT_KM ? 0 : o.fare / (eta + 0.5 * o.d + 60); },
    },
    tiago: {
      react: 20, repos: 45, travel: 1,
      score(o, eta, S) {
        const b = o.fare / (eta + o.d + 30);
        if (S.diff === 'easy') return b;
        return S.pdist < HUNT_M ? b * 2 : 0;
      },
    },
    lurdes: {
      react: 30, repos: 240, travel: 1,
      att(o, S) { return S.inSurge ? 3 : 0.7; },
      score(o, eta, S) {
        const b = o.fare / (eta + o.d + 30);
        if (!S.live) return b;
        return S.inSurge ? b * 4 : (eta < STAND_ETA ? b * 0.5 : 0);
      },
    },
    nuno: {
      react: 90, repos: 90, travel: 1.7, attn: 0.5,
      score(o, eta) { return o.km > NUNO_KM ? 0 : 1 / (eta + 60); },
    },
  };

  const GRID = 5;            // game s between decision points of a free rival
  const CYCLE = 1500;        // work + break cycle, game s
  const AIRPORT = { x: 3232, y: 1323, r: 2500 };
  const NOTICE_K = 0.6;      // share of the personal reaction spent before a pin is noticed
  const TOAST_MS = 2600;

  // ---- helpers (no allocation) ----------------------------------------------------------------
  function mix(a, b) {
    let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ b;
    h = Math.imul(h ^ (h >>> 16), 0xc2b2ae35);
    h ^= h >>> 13;
    h = Math.imul(h, 0x27d4eb2f);
    h ^= h >>> 15;
    return (h >>> 0) / 4294967296;
  }

  function fnv(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
      const c = str.charCodeAt(i);
      h ^= c & 255; h = Math.imul(h, 16777619);
      h ^= c >>> 8; h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  function cents(x) { return Math.round(x * 100) / 100; }
  function clamp(x, a, b) { return x < a ? a : (x > b ? b : x); }
  function C(name, dflt) { return (PG.C && PG.C[name] !== undefined) ? PG.C[name] : dflt; }

  const scratchS = { pdist: 1e9, inSurge: false, live: false, air: false, diff: 'normal' };
  const scratchPos = { x: 0, y: 0 };
  const scratchPt = { x: 0, y: 0, k: 0, hx: 0, hy: 0 };

  let bestO = null, bestEta = 0, bestScore = 0, bestKind = 0;

  // ---- per game setup ---------------------------------------------------------------------------
  function diffName(G) {
    const d = G.difficulty || (PG.engine && PG.engine.config && PG.engine.config.difficulty) || 'normal';
    return DIFF[d] ? d : 'normal';
  }

  function leadFor(o, K) {
    if (PG.engine && typeof PG.engine.leadOf === 'function') return PG.engine.leadOf(o);
    const L = C('LEAD', [310, 310, 310]);
    return L[o.c] * K * (PG.rules && PG.rules.leadK ? PG.rules.leadK(o) : 1);
  }

  // Stand centroids (call type B) and density hotspots, built once per game.
  function buildPlaces(A, sh) {
    const orders = sh.orders;
    const stands = new Map();
    const cells = new Map();
    for (let i = 0; i < orders.length; i++) {
      const o = orders[i];
      if (o.stand > 0) {
        let s = stands.get(o.stand);
        if (!s) { s = { x: 0, y: 0, n: 0, w: 0 }; stands.set(o.stand, s); }
        s.x += o.x0; s.y += o.y0; s.n++;
      }
      const key = Math.floor(o.x0 / 1000) * 1000 + Math.floor(o.y0 / 1000);
      let c = cells.get(key);
      if (!c) { c = { x: 0, y: 0, n: 0, w: 0 }; cells.set(key, c); }
      c.x += o.x0; c.y += o.y0; c.n++;
    }
    const st = [];
    stands.forEach(function (s) {
      if (s.n >= 3) { st.push({ x: s.x / s.n, y: s.y / s.n, w: s.n / orders.length, n: s.n }); }
    });
    st.sort(function (a, b) { return b.n - a.n; });
    A.stands = st.slice(0, 8);
    let hot = (sh.hotM && sh.hotM.length) ? sh.hotM.slice() : null;
    if (!hot) {
      const cs = [];
      cells.forEach(function (c) { cs.push({ x: c.x / c.n, y: c.y / c.n, w: c.n / orders.length, n: c.n }); });
      cs.sort(function (a, b) { return b.n - a.n; });
      hot = cs.slice(0, 6);
    } else {
      hot.sort(function (a, b) { return b.w - a.w; });
    }
    A.hot = hot;
  }

  function pick(arr, u) { return arr[Math.min(arr.length - 1, Math.floor(u * arr.length))]; }

  function init(G) {
    const sh = G.sh;
    const dn = diffName(G);
    const A = G.ai = {
      dn: dn, D: DIFF[dn], sh: sh,
      lead: new Float32Array(sh.orders.length),
      maxLead: 0, stands: [], hot: [],
      seed: fnv(sh.id || 'shift'),
      BOARD: C('BOARD_S', 30),
      RAD: C('RADIUS', [5000, 3500, 2500]),
      MAP: C('MAP', { w: 15000, h: 19000 }),
    };
    const K = (PG.engine && PG.engine.DIFF_K ? PG.engine.DIFF_K : C('DIFF_K', { easy: 1.0, normal: 1, hard: 0.9 }))[dn];
    for (let i = 0; i < sh.orders.length; i++) {
      const o = sh.orders[i];
      const l = leadFor(o, K);
      A.lead[o.i] = l;
      if (l > A.maxLead) A.maxLead = l;
    }
    buildPlaces(A, sh);
    if (!G.claim) G.claim = new Map();
    if (!G.rivals) G.rivals = [];
    G.rivals.length = 0;
    for (let k = 0; k < RIVALS.length; k++) {
      const R = RIVALS[k];
      const seed = (A.seed ^ fnv(R.id)) >>> 0;
      const rv = {
        id: R.id, name: R.name, nick: R.nick, color: R.color, f: R.f,
        x: 0, y: 0, hx: 0, hy: 1, mode: 'idle', target: null, total: 0, rides: 0,
        p: {
          k: k, seed: seed, pers: PERS[R.id], state: 0, next: 0, ptr: 0,
          phase: Math.floor(mix(seed, 1) * GRID),
          freeAt: 0, lastRepos: -1e9, idleSince: 0,
          nextBreak: 0, breakUntil: 0, surgeGo: -1, reposN: 0,
          lt0: 0, lt1: 0, lx0: 0, ly0: 0, lx1: 0, ly1: 0, lhx: 0, lhy: 1, lpath: null,
          cur: null,
        },
      };
      const W = CYCLE * A.D.duty;
      rv.p.nextBreak = A.D.duty >= 1 ? 1e9 : W * (0.3 + 0.7 * mix(seed, 2));
      destination(G, A, rv, 0);
      rv.x = scratchPos.x; rv.y = scratchPos.y;
      rv.p.next = gridUp(rv.p, rv.p.freeAt = reactTime(A, rv) * mix(seed, 3));
      G.rivals.push(rv);
    }
  }

  function gridUp(p, T) {
    return p.phase + Math.ceil((T - p.phase) / GRID) * GRID;
  }

  function reactTime(A, rv) { return rv.p.pers.react * A.D.react; }

  // ---- travel -----------------------------------------------------------------------------------
  function speedAt(A, T) {
    const sh = A.sh;
    const h = (sh.startHour + Math.floor(T / 3600)) % 24;
    return sh.speedByHour[h] * A.D.speed;
  }

  function driveTime(A, rv, T, x, y, tx, ty) {
    const dx = tx - x, dy = ty - y;
    const km = Math.sqrt(dx * dx + dy * dy) / 1000;
    return km * A.sh.detour / speedAt(A, T) * 3600 * rv.p.pers.travel;
  }

  function startLeg(A, rv, T, tx, ty, dur) {
    const p = rv.p;
    p.lt0 = T; p.lt1 = T + dur;
    p.lx0 = rv.x; p.ly0 = rv.y; p.lx1 = tx; p.ly1 = ty;
    const dx = tx - rv.x, dy = ty - rv.y, L = Math.sqrt(dx * dx + dy * dy);
    if (L > 1) { p.lhx = dx / L; p.lhy = dy / L; }
    p.lpath = null;
    if (PG.roads && PG.roads.enabled && L > 50) p.lpath = PG.roads.route(rv.x, rv.y, tx, ty) || null;
  }

  // Position of a free-or-pickup rival on its current leg at game time T.
  function legPos(rv, T) {
    const p = rv.p;
    const span = p.lt1 - p.lt0;
    const f = span > 0 ? clamp((T - p.lt0) / span, 0, 1) : 1;
    if (p.lpath && PG.roads && PG.roads.enabled) {
      const r = PG.roads.pointAt(p.lpath, f, scratchPt);
      rv.x = r.x; rv.y = r.y;
      if (r.hx !== 0 || r.hy !== 0) { rv.hx = r.hx; rv.hy = r.hy; }
    } else {
      rv.x = p.lx0 + (p.lx1 - p.lx0) * f;
      rv.y = p.ly0 + (p.ly1 - p.ly0) * f;
      rv.hx = p.lhx; rv.hy = p.lhy;
    }
    return f;
  }

  function ridePos(rv, T) {
    const p = rv.p, pts = p.cur.pts;
    const tt = clamp(T - p.lt0, 0, p.cur.d);
    let i = Math.floor(tt / 15);
    if (i > pts.n - 2) i = pts.n - 2;
    if (i < 0) i = 0;
    const fr = (tt - 15 * i) / 15;
    const ax = pts.xs[i], ay = pts.ys[i], bx = pts.xs[i + 1], by = pts.ys[i + 1];
    rv.x = ax + (bx - ax) * fr;
    rv.y = ay + (by - ay) * fr;
    const dx = bx - ax, dy = by - ay, L = Math.sqrt(dx * dx + dy * dy);
    if (L > 0.5) { rv.hx = dx / L; rv.hy = dy / L; }
  }

  // Bring rv.x / rv.y / mode to game time T.
  function place(rv, T) {
    const p = rv.p;
    if (p.state === 0) {
      if (rv.mode === 'cruise') {
        const f = legPos(rv, T);
        if (f >= 1) { rv.mode = 'idle'; p.idleSince = p.lt1; }
      }
    } else if (p.state === 1) {
      legPos(rv, T);
    } else if (p.state === 2) {
      ridePos(rv, T);
    }
  }

  // ---- player ------------------------------------------------------------------------------------
  function playerAt(G, T) {
    const l = G.leg;
    if (l && (G.mode === 'pickup' || G.mode === 'cruise') && l.t1 > l.t0) {
      const f = clamp((T - l.t0) / (l.t1 - l.t0), 0, 1);
      scratchPos.x = l.x0 + (l.x1 - l.x0) * f;
      scratchPos.y = l.y0 + (l.y1 - l.y0) * f;
    } else {
      scratchPos.x = G.x; scratchPos.y = G.y;
    }
    return scratchPos;
  }

  function playerPending(G, o) { return (G.cur === o && G.mode === 'pickup') || G.next === o; }

  // ---- idle destinations ----------------------------------------------------------------------------
  // Sets scratchPos to the spot rv drives to when it has nothing to do; may return the current surge.
  function destination(G, A, rv, T) {
    const id = rv.id, p = rv.p, sh = A.sh;
    const u = mix(p.seed, 100 + p.reposN++);
    const hot = A.hot;
    let tx = 0, ty = 0;
    if (id === 'fatima') {
      const pool = A.stands.length ? A.stands : hot;
      const s = pick(pool, u);
      tx = s.x; ty = s.y;
    } else if (id === 'rui') {
      const h = (sh.startHour + Math.floor(T / 3600)) % 24;
      const night = h >= 22 || h <= 5;
      if (T > 0 && u < (night ? 0.6 : 0.25)) { tx = AIRPORT.x; ty = AIRPORT.y; }
      else { const s = pick(hot, u * 3.7 % 1); tx = s.x; ty = s.y; }
    } else if (id === 'tiago') {
      const pl = playerAt(G, T);
      tx = pl.x + (u - 0.5) * 900; ty = pl.y + (mix(p.seed, 7 + p.reposN) - 0.5) * 900;
    } else if (id === 'lurdes') {
      let s = null;
      const sg = sh.surgesM;
      if (sg && sg.length) {
        for (let i = 0; i < sg.length; i++) {
          if (sg[i].t1 > T && T >= sg[i].t0 - 240) { s = sg[i]; break; }
        }
      }
      if (s) { tx = s.x; ty = s.y; }
      else { const h = hot[Math.min(hot.length, 2) * u | 0]; tx = h.x; ty = h.y; }
    } else if (id === 'nuno') {
      const s = pick(hot, u);
      tx = s.x + (mix(p.seed, 11 + p.reposN) - 0.5) * 1500;
      ty = s.y + (mix(p.seed, 13 + p.reposN) - 0.5) * 1500;
    } else if (id === 'ines') {
      // stays close: the nearest hotspot that is not right here (start: the busiest)
      let b = hot[0], bd = 1e18;
      if (T > 0) {
        for (let i = 0; i < hot.length; i++) {
          const dx = hot[i].x - rv.x, dy = hot[i].y - rv.y;
          const dd = dx * dx + dy * dy;
          if (dd > 90000 && dd < bd) { bd = dd; b = hot[i]; }
        }
      }
      tx = b.x; ty = b.y;
    } else { // ze: busiest spot weighted by distance
      let b = hot[0], bs = -1;
      for (let i = 0; i < hot.length; i++) {
        const dx = hot[i].x - rv.x, dy = hot[i].y - rv.y;
        const sc = hot[i].w / (1 + Math.sqrt(dx * dx + dy * dy) / 3000) * (0.7 + 0.6 * mix(p.seed, 20 + p.reposN + i));
        if (sc > bs) { bs = sc; b = hot[i]; }
      }
      tx = b.x; ty = b.y;
    }
    scratchPos.x = clamp(tx, 0, A.MAP.w);
    scratchPos.y = clamp(ty, 0, A.MAP.h);
  }

  // ---- claims --------------------------------------------------------------------------------------
  // Returns 0 not allowed, 1 free, 2 steal from a rival, 3 steal from the player.
  function claimKind(G, A, o, t1, T) {
    const c = G.claim.get(o.i);
    if (!c) return 1;
    if (c.by === 'player') {
      if (!playerPending(G, o)) return c.t1 > T ? 1 : 0; // released (stale) or already boarded
      return (A.dn !== 'easy' && t1 < c.t1) ? 3 : 0;
    }
    if (c.boarded) return 0;
    return t1 < c.t1 ? 2 : 0;
  }

  // Engine hook: does an existing claim block the player's commit with arrival t1?
  function claimBlocks(G, o, t1) {
    const c = G.claim && G.claim.get(o.i);
    if (!c || c.by === 'player') return false;
    if (c.boarded) return true;
    if (G.ai && G.ai.dn === 'easy') return false; // the shield: a player commit always wins on easy
    return c.t1 <= t1;
  }

  function rivalById(G, id) {
    for (let i = 0; i < G.rivals.length; i++) if (G.rivals[i].id === id) return G.rivals[i];
    return null;
  }

  function lose(G, A, rv, T) {
    const o = rv.target;
    place(rv, T);
    const p = rv.p;
    p.state = 0; p.cur = null; rv.target = null;
    rv.mode = 'idle'; p.idleSince = T;
    p.freeAt = T + 0.5 * reactTime(A, rv);
    p.next = gridUp(p, p.freeAt);
    if (PG.bus) PG.bus.emit('rival:lost', { rival: rv, o: o });
  }

  function toast(G, rv) {
    const text = rv.name + ' ' + (rv.f ? 'випередила' : 'випередив') + ' тебе';
    if (PG.engine && typeof PG.engine.say === 'function') PG.engine.say(text, TOAST_MS);
    else if (PG.bus) PG.bus.emit('note', { text: text, ms: TOAST_MS });
  }

  // ---- decisions ------------------------------------------------------------------------------------
  function scan(G, A, rv, T) {
    const p = rv.p, sh = A.sh, orders = sh.orders, n = orders.length, D = A.D, pers = p.pers;
    const id = rv.id;
    while (p.ptr < n && orders[p.ptr].t < T) p.ptr++;
    const pl = D.near > 0 || id === 'tiago' ? playerAt(G, T) : null;
    const px = pl ? pl.x : 0, py = pl ? pl.y : 0;
    const h = (sh.startHour + Math.floor(T / 3600)) % 24;
    const night = h >= 22 || h <= 5;
    const R0 = pers.react * D.react * (id === 'rui' && night ? 0.7 : 1);
    const Rn = pers.react * D.nearReact * (id === 'rui' && night ? 0.7 : 1);
    const spd = speedAt(A, T);
    const kmK = sh.detour / spd * 3600 * pers.travel / 1000;
    const S = scratchS;
    S.diff = A.dn;
    const sg = sh.surgesM;
    S.live = false;
    if (id === 'lurdes' && sg) {
      for (let j = 0; j < sg.length; j++) if (sg[j].t1 > T && T >= sg[j].t0 - 240) { S.live = true; break; }
    }
    bestO = null; bestScore = -1; bestEta = 0; bestKind = 0;
    const tEnd = T + A.maxLead;
    for (let i = p.ptr; i < n; i++) {
      const o = orders[i];
      if (o.t > tEnd) break;
      const lead = A.lead[o.i];
      const spawn = o.t - lead;
      if (spawn > T) continue;
      const dx = o.x0 - rv.x, dy = o.y0 - rv.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const eta = dist * kmK + A.BOARD;
      if (T + eta > o.t) continue;
      if (G.taken && G.taken.has(o.i)) continue;
      const kind = claimKind(G, A, o, T + eta, T);
      if (kind === 0) continue;
      // perception: which pins does this rival see at all
      let near = false;
      S.pdist = 1e9;
      if (pl) {
        const qx = o.x0 - px, qy = o.y0 - py;
        S.pdist = Math.sqrt(qx * qx + qy * qy);
        near = D.near > 0 && S.pdist <= D.near;
      }
      if (!near && dist > A.RAD[o.c] * D.radius) continue;
      if (id === 'tiago' && A.dn === 'easy') S.pdist = 1e9;
      // surge / airport context
      S.inSurge = false;
      if (id === 'lurdes' && sg && sg.length) {
        for (let j = 0; j < sg.length; j++) {
          const s = sg[j];
          if (o.t >= s.t0 && o.t <= s.t1) {
            const sx = o.x0 - s.x, sy = o.y0 - s.y;
            if (sx * sx + sy * sy <= s.r * s.r) { S.inSurge = true; break; }
          }
        }
      }
      if (id === 'rui') {
        const ax = o.x0 - AIRPORT.x, ay = o.y0 - AIRPORT.y, bx = o.x1 - AIRPORT.x, by = o.y1 - AIRPORT.y;
        S.air = ax * ax + ay * ay <= AIRPORT.r * AIRPORT.r || bx * bx + by * by <= AIRPORT.r * AIRPORT.r;
      }
      // attention gate and reaction delay
      let ready;
      if (near) {
        ready = spawn + NOTICE_K * Rn * (0.8 + 0.4 * mix(p.seed, o.i * 2 + 2));
      } else {
        const at = D.attn * (pers.attn || 1) * (pers.att ? pers.att(o, S, night) : 1);
        if (mix(p.seed, o.i * 2 + 1) >= at) continue;
        ready = spawn + NOTICE_K * R0 * (0.8 + 0.4 * mix(p.seed, o.i * 2 + 2));
      }
      if (ready > T) continue;
      const sc = pers.score(o, eta, S);
      if (sc > bestScore && sc > 0) { bestScore = sc; bestO = o; bestEta = eta; bestKind = kind; }
    }
  }

  function commit(G, A, rv, T, o, eta, kind) {
    const p = rv.p;
    const t1 = T + eta;
    place(rv, T);
    if (kind === 2) {
      const c = G.claim.get(o.i);
      const loser = rivalById(G, c.by);
      c.by = rv.id; c.t1 = t1; c.boarded = false;
      if (loser && loser !== rv) lose(G, A, loser, T);
    } else if (kind === 3) {
      const c = G.claim.get(o.i);
      c.by = rv.id; c.t1 = t1; c.boarded = false;
      if (PG.bus) PG.bus.emit('order:lost', { o: o, by: rv.id });
      toast(G, rv);
    } else {
      const c = G.claim.get(o.i);
      if (c) { c.by = rv.id; c.t1 = t1; c.boarded = false; }
      else G.claim.set(o.i, { by: rv.id, t1: t1, boarded: false });
    }
    startLeg(A, rv, T, o.x0, o.y0, eta);
    p.state = 1; p.cur = o; p.next = t1;
    rv.target = o; rv.mode = 'pickup';
  }

  function startBreak(A, rv, T) {
    const p = rv.p;
    place(rv, T);
    const B = CYCLE * (1 - A.D.duty) * (0.8 + 0.4 * mix(p.seed, 5 + p.reposN++));
    p.state = 3; rv.mode = 'break'; rv.target = null;
    p.breakUntil = T + B;
    p.nextBreak = p.breakUntil + CYCLE * A.D.duty * (0.8 + 0.4 * mix(p.seed, 9 + p.reposN));
    p.next = p.breakUntil;
  }

  function process(G, A, rv, T) {
    const p = rv.p;
    if (p.state === 0) {
      place(rv, T);
      if (T >= p.nextBreak) { startBreak(A, rv, T); return; }
      if (T >= p.freeAt) {
        scan(G, A, rv, T);
        if (bestO) { commit(G, A, rv, T, bestO, bestEta, bestKind); return; }
        // nothing to take: drive somewhere sensible now and then
        let go = T - p.lastRepos >= p.pers.repos;
        if (rv.id === 'lurdes') {
          const sg = A.sh.surgesM;
          if (sg) {
            for (let j = 0; j < sg.length; j++) {
              if (sg[j].t1 > T && T >= sg[j].t0 - 240) {
                const dx = sg[j].x - rv.x, dy = sg[j].y - rv.y;
                if (p.surgeGo !== j || dx * dx + dy * dy > sg[j].r * sg[j].r * 0.25) {
                  if (rv.mode !== 'cruise' || p.surgeGo !== j) go = true;
                  p.surgeGo = j;
                }
                break;
              }
            }
          }
        }
        if (go && T - p.idleSince >= 10) {
          destination(G, A, rv, T);
          const tx = scratchPos.x, ty = scratchPos.y;
          p.lastRepos = T;
          const dx = tx - rv.x, dy = ty - rv.y;
          if (dx * dx + dy * dy > 40000) {
            startLeg(A, rv, T, tx, ty, Math.max(1, driveTime(A, rv, T, rv.x, rv.y, tx, ty)));
            rv.mode = 'cruise';
          }
        }
      }
      p.next = T + GRID;
    } else if (p.state === 1) {
      // pickup
      rv.x = p.lx1; rv.y = p.ly1;
      const o = p.cur;
      rv.total = cents(rv.total + o.fare);
      rv.rides++;
      const c = G.claim.get(o.i);
      if (c && c.by === rv.id) c.boarded = true;
      p.state = 2; rv.mode = 'ride';
      p.lt0 = T; p.lt1 = T + o.d;
      p.next = T + o.d;
      if (PG.bus) PG.bus.emit('rival:pickup', { rival: rv, o: o, fare: o.fare });
    } else if (p.state === 2) {
      const o = p.cur;
      rv.x = o.x1; rv.y = o.y1;
      p.state = 0; p.cur = null; rv.target = null; rv.mode = 'idle';
      p.idleSince = T;
      p.freeAt = T + 0.5 * reactTime(A, rv) * (0.8 + 0.4 * mix(p.seed, 3000 + rv.rides));
      p.next = gridUp(p, Math.max(T, p.freeAt));
    } else { // break over
      p.state = 0; rv.mode = 'idle'; p.idleSince = T;
      p.freeAt = T + 0.3 * reactTime(A, rv);
      p.next = gridUp(p, p.freeAt);
    }
  }

  // ---- hooks -----------------------------------------------------------------------------------------
  function tick(G, t0, t1) {
    const A = G.ai;
    if (!A) return;
    const rs = G.rivals;
    let guard = 200000;
    for (;;) {
      let bi = -1, bt = Infinity;
      for (let i = 0; i < rs.length; i++) {
        if (rs[i].p.next < bt) { bt = rs[i].p.next; bi = i; }
      }
      if (bi < 0 || bt > t1 || --guard < 0) break;
      process(G, A, rs[bi], bt);
    }
    for (let i = 0; i < rs.length; i++) place(rs[i], t1);
  }

  // The engine accepted a player commit on o (the claim already says 'player').
  function onPlayerCommit(G, o) {
    const A = G.ai;
    if (!A) return;
    const rs = G.rivals;
    for (let i = 0; i < rs.length; i++) {
      const rv = rs[i];
      if (rv.p.state === 1 && rv.target === o) lose(G, A, rv, G.t);
    }
  }

  PG.ai = {
    RIVALS: RIVALS, DIFF: DIFF, PERS: PERS,
    init: init, tick: tick, onPlayerCommit: onPlayerCommit,
    claimBlocks: claimBlocks,
  };
})(typeof window !== 'undefined' ? window : globalThis);
