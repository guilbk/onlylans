/* 80_party.js: «Гра разом», rooms of friends on one map; the server decides order claims (CONTRACT §15). */
(function (root) {
  const PG = root.PG = root.PG || {};
  const doc = root.document;
  const qs = new URLSearchParams(root.location.search);
  const SCREEN = qs.get('screen') === '1';   // the clean spectator view for a projector
  const POLL_MS = 200, BACKOFF_MAX = 2000, HANG_MS = 3000;   // the server may set `poll_ms`
  const KEY = 'party-session';
  const JSON_TYPE = { 'Content-Type': 'application/json' };
  const MAP_W = 15000, MAP_H = 19000;
  const DELAY = 0.35;        // s, other cars are drawn this far behind the server time, between two samples
  const EXTRA = 0.25;        // s, how far a car may be extrapolated when the next sample is late
  const FIRST_SLOT = 10, SLOTS = 22;   // PG.cars heading slots 0-9 belong to the rivals, ghost and hero

  let on = false;            // the party UI was started on this page
  let snap = null;           // last server state
  let me = null;             // {room, key, id, token?}
  let room = '';             // room code
  let started = false;       // the shift was set up on this page
  let mode = '';             // what the overlay shows
  let ui = {};               // refs of the current overlay
  const hud = {};            // board, mini board and QR (they live as long as the page)
  let offset = 0, bestRtt = 1e9, lastDraw = 0, link = '';
  const cars = new Map();    // player id -> [{t, x, y}] samples on the server clock
  const others = new Set();  // order ids this page put into G.taken (claimed by other players)
  const pending = new Set(); // order ids with a claim in flight
  const stage = () => doc.getElementById('stage');
  const nowS = () => root.performance.now() / 1000;
  const srvNow = () => nowS() + offset;
  const E = () => PG.engine;
  const G = () => PG.engine.G;
  const eur = (x) => PG.util.eur(x);
  const ranked = () => snap.players.slice().sort((a, b) => b.money - a.money);
  const isHost = () => !!me && !!me.token;
  const TOP = 10;            // the big screen names and lists this many cars
  const FEED_S = 7;          // s, a live-feed line stays this long
  const LAST_S = 30;         // s, the final countdown
  let feed = [], prev = null, hover = null;

  /** Own car (skin id and mods) for the other screens; the server passes it through. */
  const look = () => ({ skin: PG.cars.skin(), mods: PG.cars.mods() });

  function el(tag, cls, text, parent) {
    const e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  function btn(text, parent, fn, cls) {
    const b = el('button', cls || 'pty-btn', text, parent);
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  }

  /** JSON call; resolves {ok, status, data}. A sample of the clock offset is taken from every reply. */
  function api(path, body) {
    const t0 = nowS();
    const init = body === undefined ? {} : { method: 'POST', headers: JSON_TYPE, body: JSON.stringify(Object.assign({ room: room }, body)) };
    if (root.AbortSignal && root.AbortSignal.timeout) init.signal = root.AbortSignal.timeout(HANG_MS);   // a stalled server counts as lost
    return root.fetch(path + (body === undefined ? '?room=' + room : ''), init).then(function (r) {
      return r.json().then(function (data) {
        const t1 = nowS();
        if (data && typeof data.now === 'number' && t1 - t0 <= bestRtt * 1.5 + 0.02) {
          bestRtt = Math.min(bestRtt, t1 - t0);
          offset = data.now - (t0 + t1) / 2;
        }
        return { ok: r.ok, status: r.status, data: data };
      });
    });
  }

  const gameClock = () => (srvNow() - snap.start_at) * PG.C.SHIFT / snap.duration;

  // ---- the overlay: entry, lobby, countdown ----
  function show(m, build) {
    if (m === mode) return;
    const box = doc.getElementById('party');
    mode = m;
    ui = {};
    box.textContent = '';
    box.hidden = !build;
    box.classList.toggle('count', m.indexOf('count') === 0);
    if (build) build(el('div', 'pty-card', undefined, box));
  }

  function save(name) {
    root.sessionStorage.setItem(KEY, JSON.stringify({ room: room, key: me.key, id: me.id, token: me.token, name: name }));
    root.history.replaceState(null, '', '?room=' + room);
  }

  const LOOK = { 'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M', 'Н': 'H', 'О': 'O', 'Р': 'P', 'С': 'C', 'Т': 'T', 'Х': 'X', 'І': 'I' };
  /** Room code as the server reads it: upper case, no spaces, Cyrillic look-alikes turned Latin. */
  function normCode(s) {
    return String(s || '').toUpperCase().replace(/\s+/g, '').replace(/[АВЕКМНОРСТХІ]/g, function (c) { return LOOK[c]; });
  }

  /** Create or join a room; on success the poll takes over and shows the lobby. */
  function enter(path, body, name) {
    ui.err.textContent = '';
    if (body.room) body.room = normCode(body.room);
    Object.assign(body, look());
    return root.fetch(path, { method: 'POST', headers: JSON_TYPE, body: JSON.stringify(body) }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) { ui.err.textContent = ({ no_room: 'Такого лобі немає', phase: 'Гру вже завершено', full: 'Лобі заповнене', busy: 'Забагато лобі' })[d.error] || 'Не вдалося'; return; }
        room = normCode(d.room || body.room);
        me = { key: d.key, id: d.id, token: d.token };
        save(name);
        onState(d.state);
        startPoll();
      });
    }).catch(function () { ui.err.textContent = 'Немає зв’язку з сервером гри. «Гра разом» працює, коли гру відкрито з ноутбука ведучого.'; });
  }

  function buildEntry(fixed) {
    return function (card) {
      el('h1', null, fixed ? 'Лобі ' + fixed : 'Гра разом', card);
      el('p', null, fixed ? 'Тебе запросили. Введи ім’я й заходь.' : 'Грайте разом на одній мапі: хто перший забрав замовлення, той і поїхав.', card);
      const name = el('input', 'pty-input', undefined, card);
      name.maxLength = 20;
      name.placeholder = 'Твоє ім’я';
      name.value = PG.util.playerName();
      name.setAttribute('aria-label', 'Твоє ім’я');
      if (!fixed) btn('Створити лобі', card, function () { enter('/api/create', { name: name.value }, name.value); });
      if (!fixed) el('p', 'pty-sub', 'або долучись за кодом', card);
      const code = fixed ? null : el('input', 'pty-input pty-codein', undefined, card);
      if (code) {
        code.maxLength = 4;
        code.placeholder = 'КОД';
        code.setAttribute('autocapitalize', 'characters');
        code.setAttribute('aria-label', 'Код лобі');
      }
      btn('Приєднатися', card, function () { enter('/api/join', { room: fixed || code.value, name: name.value }, name.value); }, fixed ? 'pty-btn' : 'pty-btn alt');
      ui.err = el('p', 'pty-err', '', card);
      if (!fixed) btn('Назад', card, function () { show('', null); }, 'pty-btn ghost');
    };
  }

  function fillList(list) {
    list.textContent = '';
    snap.players.forEach(function (p) {
      const row = el('div', 'pty-row' + (p.online ? '' : ' off'), undefined, list);
      el('i', 'pty-dot', undefined, row).style.background = p.color;
      el('span', 'pty-name', p.name + (me && p.id === me.id ? ' (ти)' : ''), row);
      if (p.id === snap.host) el('span', 'pty-tag', 'ведучий', row);
    });
  }

  function drawQr(canvas, rows) {
    const n = rows.length, cell = 6, quiet = 4, size = (n + 2 * quiet) * cell;
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = '#000';
    rows.forEach(function (row, y) {
      for (let x = 0; x < n; x++) if (row[x] === '1') ctx.fillRect((x + quiet) * cell, (y + quiet) * cell, cell, cell);
    });
  }

  function qrInto(canvas, urlEl) {
    api('/api/qr').then(function (r) {
      link = r.data.url || '';
      if (urlEl && 'value' in urlEl) urlEl.value = link;
      else if (urlEl) urlEl.textContent = link;
      if (r.data.rows && r.data.rows.length) drawQr(canvas, r.data.rows);
    }).catch(function () {});
  }

  /** The system share sheet where there is one (it needs https on phones); else copy the link. */
  function share(b) {
    if (root.navigator.share) { root.navigator.share({ title: 'Таксі: гра разом', text: 'Заходь у лобі ' + room, url: link }).catch(function () {}); return; }
    ui.url.select();
    let ok = false;
    try { ok = doc.execCommand('copy'); } catch (err) { ok = false; }
    b.textContent = ok ? 'Посилання скопійовано' : 'Скопіюй посилання вище';
  }

  function hostControls(card) {
    const P = PG.progress, shifts = PG.data.shifts;
    el('label', 'pty-label', 'Зміна', card);
    const sel = el('select', 'pty-input', undefined, card);
    shifts.forEach(function (sh, i) {
      const slot = PG.C.SLOTS[sh.slot];
      el('option', null, sh.name + (slot ? ' · ' + slot.label : ''), sel).value = String(i);
    });
    el('label', 'pty-label', 'Складність', card);
    const dif = el('div', 'pty-seg', undefined, card);
    let diff = 'normal';
    P.DIFFS.forEach(function (d) {
      const b = btn(P.DIFF_LABEL[d], dif, function () {
        diff = d;
        Array.prototype.forEach.call(dif.children, function (c) { c.classList.toggle('on', c === b); });
      }, 'pty-seg-btn' + (d === diff ? ' on' : ''));
    });
    btn('Старт', card, function () {
      api('/api/start', { token: me.token, shift: +sel.value, difficulty: diff, duration: PG.C.SHIFT / PG.C.BASE_SCALE })
        .then(function (r) { if (!r.ok) ui.err.textContent = 'Не вдалося почати'; });
    });
    ui.err = el('p', 'pty-err', '', card);
  }

  function buildLobby(card) {
    el('h1', null, 'Лобі', card);
    ui.code = el('div', 'pty-code', room, card);
    const row = el('div', 'pty-share', undefined, card);
    const qr = el('canvas', 'pty-qr', undefined, row);
    const side = el('div', 'pty-col', undefined, row);
    ui.url = el('input', 'pty-url', undefined, side);
    ui.url.readOnly = true;
    ui.url.setAttribute('aria-label', 'Посилання');
    const sh = btn('Поділитися', side, function () { share(sh); }, 'pty-btn alt');
    qrInto(qr, ui.url);
    ui.head = el('p', 'pty-sub', '', card);
    ui.list = el('div', 'pty-list', undefined, card);
    if (isHost()) hostControls(card);
    else el('p', 'pty-wait', 'Чекаємо на ведучого. Тримай телефон вертикально.', card);
  }

  function buildScreenLobby(card) {
    card.classList.add('wide');
    el('h1', null, 'Гра разом', card);
    const cols = el('div', 'pty-cols', undefined, card);
    const left = el('div', 'pty-col', undefined, cols);
    el('p', 'pty-sub', 'Скануйте код, щоб приєднатися', left);
    const qr = el('canvas', 'pty-qr', undefined, left);
    ui.url = el('p', 'pty-link', '', left);
    qrInto(qr, ui.url);
    const right = el('div', 'pty-col', undefined, cols);
    el('div', 'pty-code', room, right);
    ui.head = el('p', 'pty-sub', '', right);
    ui.list = el('div', 'pty-list', undefined, right);
  }

  function leave() {
    root.sessionStorage.removeItem(KEY);
    root.location.href = root.location.pathname;
  }

  // ---- the shift ----
  function begin() {
    started = true;
    if (SCREEN) return;
    const e = E();
    e.config.difficulty = snap.difficulty;
    e.party = { clock: gameClock };
    e.newGame(Math.min(snap.shift, PG.data.shifts.length - 1));
    PG.screens.setScreen('play');
    installClaims(e);
  }

  const nameOf = (id) => (snap.players.find(function (p) { return p.id === id; }) || {}).name || 'інший гравець';

  /** The server gave the order to somebody else: take the booking back and remember it as taken. */
  function lose(o, by) {
    G().taken.add(o.i);
    others.add(o.i);
    E().unbook(o);
    E().say('Вже забрав ' + by);
  }

  /** Booking is instant on the phone; the server confirms in the background and a loss is rolled back. */
  function installClaims(e) {
    const orig = { pick: e.startPickup, book: e.bookNext, cruise: e.cruiseTo };
    const release = (o) => api('/api/release', { key: me.key, order: o.i });

    function take(o, act) {
      const g = G();
      if (!g || g.over) return false;
      if (snap && snap.start_at - srvNow() > 0) { e.say('Зачекай на старт'); return false; }   // the server refuses (409) a claim during the countdown
      if (pending.has(o.i)) return true;
      const prev = g.mode === 'ride' ? g.next : g.cur;
      if (!act(o)) return false;
      pending.add(o.i);
      if (prev && prev !== o) release(prev);
      api('/api/claim', { key: me.key, order: o.i }).then(function (r) {
        pending.delete(o.i);
        if (r.data.ok === false) lose(o, r.data.by);
        else if (!r.data.ok) { e.unbook(o); e.say('Не вдалося забрати'); }
      }, function () { pending.delete(o.i); e.unbook(o); e.say('Немає зв’язку'); });
      return true;
    }
    e.startPickup = (o) => take(o, orig.pick);
    e.bookNext = (o) => take(o, orig.book);
    e.cruiseTo = function (x, y) {
      const prev = G() && G().mode === 'pickup' ? G().cur : null;
      const ok = orig.cruise(x, y);
      if (ok && prev) release(prev);
      return ok;
    };
  }

  /** Orders other players claimed leave the pins of this phone; claims they gave back return; a lost race is rolled back. */
  function syncTaken() {
    const g = G();
    if (!g) return;
    const now = new Set();
    Object.keys(snap.claims).forEach(function (k) { if (snap.claims[k] !== me.id) now.add(+k); });
    now.forEach(function (i) { if (!g.taken.has(i)) { g.taken.add(i); others.add(i); } });
    others.forEach(function (i) { if (!now.has(i) && !pending.has(i)) { g.taken.delete(i); others.delete(i); } });
    [g.mode === 'pickup' ? g.cur : null, g.next].forEach(function (o) {
      if (o && now.has(o.i) && !pending.has(o.i)) lose(o, nameOf(snap.claims[o.i]));
    });
  }

  function syncBody() {
    const g = started && !SCREEN ? G() : null;
    if (!g) return { key: me.key };
    return Object.assign({ key: me.key }, { x: Math.round(g.x), y: Math.round(g.y), hx: g.hx, hy: g.hy, money: g.tot, trips: g.rides });
  }

  // ---- other cars: samples on the server clock, drawn a little behind it so they glide ----
  function follow(players) {
    players.forEach(function (p) {
      if (p.x === null) return;
      const s = cars.get(p.id) || [];
      cars.set(p.id, s);
      if (!s.length || s[s.length - 1].t !== p.at) { s.push({ t: p.at, x: p.x, y: p.y }); if (s.length > 8) s.shift(); }
    });
  }

  function carAt(s, t) {
    const n = s.length;
    if (n < 2 || t <= s[0].t) return s[0];
    if (t >= s[n - 1].t) {
      const a = s[n - 2], b = s[n - 1], k = Math.min(t - b.t, EXTRA) / Math.max(b.t - a.t, 0.05);
      return { x: b.x + (b.x - a.x) * k, y: b.y + (b.y - a.y) * k };
    }
    let i = 1;
    while (s[i].t < t) i++;
    const a = s[i - 1], b = s[i], k = (t - a.t) / Math.max(b.t - a.t, 1e-3);
    return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k };
  }

  const skinOk = (id) => PG.cars.SKINS.some(function (k) { return k.id === id; });
  const look1 = (p) => (skinOk(p.skin) ? [p.skin, p.mods && typeof p.mods === 'object' ? p.mods : null] : [undefined, undefined]);

  /** Name tags that never overlap: the top TOP cars and the hovered one, each tries a few spots around its car. */
  function placeLabel(ctx, x, y, len, w, h, taken) {
    const gap = len * 0.55, spots = [[0, -gap - h], [0, gap], [0, -gap - 2.1 * h], [0, gap + h * 1.1], [w / 2 + len * 0.6, -h / 2], [-w / 2 - len * 0.6, -h / 2]];
    for (let k = 0; k < spots.length; k++) {
      const r = { x: x + spots[k][0] - w / 2, y: y + spots[k][1], w: w, h: h };
      if (!taken.some(function (t) { return r.x < t.x + t.w && r.x + r.w > t.x && r.y < t.y + t.h && r.y + r.h > t.y; })) { taken.push(r); return r; }
    }
    return null;
  }

  function drawCars(ctx) {
    if (!snap || !started) return;
    const dt = Math.min(0.1, nowS() - lastDraw), W = stage().clientWidth, t = srvNow() - DELAY;
    lastDraw = nowS();
    // phones: the size of the hero; the projector: big, readable from the back of the room
    const len = SCREEN ? Math.max(40, W * 0.03) : PG.render.carLen('hero'), fs = Math.round(SCREEN ? len * 0.42 : 11);
    ctx.font = '700 ' + fs + 'px system-ui, sans-serif';
    ctx.textAlign = 'center';
    const order = SCREEN ? ranked() : [], taken = [], seen = [];
    snap.players.forEach(function (p, i) {
      const s = cars.get(p.id);
      if (!s || (me && p.id === me.id)) return;
      const c = carAt(s, t), a = PG.cars.turn(FIRST_SLOT + i % SLOTS, p.hx, p.hy, dt, false);
      const q = PG.render.P(c.x, c.y), x = q.x, y = q.y, alpha = p.online ? 1 : 0.4, lk = look1(p);
      if (x < -60 || y < -60 || x > W + 60 || y > stage().clientHeight + 60) return;
      PG.cars.draw(ctx, x, y, a, len, p.color, alpha, 'rival', lk[0], lk[1]);
      seen.push({ p: p, x: x, y: y, alpha: alpha });
    });
    // labels after all cars: the leaders first, so they get the best spots; the rest are dots on the car
    const rank = (p) => order.indexOf(p);
    const list = SCREEN ? seen.slice().sort(function (a, b) { return rank(a.p) - rank(b.p); }) : seen;
    list.forEach(function (c) {
      const p = c.p, top = !SCREEN || rank(p) < TOP || (hover && Math.hypot(hover.x - c.x, hover.y - c.y) < len * 0.7);
      ctx.globalAlpha = c.alpha;
      const w = top ? ctx.measureText(p.name).width + fs * 0.7 : 0, h = fs * 1.3;
      const r = top ? placeLabel(ctx, c.x, c.y, len, w, h, taken) : null;
      if (r) {
        ctx.fillStyle = PG.theme.pal.card;
        ctx.fillRect(r.x, r.y, r.w, r.h);
        ctx.fillStyle = p.color;
        ctx.fillText(p.name, r.x + r.w / 2, r.y + h * 0.75);
      } else if (SCREEN) {
        ctx.fillStyle = p.color;
        ctx.strokeStyle = PG.theme.pal.card;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(c.x, c.y - len * 0.7, fs * 0.3, 0, 7);
        ctx.fill();
        ctx.stroke();
      }
    });
    ctx.globalAlpha = 1;
  }

  // ---- scoreboards: the projector's, the phone's mini board, the result block ----
  function board() {
    if (!hud.board) {
      hud.board = el('aside', 'pty-board', undefined, doc.getElementById('app'));
      hud.title = el('h2', null, '', hud.board);
      hud.time = el('div', 'pty-time', '', hud.board);
      hud.last = el('div', 'pty-last', '', doc.getElementById('app'));
      hud.rows = el('div', 'pty-rows', undefined, hud.board);
      hud.more = el('p', 'pty-more', '', hud.board);
      hud.feed = el('div', 'pty-feed', undefined, hud.board);
      const foot = el('div', 'pty-foot', undefined, hud.board);
      el('p', 'pty-sub', 'Долучайся за кодом ' + room, foot);
      qrInto(el('canvas', 'pty-qr small', undefined, foot));
    }
    hud.title.textContent = snap.phase === 'done' ? 'Фінал' : PG.data.shifts[snap.shift].name;
    hud.rows.textContent = '';
    const list = ranked(), n = list.length;
    list.slice(0, TOP).forEach(function (p, i) {
      const row = el('div', 'pty-row' + (p.online ? '' : ' off'), undefined, hud.rows);
      el('span', 'pty-pos', String(i + 1), row);
      el('i', 'pty-dot', undefined, row).style.background = p.color;
      el('span', 'pty-name', p.name, row);
      el('span', 'pty-trips', String(p.trips), row);
      el('b', 'pty-eur', eur(p.money), row);
    });
    hud.more.textContent = n + ' ' + PG.util.plural(n, 'гравець', 'гравці', 'гравців') + (n > TOP ? ' · ще ' + (n - TOP) + ' нижче' : '');
    showFeed();
  }

  function showFeed() {
    const keep = feed.filter(function (f) { return nowS() - f.at < FEED_S; });
    if (keep.length === feed.length && hud.feed.childNodes.length === keep.length) return;
    feed = keep;
    hud.feed.textContent = '';
    feed.forEach(function (f) { el('div', 'pty-feed-row', f.text, hud.feed); });
  }

  /** The live feed: who earned and who overtook whom, from two consecutive states. */
  function feedFrom(s) {
    const order = s.players.slice().sort(function (a, b) { return b.money - a.money; }), now = nowS(), pos = {};
    order.forEach(function (p, i) { pos[p.id] = i; });
    if (prev) {
      const add = [];
      order.forEach(function (p) {
        const o = prev.money[p.id];
        if (o === undefined) return;
        if (p.money - o >= 1) add.push(p.name + ': +' + eur(p.money - o));
        const j = pos[p.id] + 1, under = order[j];
        if (under && prev.pos[under.id] !== undefined && prev.pos[p.id] > prev.pos[under.id] && j < order.length) add.push(p.name + ' випереджає ' + under.name);
      });
      add.forEach(function (text) { feed.push({ text: text, at: now }); });
    }
    prev = { money: {}, pos: pos };
    order.forEach(function (p) { prev.money[p.id] = p.money; });
    feed = feed.slice(-4);
  }

  /** The end on the projector: the podium for the top 3 with their cars, then the full table. */
  function buildPodium(card) {
    card.classList.add('wide', 'final');
    el('h1', null, 'Фінал', card);
    const list = ranked(), pod = el('div', 'pty-podium', undefined, card);
    [1, 0, 2].forEach(function (i) {
      const p = list[i];
      if (!p) return;
      const col = el('div', 'pty-pl pl' + (i + 1), undefined, pod), cv = el('canvas', 'pty-pcar', undefined, col), lk = look1(p);
      cv.width = 240;
      cv.height = 120;
      PG.cars.paint(cv.getContext('2d'), lk[0], 120, 60, 150, p.color, lk[1] || {});
      el('b', 'pty-pname', p.name, col);
      el('span', 'pty-peur', eur(p.money), col);
      el('div', 'pty-step', String(i + 1), col);
    });
    const tab = el('div', 'pty-table', undefined, card);
    list.forEach(function (p, i) {
      const row = el('div', 'pty-row', undefined, tab);
      el('span', 'pty-pos', String(i + 1), row);
      el('i', 'pty-dot', undefined, row).style.background = p.color;
      el('span', 'pty-name', p.name, row);
      el('span', 'pty-trips', String(p.trips), row);
      el('b', 'pty-eur', eur(p.money), row);
    });
  }

  const myRank = () => { const l = ranked(); return 'Ти — #' + (l.findIndex(function (p) { return p.id === me.id; }) + 1) + ' з ' + l.length; };

  /** Top 3 and you, on the phone. */
  function mini() {
    const m = hud.mini || (hud.mini = el('div', 'pty-mini', undefined, doc.getElementById('app')));
    const list = ranked(), at = list.findIndex(function (p) { return p.id === me.id; });
    const rows = list.slice(0, 3);
    if (at > 2) rows.push(list[at]);
    m.textContent = '';
    el('div', 'pty-rank', '#' + (at + 1) + ' з ' + list.length, m);
    rows.forEach(function (p) {
      const i = list.indexOf(p), row = el('div', 'pty-mrow' + (p.id === me.id ? ' me' : ''), undefined, m);
      el('span', 'pty-pos', String(i + 1), row);
      el('i', 'pty-dot', undefined, row).style.background = p.color;
      el('span', 'pty-name', p.name, row);
      el('b', 'pty-eur', eur(p.money), row);
    });
  }

  function resultBlock() {
    const res = doc.getElementById('result');
    let box = doc.getElementById('party-race');
    if (!box) {
      box = el('div', 'res-race');
      box.id = 'party-race';
      res.insertBefore(box, res.querySelector('.res-buttons'));
    }
    box.textContent = '';
    el('h2', null, 'Перегони гравців', box);
    el('p', 'pty-myrank', myRank(), box);
    ranked().forEach(function (p) {
      const row = el('div', 'race-row' + (p.id === me.id ? ' me' : ''), undefined, box);
      el('i', 'race-dot', undefined, row).style.background = p.color;
      el('span', 'race-name', p.name, row);
      el('span', 'race-rides', String(p.trips), row);
      el('span', 'race-total', eur(p.money), row);
    });
    const bar = el('div', 'pty-bar', undefined, box);
    if (isHost()) btn('Ще раз', bar, function () { api('/api/reset', { token: me.token }); });
    else el('p', 'pty-sub', 'Ведучий почне нову гру', bar);
    btn('Вийти', bar, leave, 'pty-btn ghost');
  }

  // ---- one server reply ----
  function onState(s) {
    snap = s;
    follow(s.players);
    if (s.phase === 'lobby') {
      if (started) { root.location.reload(); return; }
      show('lobby', SCREEN ? buildScreenLobby : buildLobby);
    } else if (!started) begin();
    if (ui.head) ui.head.textContent = s.players.length + ' ' + PG.util.plural(s.players.length, 'гравець', 'гравці', 'гравців');
    if (ui.list) fillList(ui.list);
    if (!started) return;
    if (SCREEN) { feedFrom(s); board(); }
    else {
      syncTaken();
      mini();
      if (PG.screen === 'result') resultBlock();
    }
  }

  /** The map fills the screen (no empty band); the camera follows the cars, left of the leaderboard. */
  const cam = { s: 0, x: 0, y: 0 };
  function screenCamera() {
    const v = PG.render.view, st = stage(), W = st.clientWidth, H = st.clientHeight;
    const pw = hud.board ? hud.board.offsetWidth + 12 : 0, cover = Math.max(W / MAP_W, H / MAP_H) * 1.02;
    const live = snap.players.filter(function (p) { return p.x !== null && p.online; });
    let ts = cover, tx = MAP_W / 2, ty = MAP_H / 2;
    if (live.length) {
      const xs = live.map(function (p) { return p.x; }), ys = live.map(function (p) { return p.y; });
      const x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
      const fit = Math.min((W - pw) * 0.6 / Math.max(x1 - x0, 3000), H * 0.6 / Math.max(y1 - y0, 3000));
      ts = Math.min(Math.max(cover, fit), cover * 3);
      tx = (x0 + x1) / 2; ty = (y0 + y1) / 2;
    }
    const k = cam.s ? 0.06 : 1;   // the first frame jumps, then the camera eases
    cam.s += (ts - cam.s) * k;
    cam.x += (tx - cam.x) * k;
    cam.y += (ty - cam.y) * k;
    v.scale = cam.s;
    v.cx = Math.min(Math.max(cam.x + pw / 2 / cam.s, W / 2 / cam.s), MAP_W - W / 2 / cam.s);
    v.cy = Math.min(Math.max(cam.y, H / 2 / cam.s), MAP_H - H / 2 / cam.s);
  }

  function frame() {
    if (!snap || !started) return;
    if (snap.phase === 'done') {
      if (SCREEN && mode !== 'podium') show('podium', buildPodium);
      return;
    }
    const left = snap.start_at - srvNow();
    const count = left > 0 ? String(Math.ceil(left)) : '';
    if (mode !== 'count:' + count) show('count:' + count, count ? function (card) { el('div', 'pty-count', count, card); } : null);
    if (SCREEN) {
      screenCamera();
      if (hud.time) {
        const r = Math.max(0, Math.ceil(snap.start_at + snap.duration - srvNow()));
        hud.time.textContent = Math.floor(r / 60) + ':' + String(r % 60).padStart(2, '0');
        hud.time.classList.toggle('last', r > 0 && r <= LAST_S);
        hud.last.textContent = r > 0 && r <= LAST_S ? String(r) : '';
        hud.last.hidden = !hud.last.textContent;
        showFeed();
      }
    }
  }

  let polling = false;
  function startPoll() {
    if (!polling) { polling = true; poll(); }
  }

  let pollMs = POLL_MS, wait = 0;   // wait: the back-off after errors, 0 when the link is fine
  function reach(ok) {
    wait = ok ? 0 : Math.min(BACKOFF_MAX, (wait || pollMs) * 2);
    if (!ok && !hud.lost) { hud.lost = el('div', 'pty-lost', 'Перепідключення…', doc.getElementById('app')); }
    if (hud.lost) hud.lost.hidden = ok;
  }

  /** One request at a time: the next poll starts only after the last answer (or error) plus the pause. */
  function poll() {
    const t0 = nowS();
    const req = me ? api('/api/sync', syncBody()) : api('/api/party');
    req.then(function (r) {
      if (r.status === 403 || (r.status === 404 && me)) { leave(); return; }
      if (r.status === 404 && !me) { ui.err && (ui.err.textContent = 'Такого лобі немає'); return; }
      if (r.ok) {
        if (r.data.poll_ms >= 50 && r.data.poll_ms <= 2000) pollMs = r.data.poll_ms;
        onState(r.data);
      }
      reach(r.ok || r.status < 500);
    }).catch(function () { reach(false); }).then(function () { root.setTimeout(poll, Math.max(wait, pollMs - (nowS() - t0) * 1000)); });
  }

  /** Start the party UI: resume a saved room, open the room from the link, or ask what to do. */
  function activate() {
    if (on) return;
    on = true;
    doc.body.classList.add('party', SCREEN ? 'party-screen' : 'party-player');
    const box = el('div', null, undefined, doc.getElementById('app'));
    box.id = 'party';
    box.setAttribute('data-no-map', '');
    box.hidden = true;
    PG.render.onDraw(drawCars, 3);
    PG.bus.on('frame', frame);
    PG.bus.on('ui:screen', function (e) {
      if (!started || SCREEN) return;
      if (e.name === 'menu' && !G().over) PG.screens.setScreen('play');
      if (e.name === 'result') resultBlock();
    });
    const code = normCode(qs.get('room'));
    const saved = JSON.parse(root.sessionStorage.getItem(KEY) || 'null');
    if (SCREEN) {
      room = code;
      stage().addEventListener('pointermove', function (e) { const b = stage().getBoundingClientRect(); hover = { x: e.clientX - b.left, y: e.clientY - b.top }; });
      stage().addEventListener('pointerleave', function () { hover = null; });
      startPoll();
      return;
    }
    if (saved && (!code || normCode(saved.room) === code)) {
      room = normCode(saved.room);
      me = { key: saved.key, id: saved.id, token: saved.token };
      startPoll();
    } else show('entry:' + code, buildEntry(code));
  }

  const ready = (fn) => (doc.readyState === 'loading' ? doc.addEventListener('DOMContentLoaded', fn) : fn());
  PG.bus.on('party:open', function () { ready(function () { activate(); if (!me && !SCREEN) show('entry:', buildEntry('')); }); });
  if (qs.get('party') === '1' || qs.get('room') || SCREEN) ready(activate);
})(typeof window !== 'undefined' ? window : globalThis);
