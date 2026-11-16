/* 68_shop.js: «ОЛЕКС», the skin shop (a parody of a classifieds site). Look only: the engine is not touched.
   The wallet is the sum of € earned over all shifts (spent on purchases). It adds its own menu button. */
(function (root) {
  const PG = root.PG = root.PG || {};

  const KEY = 'porto-lanosiv-shop-v1';
  const HOLD_MS = 700;                 // long-press on the wallet: demo unlock
  const PHOTO = { w: 360, h: 170, car: 190 };
  const ITEMS = [
    { id: 'lanos', price: 0, title: 'Ланос б/у', tag: '1500 $, торг, не бита (майже)', who: 'Ви, Ріїн · Порту · у гаражі',
      desc: 'Торг доречний. Фара одна, зате світить за двох. Двері від різних машин, скло трішки трісло, димить символічно.' },
    { id: 'matiz', price: 30, title: 'Матіз, один власник (я)', who: 'Дарія · Алфама · сьогодні',
      desc: 'Паркується там, де інші навіть не дивляться. У салоні ялинка, теж від власника.' },
    { id: 'porto', price: 60, title: 'Порту класик, чорний із зеленим дахом', who: 'Дона Фатіма · Рібейра · 2 год тому',
      desc: 'Дід возив на ній туристів ще в 80-х. Салон пахне кавою і шкірою, а лічильник досі рахує в ескудо.' },
    { id: 'golf', price: 90, title: 'Гольф, вічний, майже не іржавіє', who: 'Мігел · Гайя · 2 дні тому',
      desc: 'Німецька якість, португальський пробіг. Двері зачиняються з першого разу, іноді.' },
    { id: 'nyc', price: 120, title: 'Жовте таксі з Нью-Йорка, шашечки в комплекті', who: 'Руй · Матозіньюш · вчора',
      desc: 'Приїхала контейнером, принаймні так каже продавець. Ліхтар на даху працює, шашечки рідні.' },
    { id: 'rickshaw', price: 160, title: 'Рікша, три колеса, жодного дзеркала', who: 'Сатіш · Порту · 5 хв тому',
      desc: 'Пролазить туди, куди іншим не можна. Дах із бахромою, гудок із характером.' },
    { id: 'cab', price: 200, title: 'Лондонський кеб, парасолька в бардачку', who: 'Тіаго · Фош · сьогодні',
      desc: 'Розвертається на семи метрах. Дощ у комплекті, а от на сонце не розраховуйте.' },
    { id: 'electro', price: 320, title: 'Електро, їде тихо як миша', who: 'Нуну · Боавішта · 3 год тому',
      desc: 'Клієнти лякаються, бо не чують, як він під’їхав. Емблем немає, не питайте.' },
    { id: 'horse', price: 500, title: 'Кінь з возом, їсть овес, не бензин', who: 'Лурдеш · Кампаньян · щойно', top: true,
      desc: 'Заводиться з морквини. Пробок не боїться, на світлофорі нервує. Подушка на возі м’яка.' }
  ];

  const st = { earned: 0, spent: 0, owned: { lanos: 1 }, skin: 'lanos' };   // money in cents
  let dom = null;

  function store() { try { return root.localStorage || null; } catch (e) { return null; } }

  function load() {
    try {
      const ls = store();
      const raw = ls ? JSON.parse(ls.getItem(KEY) || 'null') : null;
      if (!raw) return;
      st.earned = Math.max(0, raw.earned | 0);
      st.spent = Math.max(0, raw.spent | 0);
      if (raw.owned) for (const k in raw.owned) if (byId(k)) st.owned[k] = 1;
      if (byId(raw.skin) && st.owned[raw.skin]) st.skin = raw.skin;
    } catch (e) { /* a broken save is ignored */ }
  }

  function save() {
    try { const ls = store(); if (ls) ls.setItem(KEY, JSON.stringify(st)); } catch (e) { /* storage is full or off */ }
  }

  function byId(id) { for (let i = 0; i < ITEMS.length; i++) if (ITEMS[i].id === id) return ITEMS[i]; return null; }
  function wallet() { return (st.earned - st.spent) / 100; }
  function owned(id) { return !!st.owned[id]; }
  function need(id) { const it = byId(id); return it ? Math.max(0, Math.ceil(it.price - wallet() - 1e-9)) : 0; }

  function earn(x) {
    if (!(x > 0) || !isFinite(x)) return;
    st.earned += Math.round(x * 100);
    save();
  }

  function pick(id) {
    if (!owned(id)) return false;
    st.skin = id;
    if (PG.cars) PG.cars.setSkin(id);
    save();
    return true;
  }

  function buy(id) {
    const it = byId(id);
    if (!it || owned(id) || need(id) > 0) return false;
    st.spent += it.price * 100;
    st.owned[id] = 1;
    return pick(id);
  }

  function unlockAll() {
    ITEMS.forEach(function (it) { st.owned[it.id] = 1; });
    save();
  }

  // ---- DOM ----
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function photo(it) {
    const cv = el('canvas', 'olx-photo');
    cv.width = PHOTO.w * 2; cv.height = PHOTO.h * 2;
    cv.setAttribute('role', 'img');
    cv.setAttribute('aria-label', it.title);
    const c = cv.getContext('2d');
    if (!c) return cv;
    const css = root.getComputedStyle(dom.root);
    c.scale(2, 2);
    c.fillStyle = css.getPropertyValue('--s-photo').trim() || '#565b64';
    c.fillRect(0, 0, PHOTO.w, PHOTO.h);
    c.fillStyle = css.getPropertyValue('--s-lane').trim() || '#e9e6dc';
    for (let x = 0; x < PHOTO.w; x += 44) c.fillRect(x, PHOTO.h - 22, 26, 4);   // lane marks
    if (PG.cars) PG.cars.paint(c, it.id, PHOTO.w / 2, PHOTO.h / 2 - 6, PHOTO.car, '#3df5b0');
    return cv;
  }

  function card(it) {
    const mine = owned(it.id), on = mine && st.skin === it.id, n = need(it.id);
    const a = el('article', 'olx-ad');
    a.setAttribute('data-skin', it.id);
    const ph = el('div', 'olx-ph');
    ph.appendChild(photo(it));
    if (it.top) ph.appendChild(el('span', 'olx-top', 'ТОП'));
    a.appendChild(ph);
    const b = el('div', 'olx-body');
    const row = el('div', 'olx-row');
    row.appendChild(el('h3', 'olx-name', it.title));
    row.appendChild(el('span', 'olx-price' + (it.tag ? ' own' : ''), it.tag || PG.util.eur(it.price)));
    b.appendChild(row);
    b.appendChild(el('p', 'olx-who', it.who));
    b.appendChild(el('p', 'olx-desc', it.desc));
    if (!mine && n > 0) {
      const bar = el('div', 'olx-need');
      const fill = el('i');
      fill.style.width = Math.min(100, Math.round(100 * Math.max(0, wallet()) / it.price)) + '%';
      bar.appendChild(fill);
      b.appendChild(bar);
    }
    const act = el('button', 'olx-btn ' + (on ? 'on' : mine || n === 0 ? 'buy' : 'no'),
      on ? 'Обрано' : mine ? 'Обрати' : n === 0 ? 'Купити' : 'Не вистачає ' + PG.util.eur(n));
    act.type = 'button';
    act.disabled = on || (!mine && n > 0);
    act.addEventListener('click', function () { if (!mine) buy(it.id); else pick(it.id); refresh(); });
    b.appendChild(act);
    a.appendChild(b);
    return a;
  }

  function refresh() {
    if (!dom) return;
    dom.wal.textContent = PG.util.eur(wallet());
    dom.ads.textContent = '';
    ITEMS.forEach(function (it) { dom.ads.appendChild(card(it)); });
    updateButton();
  }

  function updateButton() {
    if (typeof document === 'undefined') return;
    const b = document.getElementById('btn-shop');
    if (b) b.querySelector('.olx-open-wal').textContent = PG.util.eur(wallet());
  }

  function build() {
    const r = el('div'); r.id = 'shop'; r.hidden = true;
    r.setAttribute('role', 'dialog'); r.setAttribute('aria-label', 'ОЛЕКС');
    const head = el('div', 'olx-head');
    const top = el('div', 'olx-topbar');
    const back = el('button', 'olx-back', '‹'); back.type = 'button'; back.setAttribute('aria-label', 'Назад');
    back.addEventListener('click', close);
    top.appendChild(back);
    top.appendChild(el('div', 'olx-logo', 'ОЛЕКС'));
    const w = el('div', 'olx-wal');
    w.appendChild(el('small', '', 'Гаманець'));
    const wal = el('b', '', PG.util.eur(wallet()));
    w.appendChild(wal);
    let hold = 0;                                   // long-press on the wallet: «Демо: відкрити все»
    const stop = function () { if (hold) { clearTimeout(hold); hold = 0; } };
    w.addEventListener('pointerdown', function () {
      stop();
      hold = setTimeout(function () {
        hold = 0; unlockAll(); refresh();
        if (PG.bus) PG.bus.emit('note', { text: 'Демо: відкрито все', ms: 2200 });
      }, HOLD_MS);
    });
    ['pointerup', 'pointerleave', 'pointercancel'].forEach(function (ev) { w.addEventListener(ev, stop); });
    w.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    top.appendChild(w);
    head.appendChild(top);
    head.appendChild(el('div', 'olx-q', 'Шукаю авто для зміни'));
    r.appendChild(head);
    const chips = el('div', 'olx-chips');
    ['Усе', 'З рук', 'Дивне'].forEach(function (t, i) { chips.appendChild(el('span', i ? '' : 'on', t)); });
    r.appendChild(chips);
    const ads = el('div', 'olx-ads');
    r.appendChild(ads);
    (document.getElementById('app') || document.body).appendChild(r);
    dom = { root: r, wal: wal, ads: ads };
  }

  function open() {
    if (typeof document === 'undefined') return;
    if (!dom) build();
    refresh();
    dom.root.hidden = false;
    dom.root.scrollTop = 0;
  }

  function close() {
    if (dom) dom.root.hidden = true;
    updateButton();
  }

  // The menu button: added once the menu is on the screen, and its wallet refreshed on every return.
  function ensureButton() {
    const m = document.getElementById('menu');
    if (!m) return;
    if (!document.getElementById('btn-shop')) {
      const b = el('button', 'btn-big alt');
      b.id = 'btn-shop'; b.type = 'button';
      b.appendChild(el('span', 'olx-open-name', 'ОЛЕКС'));
      b.appendChild(el('span', 'olx-open-wal'));
      b.addEventListener('click', open);
      const after = document.getElementById('party-note') || document.getElementById('btn-party');
      if (after && after.parentNode === m) m.insertBefore(b, after.nextSibling); else m.appendChild(b);
    }
    updateButton();
  }

  load();
  if (PG.cars) PG.cars.setSkin(st.skin);
  PG.shop = {
    ITEMS: ITEMS, KEY: KEY, wallet: wallet, owned: owned, need: need, earn: earn, buy: buy, pick: pick,
    unlockAll: unlockAll, skin: function () { return st.skin; }, open: open, close: close
  };
  if (PG.bus) {
    PG.bus.on('shift:end', function (e) { if (e && e.result) { earn(e.result.earned); updateButton(); } });
    PG.bus.on('ui:screen', function (e) {
      if (typeof document === 'undefined' || !e) return;
      if (e.name === 'menu') ensureButton();
      if (e.name !== 'menu') close();
    });
  }
})(typeof window !== 'undefined' ? window : globalThis);
