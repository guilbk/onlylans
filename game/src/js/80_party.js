/* 80_party.js: party mode (?party=1), one map for everybody; the server decides order claims (CONTRACT §15). */
(function (root) {
  const PG = root.PG = root.PG || {};
  const doc = root.document;
  const qs = new URLSearchParams(root.location.search);
  if (qs.get('party') !== '1') return;

  const HOST = qs.get('host') === '1';
  const POLL_MS = 500;
  const KEY = 'party-key';
  const MAP_W = 15000, MAP_H = 19000;
  const SMOOTH = 6;          // 1/s, how fast other cars follow the server positions

  let snap = null;           // last server state
  let me = null;             // {id, key}
  let started = false;       // the shift was set up on this page
  let mode = '';             // what the overlay shows
  let ui = {};               // refs of the current overlay
  const hud = {};            // board, time and chip elements (they live as long as the page)
  let offset = 0, bestRtt = 1e9, lastDraw = 0;
  const cars = new Map();    // player id -> smoothed {x, y, hx, hy}
  const others = new Set();  // order ids this page put into G.taken (claimed by other players)
  const pending = new Set(); // order ids with a claim in flight
  const stage = () => doc.getElementById('stage');
  const nowS = () => root.performance.now() / 1000;
  const srvNow = () => nowS() + offset;
  const E = () => PG.engine;
  const G = () => PG.engine.G;

  function el(tag, cls, text, parent) {
    const e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  /** JSON call; resolves {ok, status, data}. A sample of the clock offset is taken from every reply. */
  function api(path, body) {
    const t0 = nowS();
    const init = body === undefined ? undefined : { method: 'POST', body: JSON.stringify(body) };
    return root.fetch(path, init).then(function (r) {
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

  const gameClock = () => (srvNow() - snap.start_at) * PG.C.BASE_SCALE;
  const eur = (x) => PG.util.eur(x);
  const ranked = () => snap.players.slice().sort((a, b) => b.money - a.money);

  // ---- the overlay: name entry, lobby, host setup, countdown ----
  function show(m, build) {
    if (m === mode) return;
    const box = doc.getElementById('party');
    mode = m;
    ui = {};
    box.textContent = '';
    box.hidden = !build;
    if (build) build(el('div', 'pty-card', undefined, box));
  }

  function fillList(list) {
    list.textContent = '';
    snap.players.forEach(function (p) {
      const row = el('div', 'pty-row' + (p.online ? '' : ' off'), undefined, list);
      el('i', 'pty-dot', undefined, row).style.background = p.color;
      el('span', 'pty-name', p.name, row);
    });
  }

  function listHead(n) {
    return n + ' ' + PG.util.plural(n, 'гравець', 'гравці', 'гравців');
  }

  /** Joins (or rejoins with the key saved in this tab); the name is only used for a new player. */
  function join(name, key) {
    return api('/api/join', { name: name, key: key }).then(function (r) {
      if (!r.ok) { if (ui.err) ui.err.textContent = r.status === 409 ? 'Гру вже завершено' : 'Не вдалося приєднатися'; return; }
      me = { id: r.data.id, key: r.data.key };
      root.sessionStorage.setItem(KEY, JSON.stringify({ key: me.key, name: name }));
    });
  }

  function buildJoin(card) {
    el('h1', null, 'Гра разом', card);
    el('p', null, 'Усі грають на одній мапі. Хто перший забрав замовлення, той і поїхав.', card);
    ui.name = el('input', 'pty-input', undefined, card);
    ui.name.maxLength = 20;
    ui.name.value = 'Таксист ' + (snap.players.length + 1);
    ui.name.setAttribute('aria-label', 'Твоє ім’я');
    ui.name.addEventListener('focus', function () { ui.name.select(); });
    const go = el('button', 'pty-btn', 'Приєднатися', card);
    go.type = 'button';
    ui.err = el('p', 'pty-err', '', card);
    go.addEventListener('click', function () { join(ui.name.value, null); });
  }

  function buildLobby(card) {
    el('h1', null, 'Чекаємо на старт', card);
    ui.head = el('p', 'pty-sub', '', card);
    ui.list = el('div', 'pty-list', undefined, card);
    el('p', 'pty-wait', 'Ведучий скоро почне. Тримай телефон вертикально.', card);
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

  function buildSetup(card) {
    const P = PG.progress, shifts = PG.data.shifts;
    card.classList.add('wide');
    el('h1', null, 'Гра разом', card);
    const cols = el('div', 'pty-cols', undefined, card);
    const left = el('div', 'pty-col', undefined, cols);
    el('p', 'pty-sub', 'Скануйте код, щоб приєднатися', left);
    const qr = el('canvas', 'pty-qr', undefined, left);
    ui.url = el('p', 'pty-url', '', left);
    api('/api/qr').then(function (r) {
      ui.url.textContent = r.data.url;
      if (r.data.rows.length) drawQr(qr, r.data.rows);
    });
    const right = el('div', 'pty-col', undefined, cols);
    ui.head = el('p', 'pty-sub', '', right);
    ui.list = el('div', 'pty-list', undefined, right);
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
      const b = el('button', 'pty-seg-btn' + (d === diff ? ' on' : ''), P.DIFF_LABEL[d], dif);
      b.type = 'button';
      b.addEventListener('click', function () {
        diff = d;
        Array.prototype.forEach.call(dif.children, function (c) { c.classList.toggle('on', c === b); });
      });
    });
    const go = el('button', 'pty-btn', 'Старт', card);
    go.type = 'button';
    ui.err = el('p', 'pty-err', '', card);
    go.addEventListener('click', function () {
      api('/api/start', { shift: +sel.value, difficulty: diff, duration: PG.C.SHIFT / PG.C.BASE_SCALE })
        .then(function (r) { if (!r.ok) ui.err.textContent = 'Не вдалося почати'; });
    });
  }

  function message(text) {
    return function (card) { el('h1', null, text, card); };
  }

  // ---- the shift ----
  function begin() {
    started = true;
    if (HOST) return;
    const e = E();
    e.config.difficulty = snap.difficulty;
    e.party = { clock: gameClock };
    e.newGame(Math.min(snap.shift, PG.data.shifts.length - 1));
    PG.screens.setScreen('play');
    installClaims(e);
  }

  /** The server decides: the claim goes first, the engine action follows only when it is ours. */
  function installClaims(e) {
    const orig = { pick: e.startPickup, book: e.bookNext, cruise: e.cruiseTo };
    const release = (o) => api('/api/release', { key: me.key, order: o.i });

    function run(o) {
      const g = G(), riding = g.mode === 'ride', prev = riding ? g.next : g.cur;
      const ok = !g.over && (riding ? orig.book(o) : orig.pick(o));
      if (!ok) release(o);
      else if (prev && prev !== o) release(prev);
    }

    function take(o, first) {
      if (!G() || G().over || !e.reachable(o)) return first(o);   // the engine says why not
      if (pending.has(o.i)) return true;
      pending.add(o.i);
      api('/api/claim', { key: me.key, order: o.i }).then(function (r) {
        pending.delete(o.i);
        if (r.data.ok) { run(o); return; }
        if (r.data.ok === false) { G().taken.add(o.i); others.add(o.i); e.say('Вже забрав ' + r.data.by); }
        else e.say('Не вдалося забрати');
      }, function () { pending.delete(o.i); e.say('Немає зв’язку'); });
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

  /** Orders other players claimed leave the pins of this phone; claims they gave back return. */
  function syncTaken() {
    const g = G();
    if (!g) return;
    const now = new Set();
    Object.keys(snap.claims).forEach(function (k) { if (snap.claims[k] !== me.id) now.add(+k); });
    now.forEach(function (i) { if (!g.taken.has(i)) { g.taken.add(i); others.add(i); } });
    others.forEach(function (i) { if (!now.has(i) && !pending.has(i)) { g.taken.delete(i); others.delete(i); } });
  }

  function syncBody() {
    const g = started && !HOST ? G() : null;
    if (!g) return { key: me.key };
    return { key: me.key, x: Math.round(g.x), y: Math.round(g.y), hx: g.hx, hy: g.hy, money: g.tot, trips: g.rides };
  }

  // ---- other cars ----
  function follow(players) {
    players.forEach(function (p) {
      if (p.x !== null && !cars.has(p.id)) cars.set(p.id, { x: p.x, y: p.y, hx: p.hx, hy: p.hy });
    });
  }

  function drawCars(ctx) {
    if (!snap || !started) return;
    const R = PG.render, k = 1 - Math.exp(-Math.min(0.1, nowS() - lastDraw) * SMOOTH), big = HOST;
    lastDraw = nowS();
    const len = big ? 22 : 17, wid = big ? 12 : 9;
    ctx.font = (big ? '600 13px ' : '600 11px ') + 'system-ui, sans-serif';
    ctx.textAlign = 'center';
    snap.players.forEach(function (p) {
      const c = cars.get(p.id);
      if (!c || (me && p.id === me.id)) return;
      c.x += (p.x - c.x) * k; c.y += (p.y - c.y) * k; c.hx += (p.hx - c.hx) * k; c.hy += (p.hy - c.hy) * k;
      const q = R.P(c.x, c.y), x = q.x, y = q.y;
      if (x < -40 || y < -40 || x > root.innerWidth + 40 || y > root.innerHeight + 40) return;
      ctx.globalAlpha = p.online ? 1 : 0.4;
      ctx.fillStyle = p.color;
      ctx.beginPath();
      ctx.arc(x, y, len, 0, 6.2832);
      ctx.globalAlpha *= 0.18;
      ctx.fill();
      ctx.globalAlpha = p.online ? 1 : 0.4;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(Math.atan2(c.hy, c.hx));
      ctx.fillRect(-len / 2, -wid / 2, len, wid);
      ctx.fillStyle = 'rgba(7,11,20,0.75)';
      ctx.fillRect(len * 0.1, -wid / 2 + 1.5, len * 0.22, wid - 3);
      ctx.restore();
      const w = ctx.measureText(p.name).width + 8;
      ctx.fillStyle = 'rgba(7,11,20,0.75)';
      ctx.fillRect(x - w / 2, y - len - 14, w, 15);
      ctx.fillStyle = p.color;
      ctx.fillText(p.name, x, y - len - 3);
    });
    ctx.globalAlpha = 1;
  }

  // ---- scoreboards: the host's big one, the phone's chip, the result block ----
  function board() {
    const b = hud.board || (hud.board = el('aside', 'pty-board', undefined, doc.getElementById('app')));
    b.textContent = '';
    const done = snap.phase === 'done';
    el('h2', null, done ? 'Фінал' : PG.data.shifts[snap.shift].name, b);
    hud.time = el('div', 'pty-time', '', b);
    ranked().forEach(function (p, i) {
      const row = el('div', 'pty-row' + (p.online ? '' : ' off'), undefined, b);
      el('span', 'pty-pos', String(i + 1), row);
      el('i', 'pty-dot', undefined, row).style.background = p.color;
      el('span', 'pty-name', p.name, row);
      el('span', 'pty-trips', String(p.trips), row);
      el('b', 'pty-eur', eur(p.money), row);
    });
    if (done) {
      const again = el('button', 'pty-btn', 'Нова гра', b);
      again.type = 'button';
      again.addEventListener('click', function () {
        api('/api/reset', {}).then(function () { root.location.reload(); });
      });
    }
  }

  function chip() {
    const c = hud.chip || (hud.chip = el('div', 'pty-chip', '', doc.getElementById('app')));
    const list = ranked(), i = list.findIndex(function (p) { return p.id === me.id; });
    c.textContent = '#' + (i + 1) + ' з ' + list.length + ' · ' + list[0].name + ' ' + eur(list[0].money);
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
    ranked().forEach(function (p) {
      const row = el('div', 'race-row' + (me && p.id === me.id ? ' me' : ''), undefined, box);
      el('i', 'race-dot', undefined, row).style.background = p.color;
      el('span', 'race-name', p.name, row);
      el('span', 'race-rides', String(p.trips), row);
      el('span', 'race-total', eur(p.money), row);
    });
  }

  // ---- one server reply ----
  function onState(s) {
    snap = s;
    follow(s.players);
    if (s.phase === 'lobby') {
      if (started) { root.location.reload(); return; }
      if (HOST) show('setup', buildSetup);
      else if (me) show('lobby', buildLobby);
      else show('join', buildJoin);
    } else if (!started && (HOST || me)) begin();
    else if (!started) {
      if (s.phase === 'done') show('over', message('Гру завершено. Чекай новий раунд'));
      else show('join', buildJoin);
    }
    if (ui.head) ui.head.textContent = listHead(s.players.length);
    if (ui.list) fillList(ui.list);
    if (!started) return;
    if (HOST) board();
    else {
      syncTaken();
      chip();
      if (PG.screen === 'result') resultBlock();
    }
  }

  function frame() {
    if (!snap || !started) return;
    const left = snap.start_at - srvNow();
    const count = left > 0 ? String(Math.ceil(left)) : '';
    if (mode !== 'count:' + count) show('count:' + count, count ? function (card) { el('div', 'pty-count', count, card); } : null);
    if (HOST) {
      const v = PG.render.view, s = stage(), pw = Math.min(420, s.clientWidth * 0.34);
      v.scale = Math.min((s.clientWidth - pw) / MAP_W, s.clientHeight / MAP_H);
      v.cx = MAP_W / 2 + pw / 2 / v.scale;
      v.cy = MAP_H / 2;
      if (hud.time) {
        const r = Math.max(0, Math.ceil(snap.start_at + snap.duration - srvNow()));
        hud.time.textContent = snap.phase === 'done' ? '' : Math.floor(r / 60) + ':' + String(r % 60).padStart(2, '0');
      }
    }
  }

  function poll() {
    const req = me ? api('/api/sync', syncBody()) : api('/api/party');
    req.then(function (r) {
      if (r.status === 403) { root.sessionStorage.removeItem(KEY); root.location.reload(); }
      else if (r.ok) onState(r.data);
    }).catch(function () {}).then(function () { root.setTimeout(poll, POLL_MS); });
  }

  function init() {
    doc.body.classList.add('party', HOST ? 'party-host' : 'party-player');
    const box = el('div', null, undefined, doc.getElementById('app'));
    box.id = 'party';
    box.setAttribute('data-no-map', '');
    box.hidden = true;
    PG.render.onDraw(drawCars, 3);
    PG.bus.on('frame', frame);
    PG.bus.on('ui:screen', function (e) {
      if (!started || HOST) return;
      if (e.name === 'menu' && !G().over) PG.screens.setScreen('play');
      if (e.name === 'result') resultBlock();
    });
    const saved = HOST ? null : JSON.parse(root.sessionStorage.getItem(KEY) || 'null');
    (saved ? join(saved.name, saved.key) : Promise.resolve()).catch(function () {}).then(poll);
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init);
  else init();
})(typeof window !== 'undefined' ? window : globalThis);
