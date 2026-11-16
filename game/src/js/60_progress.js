(function (root) {
  const PG = root.PG = root.PG || {};
  const KEY = 'porto-lanosiv-progress-v1';
  const DIFFS = ['easy', 'normal', 'hard'];
  const DIFF_LABEL = { easy: 'Легко', normal: 'Нормально', hard: 'Важко' };
  const MEDAL_NAME = ['без медалі', 'бронза', 'срібло', 'золото', 'легенда'];
  const PLAYER = { id: 'player', name: 'Ріїн Гіслінг', nick: 'Ти', color: '#3df5b0' };

  const HINTS = [
    'Торкнись світлої точки — побачиш маршрут, ще раз — береш. З мишею: наведи — маршрут, клік — береш.',
    'Ліловий автомобіль — привид: найкращий справжній водій цієї зміни.',
    'Смуга вгорі показує медалі: бронза, срібло, золото, легенда.'
  ];
  const HOWTO = [
    'Світла точка на мапі — замовлення. Торкнись раз — побачиш маршрут, ще раз — береш. З мишею: наведи — маршрут, клік — береш.',
    'Встигни доїхати до початку поїздки, поки точка не згасла; можна бронювати наступну під час поїздки.',
    'Чайові й серія поїздок підряд дають бонус; ×3 прискорює час.',
    'Ліловий автомобіль — привид, найкращий справжній водій зміни. Сім ланосів — ШІ-суперники.',
    'Бронза за зміну відкриває наступну. Усього 28 змін.'
  ];

  const ABOUT = {
    source: 'Джерело: UCI 339, «Taxi Service Trajectory», CC BY 4.0, один тиждень травня 2014.',
    data: ['поїздки', 'водії', 'маршрути', 'привид', 'рейтинг', 'гарячі точки', 'хвилі попиту', 'дорожній граф'],
    dataNote: 'усе пораховано нашим кодом із сирого архіву',
    model: ['тариф 3,25 + 0,50 €/км (×1,2 вночі)', 'час ×40', 'видимість і радіус міток', 'чайові',
      'серія (комбо)', 'типи пасажирів', '7 ланосів (ШІ-суперники)', 'медалі']
  };

  let state = fresh();
  let mem = null;          // in-memory copy when storage is blocked
  let storageOk = true;

  function fresh() {
    return { v: 1, difficulty: 'normal', best: {}, hints: { h1: false, h2: false, h3: false }, coach: false };
  }
  function store() {
    try { return root.localStorage || null; } catch (e) { return null; }
  }
  function sanitize(o) {
    const s = fresh();
    if (!o || typeof o !== 'object') return s;
    if (DIFFS.indexOf(o.difficulty) >= 0) s.difficulty = o.difficulty;
    if (o.best && typeof o.best === 'object') {
      Object.keys(o.best).forEach(function (id) {
        const b = o.best[id];
        if (b && typeof b.earned === 'number' && isFinite(b.earned)) {
          s.best[id] = { medal: (b.medal | 0), earned: b.earned, rank: (b.rank | 0) };
        }
      });
    }
    if (o.hints && typeof o.hints === 'object') {
      ['h1', 'h2', 'h3'].forEach(function (k) { s.hints[k] = !!o.hints[k]; });
    }
    s.coach = o.coach === true;
    return s;
  }
  function load() {
    try {
      const ls = store();
      const raw = ls ? ls.getItem(KEY) : null;
      return raw ? sanitize(JSON.parse(raw)) : fresh();
    } catch (e) { storageOk = false; return mem ? sanitize(mem) : fresh(); }
  }
  function save() {
    mem = JSON.parse(JSON.stringify(state));
    try {
      const ls = store();
      if (ls) ls.setItem(KEY, JSON.stringify(state));
      else storageOk = false;
    } catch (e) { storageOk = false; }
  }

  function shifts() { return (PG.data && PG.data.shifts) || []; }
  function idOf(idx) { const sh = shifts()[idx]; return sh ? sh.id : null; }
  function cents(x) { return Math.round(x * 100); }

  const P = {
    DIFFS: DIFFS, DIFF_LABEL: DIFF_LABEL, MEDAL_NAME: MEDAL_NAME, PLAYER: PLAYER,
    HINTS: HINTS, HOWTO: HOWTO, ABOUT: ABOUT, KEY: KEY,

    init: function () {
      state = load();
      if (PG.engine && PG.engine.config) PG.engine.config.difficulty = state.difficulty;
      return P;
    },
    // test hook: forget everything
    reset: function () { state = fresh(); save(); },
    persistent: function () { return storageOk; },

    isOpen: function (idx) {
      if (idx <= 0) return true;
      const prev = idOf(idx - 1);
      if (prev == null) return idx === 0;
      const b = state.best[prev];
      return !!b && b.medal >= 1;
    },
    best: function (idx) {
      const id = idOf(idx);
      return id != null && state.best[id] ? state.best[id] : null;
    },
    // result = calcResult(); true if a new record (first finish counts)
    record: function (result) {
      if (!result) return false;
      const id = result.shiftId != null ? result.shiftId : idOf(result.idx);
      if (id == null) return false;
      const old = state.best[id];
      const isNew = !old || cents(result.earned) > cents(old.earned);
      if (isNew) {
        state.best[id] = { medal: Math.max(result.medal | 0, old ? old.medal : 0),
          earned: result.earned, rank: result.rank | 0 };
      } else if ((result.medal | 0) > old.medal) {
        old.medal = result.medal | 0;
      }
      save();
      return isNew;
    },
    difficulty: function () { return state.difficulty; },
    setDifficulty: function (d) {
      if (DIFFS.indexOf(d) < 0) return;
      state.difficulty = d;
      if (PG.engine && PG.engine.config) PG.engine.config.difficulty = d;
      save();
    },
    // first open shift without a bronze (the one to play next); last shift when all done
    nextIdx: function () {
      const n = shifts().length;
      for (let i = 0; i < n; i++) {
        const b = state.best[idOf(i)];
        if (!b || b.medal < 1) return P.isOpen(i) ? i : Math.max(0, i - 1);
      }
      return Math.max(0, n - 1);
    },
    // guided first shift (66_coach.js): finished or skipped
    coachDone: function () { return state.coach; },
    setCoachDone: function (v) { state.coach = !!v; save(); },
    hint: function (n) { return !!state.hints['h' + n]; },
    markHint: function (n) {
      if (n >= 1 && n <= 3) { state.hints['h' + n] = true; save(); }
    },

    // ---- thin helpers for 65_screens.js ----
    // card view for the shift list: {open, medal, medalName, earned, rank, hasBest, next}
    cardView: function (idx) {
      const b = P.best(idx);
      return { open: P.isOpen(idx), hasBest: !!b, medal: b ? b.medal : 0,
        medalName: MEDAL_NAME[b ? b.medal : 0], earned: b ? b.earned : 0,
        rank: b ? b.rank : 0, next: idx === P.nextIdx() };
    },
    // index the «Грати» button starts (always an open shift)
    playIdx: function () { return P.nextIdx(); },
    // call BEFORE record(); then after record() use the same object
    // -> {record, bestEarned, bestMedal, placeText, race}
    resultView: function (result, G) {
      const hasNext = result.idx + 1 < shifts().length;
      const wasOpen = hasNext && P.isOpen(result.idx + 1);
      const rec = P.record(result);
      const b = P.best(result.idx);
      return { record: rec, recordText: rec ? 'новий рекорд' : '',
        bestEarned: b ? b.earned : result.earned, bestMedal: b ? b.medal : result.medal,
        placeText: P.placeText(result), race: P.raceTable(G, result),
        unlockedNext: hasNext && !wasOpen && P.isOpen(result.idx + 1), nextIdx: P.nextIdx() };
    },
    placeText: function (r) {
      if (!r || !(r.raceSize > 1) || !(r.racePlace >= 1)) return '';
      return r.racePlace + '-е місце серед ' + r.raceSize + ' таксі на мапі';
    },
    // rows sorted by € desc: {id, name, nick, color, total, rides, player}; ties keep the player first
    raceTable: function (G, result) {
      const rows = [{ id: PLAYER.id, name: PLAYER.name, nick: PLAYER.nick, color: PLAYER.color,
        total: result ? result.earned : (G ? G.tot : 0), rides: result ? result.rides : (G ? G.rides : 0),
        player: true }];
      const rv = G && G.rivals ? G.rivals : [];
      for (let i = 0; i < rv.length; i++) {
        rows.push({ id: rv[i].id, name: rv[i].name, nick: rv[i].nick, color: rv[i].color,
          total: rv[i].total, rides: rv[i].rides, player: false });
      }
      if (rows.length < 2) return [];
      rows.sort(function (a, b) {
        const d = cents(b.total) - cents(a.total);
        return d || (b.player ? 1 : 0) - (a.player ? 1 : 0);
      });
      return rows;
    },
    // onboarding: first shift only, one hint at a time, in order, each when its subject is on screen.
    // ctx {pin, ghost, bar} booleans -> {n, text} or null. The caller shows it and calls markHint(n).
    hintsActive: function () { return Object.keys(state.best).length === 0; },
    hintDue: function (ctx) {
      if (!ctx || !P.hintsActive()) return null;
      const vis = [ctx.pin, ctx.ghost, ctx.bar];
      for (let n = 1; n <= 3; n++) {
        if (P.hint(n)) continue;
        return vis[n - 1] ? { n: n, text: HINTS[n - 1] } : null;
      }
      return null;
    }
  };
  PG.progress = P;
})(typeof window !== 'undefined' ? window : globalThis);
