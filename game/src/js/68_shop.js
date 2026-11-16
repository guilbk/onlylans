/* 68_shop.js: «ОЛХ», the skin and tuning marketplace (a parody of a classifieds site). Look only: the engine is not touched.
   The wallet is the sum of € earned over all shifts (spent on purchases). It adds its own menu button. */
(function (root) {
  const PG = root.PG = root.PG || {};

  const KEY = 'porto-lanosiv-shop-v1';
  const HOLD_MS = 700;                 // long-press on the wallet: demo unlock
  const PHOTO = { w: 360, h: 170, car: 190 };
  const ITEMS = [
    { id: 'lanos', price: 0, cur: '1500 $', torg: true, title: 'Ланос 2007, 1500 $, торг, не бита (майже)',
      who: 'Ви, Ріїн · Порту · у гаражі', date: '3 травня 2014',
      desc: 'Торг доречний. Фара одна, зате світить за двох. Двері від різних машин, скло трішки трісло, димить символічно.' },
    { id: 'matiz', price: 30, title: 'Матіз, один власник (я)', who: 'Дарія · Алфама · на сайті з 2012', date: '16 травня 2014',
      desc: 'Паркується там, де інші навіть не дивляться. У салоні ялинка, теж від власника.' },
    { id: 'porto', price: 60, torg: true, title: 'Порту класик, чорний із зеленим дахом', who: 'Дона Фатіма · Рібейра · не дзвоніть до обіду',
      date: '15 травня 2014',
      desc: 'Дід возив на ній туристів ще в 80-х. Салон пахне кавою і шкірою, а лічильник досі рахує в ескудо.' },
    { id: 'golf', price: 90, torg: true, title: 'Гольф, вічний, майже не іржавіє', who: 'Мігел · Гайя · пише лише голосовими',
      date: '14 травня 2014',
      desc: 'Німецька якість, португальський пробіг. Двері зачиняються з першого разу, іноді.' },
    { id: 'nyc', price: 120, torg: true, title: 'Жовте таксі з Нью-Йорка, шашечки в комплекті',
      who: 'Руй · Матозіньюш · «брат привіз контейнером»', date: '17 травня 2014',
      desc: 'Приїхала контейнером, принаймні так каже продавець. Ліхтар на даху працює, шашечки рідні.' },
    { id: 'rickshaw', price: 160, title: 'Рікша, три колеса, жодного дзеркала', who: 'Сатіш · Порту · відповідає дзвінком на дзвінок',
      date: '18 травня 2014',
      desc: 'Пролазить туди, куди іншим не можна. Дах із бахромою, гудок із характером.' },
    { id: 'cab', price: 200, torg: true, title: 'Лондонський кеб, парасолька в бардачку', who: 'Тіаго · Фош · не поспішає, і вам не раджу',
      date: '13 травня 2014',
      desc: 'Розвертається на семи метрах. Дощ у комплекті, а от на сонце не розраховуйте.' },
    { id: 'electro', price: 320, title: 'Електро, їде тихо як миша', who: 'Нуну · Боавішта · пише тихо, їздить ще тихіше',
      date: '16 травня 2014',
      desc: 'Клієнти лякаються, бо не чують, як він під’їхав. Емблем немає, не питайте.' },
    { id: 'horse', price: 500, torg: true, top: true, title: 'Кінь з возом, їсть овес, не бензин',
      who: 'Лурдеш · Кампаньян · лише дзвінки, з шостої ранку', date: '18 травня 2014',
      desc: 'Заводиться з морквини. Пробок не боїться, на світлофорі нервує. Подушка на возі м’яка. Торг за моркву.' }
  ];

  // Cosmetic extras: look only. They show on the listing photo; the map car has no hook for them.
  const TUNING = [
    { id: 'taxi', price: 14, title: 'Шашка TAXI на дах, світиться', who: 'Жозе · склад біля порту · шашки з різних міст',
      date: '12 травня 2014', desc: 'Клієнти бачать здалеку. Чи сядуть, то вже їхня справа.' },
    { id: 'stickers', price: 9, torg: true, title: 'Наклейки «Полум’я», комплект на два боки',
      who: 'Беатріш · друкарня на розі · гарантія до першої мийки', date: '10 травня 2014',
      desc: 'Швидкість не додають, зате додають упевненості. Клеїти на суху і чисту, тобто не на Ланос.' },
    { id: 'rims', price: 24, title: 'Литі диски, блищать навіть у дощ', who: 'Дієґу · Гайя · диски блищать, власник теж',
      date: '9 травня 2014', desc: 'Колеса ті самі, видно їх тепер здалеку. Обіцяти, що їх не зніме хтось інший, не буду.' },
    { id: 'tree', price: 4, title: 'Ялинка-ароматизатор «Новий салон»', who: 'Кіоск «Пахне» · ринок Болья · без здачі',
      date: '8 травня 2014', desc: 'Пахне новою машиною, поки не відчинять вікно. Висить на дзеркалі, тримається міцно.' },
    { id: 'garland', price: 11, title: 'Гірлянда на лобове, лишилась після Різдва',
      who: 'Інеш · Порту · «у травні вже ні для чого»', date: '11 травня 2014',
      desc: 'Блимає без причини. У нічну зміну видно, що ви їдете, хоча й не завжди куди.' }
  ];

  const st = { earned: 0, spent: 0, owned: { lanos: 1 }, skin: 'lanos', tune: {}, fit: {} };   // money in cents
  const flt = { cat: 'all', max: 500, can: false, q: '' };   // the listing filter (not saved)
  const MAXP = 500;
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
      if (raw.tune) for (const k in raw.tune) if (tuneById(k)) st.tune[k] = 1;
      if (raw.fit) for (const k in raw.fit) if (tuneById(k) && st.tune[k] && raw.fit[k]) st.fit[k] = 1;
    } catch (e) { /* a broken save is ignored */ }
  }

  function save() {
    try { const ls = store(); if (ls) ls.setItem(KEY, JSON.stringify(st)); } catch (e) { /* storage is full or off */ }
  }

  function byId(id) { for (let i = 0; i < ITEMS.length; i++) if (ITEMS[i].id === id) return ITEMS[i]; return null; }
  function tuneById(id) { for (let i = 0; i < TUNING.length; i++) if (TUNING[i].id === id) return TUNING[i]; return null; }
  function wallet() { return (st.earned - st.spent) / 100; }
  function owned(id) { return !!st.owned[id]; }
  function ownedTune(id) { return !!st.tune[id]; }
  function fitted(id) { return !!st.fit[id]; }
  function lack(it) { return it ? Math.max(0, Math.ceil(it.price - wallet() - 1e-9)) : 0; }
  function need(id) { return lack(byId(id)); }
  function needTune(id) { return lack(tuneById(id)); }

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

  function buyTune(id) {
    const it = tuneById(id);
    if (!it || ownedTune(id) || needTune(id) > 0) return false;
    st.spent += it.price * 100;
    st.tune[id] = 1;
    st.fit[id] = 1;
    save();
    return true;
  }

  // on: true fits, false takes it off, undefined flips
  function fitTune(id, on) {
    if (!ownedTune(id)) return false;
    st.fit[id] = (on === undefined ? !st.fit[id] : !!on) ? 1 : 0;
    save();
    return true;
  }

  function fittedList() { return TUNING.filter(function (t) { return st.fit[t.id]; }).map(function (t) { return t.id; }); }

  function unlockAll() {
    ITEMS.forEach(function (it) { st.owned[it.id] = 1; });
    TUNING.forEach(function (it) { st.tune[it.id] = 1; });
    save();
  }

  // The visible listings for a filter: [{ kind: 'car' | 'tune', it }]. Cars first, then the tuning.
  function listings(f) {
    f = f || flt;
    const q = String(f.q || '').trim().toLowerCase();
    const max = f.max >= MAXP ? Infinity : f.max;
    const out = [];
    function add(kind, it) {
      const mine = kind === 'car' ? owned(it.id) : ownedTune(it.id);
      if (it.price > max) return;
      if (f.can && (mine || lack(it) > 0)) return;
      if (q && (it.title + ' ' + it.desc + ' ' + it.who).toLowerCase().indexOf(q) < 0) return;
      out.push({ kind: kind, it: it });
    }
    if (f.cat !== 'tune') ITEMS.forEach(function (it) { add('car', it); });
    if (f.cat !== 'car') TUNING.forEach(function (it) { add('tune', it); });
    return out;
  }

  // ---- the extras, drawn over the car in the car's own units (points to +x, nominal 40 x 20) ----
  const ROOF = { lanos: -4, horse: -9, rickshaw: -5, electro: 0, cab: -3, golf: 0 };
  const HALF = { matiz: 8, rickshaw: 8, electro: 8, horse: 9, porto: 9, nyc: 9 };
  const GLOW = ['#ff4d6a', '#ffd23f', '#43d6a1', '#6fb4ff', '#ff9ad5'];

  function fillPoly(c, col, pts) {
    c.fillStyle = col; c.beginPath(); c.moveTo(pts[0], pts[1]);
    for (let i = 2; i < pts.length; i += 2) c.lineTo(pts[i], pts[i + 1]);
    c.closePath(); c.fill();
  }

  const EXTRA = {
    taxi(c, id) {
      const x = ROOF[id] === undefined ? -2 : ROOF[id];
      c.fillStyle = 'rgba(0,0,0,0.25)'; c.fillRect(x - 3, -5.6, 6, 11.6);
      c.fillStyle = '#ffd23f'; c.fillRect(x - 3, -6, 6, 12);
      c.fillStyle = '#1c1a2e'; c.fillRect(x - 3, -6, 6, 1); c.fillRect(x - 3, 5, 6, 1);
      c.save(); c.translate(x, 0); c.rotate(Math.PI / 2);
      c.font = '800 3.4px system-ui, sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillStyle = '#1c1a2e'; c.fillText('TAXI', 0, 0.2); c.restore();
    },
    stickers(c, id) {
      const h = (HALF[id] || 9) - 1.2;
      [-1, 1].forEach(function (s) {
        for (let i = 0; i < 3; i++) {
          const x = 8 - i * 6;
          fillPoly(c, i === 1 ? '#ffd23f' : '#1c1a2e', [x, s * h, x - 5.2, s * (h - 1.8 + 0.4 * i), x - 1.8, s * (h + 0.2), x - 4.6, s * (h + 0.4)]);
        }
      });
    },
    rims(c, id) {
      const h = HALF[id] || 9;
      [-12, 12].forEach(function (x) {
        [-1, 1].forEach(function (s) {
          c.fillStyle = '#12111c'; c.beginPath(); c.ellipse(x, s * (h + 0.4), 3.3, 1.5, 0, 0, Math.PI * 2); c.fill();
          c.fillStyle = '#d9e0ec'; c.beginPath(); c.ellipse(x, s * (h + 0.4), 2.5, 1.1, 0, 0, Math.PI * 2); c.fill();
          c.fillStyle = '#7d879b'; c.fillRect(x - 0.3, s * (h + 0.4) - 1, 0.6, 2);
        });
      });
    },
    tree(c, id) {
      const x = id === 'horse' ? -8 : 9.5, y = -2.4;
      c.strokeStyle = '#e9e6dc'; c.lineWidth = 0.35;
      c.beginPath(); c.moveTo(x - 1.2, y); c.lineTo(x - 0.2, y); c.stroke();
      fillPoly(c, '#2fae5f', [x + 3.2, y, x - 0.2, y - 2, x - 0.2, y + 2]);
      fillPoly(c, '#1f8a49', [x + 3.2, y, x + 1, y - 0.1, x - 0.2, y + 2]);
    },
    garland(c, id) {
      const x = id === 'horse' ? -14 : id === 'rickshaw' ? 6.4 : 11.6, h = (HALF[id] || 9) - 1.5;
      c.strokeStyle = '#0c0b14'; c.lineWidth = 0.35; c.beginPath(); c.moveTo(x, -h);
      for (let i = 1; i <= 6; i++) c.lineTo(x + (i % 2 ? -0.8 : 0), -h + (2 * h * i) / 6);
      c.stroke();
      for (let i = 0; i <= 6; i++) {
        const y = -h + (2 * h * i) / 6, col = GLOW[i % GLOW.length];
        c.globalAlpha = 0.35; c.fillStyle = col; c.beginPath(); c.arc(x, y, 2.2, 0, Math.PI * 2); c.fill();
        c.globalAlpha = 1; c.beginPath(); c.arc(x, y, 0.95, 0, Math.PI * 2); c.fill();
      }
    }
  };

  // ---- DOM ----
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function scene(c, css) {
    const W = PHOTO.w, H = PHOTO.h;
    const g = c.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, css.getPropertyValue('--s-photo-hi').trim() || '#4a5174');
    g.addColorStop(1, css.getPropertyValue('--s-photo').trim() || '#3b4160');
    c.fillStyle = g; c.fillRect(0, 0, W, H);
    c.fillStyle = 'rgba(0,0,0,0.10)';                                   // cobbles, a fixed pattern
    for (let r = 0; r < 6; r++) for (let k = 0; k < 14; k++) {
      if ((r * 7 + k * 3) % 5 === 0) c.fillRect(k * 27 + (r % 2) * 13, 12 + r * 26, 22, 10);
    }
    c.fillStyle = css.getPropertyValue('--s-lane').trim() || '#e9e6dc';
    for (let x = 0; x < W; x += 44) c.fillRect(x, H - 24, 26, 4);       // lane marks
    c.fillStyle = 'rgba(0,0,0,0.22)'; c.fillRect(0, 0, W, 5);            // kerb shadow
    const v = c.createRadialGradient(W / 2, H / 2, H * 0.5, W / 2, H / 2, W * 0.62);
    v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, 'rgba(0,0,0,0.32)');
    c.fillStyle = v; c.fillRect(0, 0, W, H);                             // vignette, like a phone photo
  }

  // The listing photo: a car on the street. `extras` is the list of tuning drawn on it.
  function photo(it, id, extras, big) {
    const cv = el('canvas', 'olx-photo');
    cv.width = PHOTO.w * 2; cv.height = PHOTO.h * 2;
    cv.setAttribute('role', 'img');
    cv.setAttribute('aria-label', it.title);
    const c = cv.getContext && cv.getContext('2d');
    if (!c) return cv;
    const css = root.getComputedStyle(dom.root);
    c.scale(2, 2);
    scene(c, css);
    const len = big ? PHOTO.car + 40 : PHOTO.car, px = PHOTO.w / 2, py = PHOTO.h / 2 - 6;
    if (PG.cars) PG.cars.paint(c, id, px, py, len, '#3df5b0');
    if (extras.length) {
      c.save(); c.translate(px, py); c.scale(len / 40, len / 40);
      extras.forEach(function (x) { if (EXTRA[x]) EXTRA[x](c, id); });
      c.restore();
    }
    return cv;
  }

  function badge(cls, text) { return el('span', 'olx-badge ' + cls, text); }

  function card(row) {
    const car = row.kind === 'car', it = row.it;
    const mine = car ? owned(it.id) : ownedTune(it.id);
    const on = car && mine && st.skin === it.id;
    const n = lack(it);
    const a = el('article', 'olx-ad' + (car ? '' : ' olx-tune'));
    a.setAttribute(car ? 'data-skin' : 'data-tune', it.id);
    const ph = el('div', 'olx-ph');
    ph.appendChild(car ? photo(it, it.id, on ? fittedList() : [], false) : photo(it, st.skin, [it.id], true));
    if (it.top) ph.appendChild(el('span', 'olx-top', 'ТОП'));
    if (!car && fitted(it.id)) ph.appendChild(el('span', 'olx-top fit', 'Встановлено'));
    a.appendChild(ph);
    const b = el('div', 'olx-body');
    const rowEl = el('div', 'olx-row');
    rowEl.appendChild(el('h3', 'olx-name', it.title));
    rowEl.appendChild(el('span', 'olx-price' + (it.cur ? ' own' : ''), it.cur || PG.util.eur(it.price)));
    b.appendChild(rowEl);
    const tags = el('div', 'olx-tags');
    tags.appendChild(badge('kind', car ? 'Авто' : 'Тюнінг'));
    if (it.torg) tags.appendChild(badge('torg', 'торг'));
    if (mine) tags.appendChild(badge('mine', car ? 'у гаражі' : 'куплено'));
    b.appendChild(tags);
    b.appendChild(el('p', 'olx-who', it.who));
    b.appendChild(el('p', 'olx-date', 'Опубліковано ' + it.date));
    b.appendChild(el('p', 'olx-desc', it.desc));
    if (!mine && n > 0) {
      const bar = el('div', 'olx-need');
      const fill = el('i');
      fill.style.width = Math.min(100, Math.round(100 * Math.max(0, wallet()) / it.price)) + '%';
      bar.appendChild(fill);
      b.appendChild(bar);
    }
    let label, cls, off = false;
    if (car) {
      label = on ? 'Обрано' : mine ? 'Обрати' : n === 0 ? 'Купити' : 'Не вистачає ' + PG.util.eur(n);
      cls = on ? 'on' : mine || n === 0 ? 'buy' : 'no';
      off = on || (!mine && n > 0);
    } else {
      label = mine ? (fitted(it.id) ? 'Зняти' : 'Встановити') : n === 0 ? 'Купити' : 'Не вистачає ' + PG.util.eur(n);
      cls = mine ? (fitted(it.id) ? 'alt' : 'buy') : n === 0 ? 'buy' : 'no';
      off = !mine && n > 0;
    }
    const act = el('button', 'olx-btn ' + cls, label);
    act.type = 'button';
    act.disabled = off;
    act.addEventListener('click', function () {
      if (car) { if (!mine) buy(it.id); else pick(it.id); }
      else if (!mine) buyTune(it.id);
      else fitTune(it.id);
      refresh();
    });
    b.appendChild(act);
    a.appendChild(b);
    return a;
  }

  function refresh() {
    if (!dom) return;
    dom.wal.textContent = PG.util.eur(wallet());
    renderAds();
    updateButton();
  }

  function renderAds() {
    dom.ads.textContent = '';
    const rows = listings(flt);
    const cars = rows.filter(function (r) { return r.kind === 'car'; });
    const tune = rows.filter(function (r) { return r.kind === 'tune'; });
    dom.count.textContent = rows.length ? 'Знайдено: ' + rows.length : '';
    if (!rows.length) {
      dom.ads.appendChild(el('p', 'olx-empty', flt.can ? 'Поки що нічого не по кишені. Відкатайте ще одну зміну.' : 'Нічого не знайшли. Спробуйте інший запит.'));
      return;
    }
    function section(title, list) {
      if (!list.length) return;
      if (flt.cat === 'all') dom.ads.appendChild(el('h2', 'olx-sec', title));
      list.forEach(function (r) { dom.ads.appendChild(card(r)); });
    }
    section('Авто', cars);
    section('Тюнінг', tune);
  }

  function updateButton() {
    if (typeof document === 'undefined') return;
    const b = document.getElementById('btn-shop');
    if (b) b.querySelector('.olx-open-wal').textContent = PG.util.eur(wallet());
  }

  // Both filter sets (phone chips, PC sidebar) write into `flt` and are kept in step.
  function syncFilter() {
    if (!dom) return;
    dom.chips.forEach(function (c) {
      const on = c.key === 'cheap' ? flt.max < MAXP : c.key === 'can' ? flt.can : c.key === flt.cat;
      c.btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      c.btn.className = 'olx-chip' + (on ? ' on' : '');
    });
    dom.radios.forEach(function (r) { r.checked = r.value === flt.cat; });
    dom.can.checked = flt.can;
    dom.range.value = String(flt.max);
    dom.rangeOut.textContent = flt.max >= MAXP ? 'без обмеження' : 'до ' + PG.util.eur(flt.max);
    renderAds();
  }

  function buildFilters(bar, side) {
    const CATS = [['all', 'Усе'], ['car', 'Авто'], ['tune', 'Тюнінг']];
    const chips = el('div', 'olx-chips');
    chips.setAttribute('role', 'group'); chips.setAttribute('aria-label', 'Фільтри');
    dom.chips = [];
    function chip(key, label, fn) {
      const b = el('button', 'olx-chip', label); b.type = 'button';
      b.addEventListener('click', function () { fn(); syncFilter(); });
      chips.appendChild(b);
      dom.chips.push({ key: key, btn: b });
    }
    CATS.forEach(function (c) { chip(c[0], c[1], function () { flt.cat = c[0]; }); });
    chip('can', 'Можу купити', function () { flt.can = !flt.can; });
    chip('cheap', 'До 100 €', function () { flt.max = flt.max < MAXP ? MAXP : 100; });
    bar.appendChild(chips);

    side.appendChild(el('h2', 'olx-side-h', 'Фільтри'));
    const cat = el('fieldset', 'olx-fs');
    cat.appendChild(el('legend', '', 'Категорія'));
    dom.radios = [];
    CATS.forEach(function (c) {
      const lab = el('label', 'olx-opt');
      const r = el('input'); r.type = 'radio'; r.name = 'olx-cat'; r.value = c[0];
      r.addEventListener('change', function () { flt.cat = c[0]; syncFilter(); });
      lab.appendChild(r); lab.appendChild(el('span', '', c[1]));
      cat.appendChild(lab);
      dom.radios.push(r);
    });
    side.appendChild(cat);
    const pr = el('fieldset', 'olx-fs');
    pr.appendChild(el('legend', '', 'Ціна'));
    const rg = el('input', 'olx-range'); rg.type = 'range'; rg.min = '0'; rg.max = String(MAXP); rg.step = '10'; rg.value = String(MAXP);
    rg.setAttribute('aria-label', 'Ціна до');
    rg.addEventListener('input', function () { flt.max = Math.max(0, Math.min(MAXP, +rg.value || 0)); syncFilter(); });
    pr.appendChild(rg);
    const out = el('output', 'olx-range-out', ''); pr.appendChild(out);
    side.appendChild(pr);
    const lab = el('label', 'olx-opt olx-can');
    const cb = el('input'); cb.type = 'checkbox';
    cb.addEventListener('change', function () { flt.can = cb.checked; syncFilter(); });
    lab.appendChild(cb); lab.appendChild(el('span', '', 'Можу купити'));
    side.appendChild(lab);
    dom.can = cb; dom.range = rg; dom.rangeOut = out;
  }

  function build() {
    const r = el('div'); r.id = 'shop'; r.hidden = true;
    r.setAttribute('role', 'dialog'); r.setAttribute('aria-label', 'ОЛХ');
    const head = el('div', 'olx-head');
    const top = el('div', 'olx-topbar');
    const back = el('button', 'olx-back'); back.type = 'button'; back.setAttribute('aria-label', 'Назад');
    back.appendChild(el('span', 'olx-chev'));
    back.addEventListener('click', close);
    top.appendChild(back);
    const logo = el('div', 'olx-logo');
    logo.appendChild(el('span', 'olx-mark'));
    logo.appendChild(el('span', '', 'ОЛХ'));
    top.appendChild(logo);
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
    r.appendChild(head);

    const bar = el('div', 'olx-bar');                // sticky: search and the phone chips
    const q = el('input', 'olx-q'); q.type = 'search'; q.placeholder = 'Шукаю авто для зміни';
    q.setAttribute('aria-label', 'Пошук оголошень'); q.setAttribute('autocomplete', 'off');
    q.addEventListener('input', function () { flt.q = q.value; renderAds(); });
    bar.appendChild(q);
    const main = el('div', 'olx-main');
    const side = el('aside', 'olx-side'); side.setAttribute('aria-label', 'Фільтри');
    const list = el('div', 'olx-list');
    const count = el('p', 'olx-count', '');
    count.setAttribute('aria-live', 'polite');
    const ads = el('div', 'olx-ads');
    list.appendChild(count); list.appendChild(ads);
    main.appendChild(side); main.appendChild(list);
    dom = { root: r, wal: wal, ads: ads, count: count, q: q };
    buildFilters(bar, side);
    r.appendChild(bar);
    r.appendChild(main);
    (document.getElementById('app') || document.body).appendChild(r);
  }

  function open() {
    if (typeof document === 'undefined') return;
    if (!dom) build();
    dom.q.value = flt.q;
    syncFilter();
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
      b.appendChild(el('span', 'olx-open-name', 'ОЛХ'));
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
    ITEMS: ITEMS, TUNING: TUNING, KEY: KEY, wallet: wallet, owned: owned, need: need, earn: earn, buy: buy, pick: pick,
    ownedTune: ownedTune, needTune: needTune, buyTune: buyTune, fitTune: fitTune, fitted: fitted, fittedList: fittedList,
    listings: listings, filter: flt, unlockAll: unlockAll, skin: function () { return st.skin; }, open: open, close: close
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
