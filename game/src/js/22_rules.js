(function (root) {
  const PG = root.PG = root.PG || {};

  const RATE = { regular: 0.05, tourist: 0.15, vip: 0.30, rush: 0.10 };
  const COMBO_WINDOW = 300;         // game s from the previous drop-off to the next pickup
  const COMBO_K = [1.0, 1.0, 1.1, 1.2, 1.3];

  // FNV-1a 32 bit over the UTF-8 bytes of a string.
  function fnv1a32(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
      let c = str.charCodeAt(i);
      if (c >= 0xd800 && c <= 0xdbff && i + 1 < str.length) {
        const d = str.charCodeAt(i + 1);
        if (d >= 0xdc00 && d <= 0xdfff) { c = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00); i++; }
      }
      if (c < 0x80) {
        h = Math.imul(h ^ c, 16777619) >>> 0;
      } else if (c < 0x800) {
        h = Math.imul(h ^ (0xc0 | (c >> 6)), 16777619) >>> 0;
        h = Math.imul(h ^ (0x80 | (c & 63)), 16777619) >>> 0;
      } else if (c < 0x10000) {
        h = Math.imul(h ^ (0xe0 | (c >> 12)), 16777619) >>> 0;
        h = Math.imul(h ^ (0x80 | ((c >> 6) & 63)), 16777619) >>> 0;
        h = Math.imul(h ^ (0x80 | (c & 63)), 16777619) >>> 0;
      } else {
        h = Math.imul(h ^ (0xf0 | (c >> 18)), 16777619) >>> 0;
        h = Math.imul(h ^ (0x80 | ((c >> 12) & 63)), 16777619) >>> 0;
        h = Math.imul(h ^ (0x80 | ((c >> 6) & 63)), 16777619) >>> 0;
        h = Math.imul(h ^ (0x80 | (c & 63)), 16777619) >>> 0;
      }
    }
    return h >>> 0;
  }

  function kindFor(shiftId, i) {
    const u = fnv1a32(shiftId + '#' + i) / 4294967296;
    return u < 0.70 ? 'regular' : u < 0.80 ? 'tourist' : u < 0.88 ? 'vip' : 'rush';
  }

  function curG() { return PG.engine && PG.engine.G ? PG.engine.G : null; }

  // Kind of an order, cached on the order (an order belongs to one shift).
  function kindOf(o) {
    if (o._kind) return o._kind;
    const G = curG();
    if (!G || !G.sh) return 'regular';
    const k = kindFor(G.sh.id, o.i);
    o._kind = k;
    return k;
  }

  function leadK(o) { return kindOf(o) === 'rush' ? 0.6 : 1; }

  // Game time of the event being processed: the end of the current leg when
  // known (the engine may process a long step at once), else G.t.
  function evT(G) {
    const l = G.leg;
    return l && isFinite(l.t1) ? l.t1 : G.t;
  }

  function comboK(n) { return n >= 4 ? COMBO_K[4] : COMBO_K[n < 1 ? 1 : n]; }
  function cents(x) { return Math.round(x * 100) / 100; }

  function reset(G) {
    G.tips = 0; G.combo = 0; G.bestCombo = 0; G.lastDropT = -1e9;
  }

  const bus = PG.bus;
  if (bus) {
    bus.on('dropoff', function (p) {
      const G = curG();
      const o = p.o;
      const fare = p.fare != null ? p.fare : o.fare;
      const k = G ? comboK(G.combo || 0) : 1;
      const tip = cents((fare * RATE[kindOf(o)] + fare * (k - 1)) * (PG.engine && PG.engine.tuneK ? PG.engine.tuneK('tips') : 1));
      p.tip = tip;
      if (G) {
        G.tips = cents((G.tips || 0) + tip);
        G.lastDropT = evT(G);
      }
    });

    bus.on('shift:start', function () {
      const G = curG();
      if (G) reset(G);
    });

    bus.on('pickup', function () {
      const G = curG();
      if (!G) return;
      const t = G.leg.t0;           // the engine has already started the ride: its start is the pickup
      const prevN = G.combo || 0;
      if (prevN > 0 && t <= G.lastDropT + COMBO_WINDOW) {
        G.combo = prevN + 1;
        if (G.combo > (G.bestCombo || 0)) G.bestCombo = G.combo;
        bus.emit('combo', { n: G.combo, k: comboK(G.combo) });
      } else {
        if (prevN >= 2) bus.emit('combo:break', { n: prevN });
        G.combo = 1;
        if (G.bestCombo < 1) G.bestCombo = 1;
        bus.emit('combo', { n: 1, k: 1.0 });
      }
    });
  }

  PG.rules = { kindOf, leadK, _fnv1a32: fnv1a32, _kindFor: kindFor, _comboK: comboK };
})(typeof window !== 'undefined' ? window : globalThis);
