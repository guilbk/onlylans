/* 41_cars.js: drawn top-down cars from cached sprites, with smooth turning. No DOM at load. */
(function (root) {
  const PG = root.PG = root.PG || {};

  const L = 40;            // sprite car length, logical units (the car points to +x)
  const WID = 20;
  const BOX = 76;          // sprite box side, logical units (room for the glow)
  const RES = 2;           // sprite pixels per logical unit
  const GLOW_R = 34;
  const TURN_RATE = 11;    // 1/s: how fast the heading follows the target
  const TAU = Math.PI * 2;

  const sprites = {};
  const ang = new Float32Array(32);
  const seen = new Uint8Array(32);

  function rrect(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
  }

  function makeSprite(color) {
    const cv = document.createElement('canvas');
    cv.width = cv.height = BOX * RES;
    const c = cv.getContext('2d');
    c.scale(RES, RES);
    c.translate(BOX / 2, BOX / 2);
    const g = c.createRadialGradient(0, 0, 8, 0, 0, GLOW_R);
    g.addColorStop(0, color);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    c.globalAlpha = 0.12;
    c.fillStyle = g;
    c.beginPath(); c.arc(0, 0, GLOW_R, 0, TAU); c.fill();
    c.globalAlpha = 1;
    c.fillStyle = 'rgba(0,0,0,0.45)';             // soft contact shadow
    rrect(c, -L / 2 - 1.5, -WID / 2 - 1.5, L + 3, WID + 3, 9); c.fill();
    c.fillStyle = color;                         // body
    rrect(c, -L / 2, -WID / 2, L, WID, 7.5); c.fill();
    c.fillStyle = 'rgba(255,255,255,0.28)';      // top light
    rrect(c, -L / 2 + 4, -WID / 2 + 1.5, L - 8, 4, 2); c.fill();
    c.fillStyle = 'rgba(7,11,20,0.82)';          // windscreen, roof gap, rear window
    rrect(c, 1, -WID / 2 + 2.5, 11, WID - 5, 3); c.fill();
    rrect(c, -15, -WID / 2 + 3.5, 5.5, WID - 7, 2); c.fill();
    c.fillStyle = 'rgba(0,0,0,0.22)';            // roof
    rrect(c, -9, -WID / 2 + 2, 9.5, WID - 4, 2); c.fill();
    c.fillStyle = '#fff6c9';                     // headlights
    c.beginPath(); c.arc(L / 2 - 2.5, -WID / 2 + 4, 2.2, 0, TAU); c.arc(L / 2 - 2.5, WID / 2 - 4, 2.2, 0, TAU); c.fill();
    c.fillStyle = '#ff4d4d';                     // tail lights
    c.fillRect(-L / 2, -WID / 2 + 2.5, 1.8, 4);
    c.fillRect(-L / 2, WID / 2 - 6.5, 1.8, 4);
    return cv;
  }

  function sprite(color) {
    return sprites[color] || (sprites[color] = makeSprite(color));
  }

  // Heading follows the target by the shortest way round, so the car turns instead of snapping.
  function turn(slot, hx, hy, dt, still) {
    if (hx || hy) {
      const t = Math.atan2(hy, hx);
      if (!seen[slot]) { seen[slot] = 1; ang[slot] = t; }
      else {
        let d = t - ang[slot];
        d -= TAU * Math.round(d / TAU);
        ang[slot] += still ? d : d * (1 - Math.exp(-dt * TURN_RATE));
      }
    }
    return ang[slot];
  }


  // ---- hero skins: flat vector sprites, car points to +x, nominal box 40 x 20, no brands or logos ----
  const GLASS = '#10192b';
  const SKINS = [
    { id: 'lanos', name: 'Ланос б/у' }, { id: 'matiz', name: 'Матіз' }, { id: 'porto', name: 'Порту класик' },
    { id: 'golf', name: 'Гольф' }, { id: 'nyc', name: 'Нью-Йорк' }, { id: 'rickshaw', name: 'Рікша' },
    { id: 'cab', name: 'Лондонський кеб' }, { id: 'electro', name: 'Електро' }, { id: 'horse', name: 'Кінь з возом' }
  ];
  const SKIN_K = { horse: 1.45 };      // the horse and cart is drawn bigger on the map
  const SKIN_W = { matiz: 18, rickshaw: 18, electro: 18 };   // body size for the shadow
  const SKIN_L = { matiz: 32, rickshaw: 32 };
  let skinId = 'lanos';

  function R(c, col, x, y, w, h, r) { c.fillStyle = col; rrect(c, x, y, w, h, r); c.fill(); }
  function E(c, col, x, y, rx, ry) { c.fillStyle = col; c.beginPath(); c.ellipse(x, y, rx, ry, 0, 0, TAU); c.fill(); }
  function lamps(c, col, x, y, r) { c.fillStyle = col; c.beginPath(); c.arc(x, -y, r, 0, TAU); c.arc(x, y, r, 0, TAU); c.fill(); }

  const DRAW = {
    // the worn 90s sedan: odd doors, rust, cracked glass, one headlight, a puff of smoke
    lanos(c, col) {
      E(c, 'rgba(150,156,166,0.30)', -33, 3, 4.4, 4); E(c, 'rgba(150,156,166,0.45)', -28.5, -1, 3.6, 3.2);
      E(c, 'rgba(150,156,166,0.65)', -24, 2, 2.6, 2.4);
      R(c, col, -20, -10, 40, 20, 7);
      R(c, '#b9c4cc', -6, -10, 10, 3.4, 1.5);            // door from another car (primer grey)
      R(c, '#e3d79c', -15, 6.6, 10, 3.4, 1.5);           // and a yellowed one
      R(c, 'rgba(0,0,0,0.18)', -9, -7, 10, 14, 2);       // roof
      R(c, GLASS, 2, -7.5, 9, 15, 3); R(c, GLASS, -16, -6.5, 5, 13, 2);
      c.strokeStyle = 'rgba(255,255,255,0.8)'; c.lineWidth = 0.7;      // cracked windscreen
      c.beginPath(); c.moveTo(4, -7); c.lineTo(7, -1.5); c.lineTo(5.5, 2); c.lineTo(9.5, 7);
      c.moveTo(7, -1.5); c.lineTo(11, -3); c.stroke();
      E(c, '#b4582a', 14, -6, 2.6, 1.7); E(c, '#b4582a', -17, 5.5, 2, 1.4); E(c, '#9c4a22', -1, 9, 2.2, 1.1);   // rust
      R(c, '#fff6c9', 17.5, 2, 2.5, 4.5, 1.2);           // the only headlight
      R(c, '#3a3f4a', 17.5, -6.5, 2.5, 4.5, 1.2);
      R(c, '#ff4d4d', -20, -7, 1.8, 4, 0.8); R(c, '#7a2b2b', -20, 3, 1.8, 4, 0.8);
    },
    matiz(c) {
      R(c, '#ff8a3d', -16, -9, 32, 18, 8); R(c, '#ffb27a', -8, -7, 10, 14, 3);
      R(c, GLASS, 2, -7, 7, 14, 3); R(c, GLASS, -12, -6, 3.5, 12, 2);
      R(c, '#e6742c', -16, -2, 6, 4, 2); R(c, '#e6742c', 13, -2, 3, 4, 1.5);
      lamps(c, '#fff6c9', 15, 5.5, 2); lamps(c, '#ff4d4d', -15.6, 5.5, 1.4);
      R(c, '#e6742c', 3, -10.8, 2.4, 2.2, 1); R(c, '#e6742c', 3, 8.6, 2.4, 2.2, 1);
    },
    porto(c) {
      R(c, '#1d2230', -20, -9.5, 40, 19, 6); R(c, '#2b3246', 10, -1, 9, 2, 1);
      R(c, '#2e9a62', -10, -7, 18, 14, 4); R(c, '#ffe27a', -2.5, -2, 4, 4, 1.2);
      R(c, '#27324d', 8, -7, 4, 14, 2); R(c, GLASS, -14.5, -6, 4, 12, 2);
      R(c, '#c9ced8', 19, -8, 1.6, 16, 0.8); lamps(c, '#fff2b8', 18, 6, 2.6); lamps(c, '#ff4d4d', -19, 6, 1.4);
    },
    golf(c) {
      R(c, '#4c7bd9', -19, -9.5, 38, 19, 4); R(c, '#3a64b8', -10, -8, 20, 16, 3);
      R(c, GLASS, -6, -5, 10, 10, 2); R(c, GLASS, 10.5, -8, 4.5, 16, 2); R(c, GLASS, -15, -7, 4, 14, 2);
      R(c, '#2f539a', -9.5, -9, 19, 1.2, 0.5); R(c, '#2f539a', -9.5, 7.8, 19, 1.2, 0.5);
      R(c, '#fff6c9', 16.8, -9, 2.4, 4.6, 1); R(c, '#fff6c9', 16.8, 4.4, 2.4, 4.6, 1);
      R(c, '#ff4d4d', -19.4, -9, 1.8, 4, 0.8); R(c, '#ff4d4d', -19.4, 5, 1.8, 4, 0.8);
    },
    nyc(c) {
      R(c, '#ffcf1f', -20, -9.5, 40, 19, 6);
      for (let i = 0; i < 14; i++) {                       // checker band on both sides
        c.fillStyle = i % 2 ? '#14161f' : '#ffcf1f';
        c.fillRect(-18 + i * 2.6, -9.5, 2.6, 2.4); c.fillRect(-18 + i * 2.6, 7.1, 2.6, 2.4);
      }
      R(c, '#e8b50d', -9, -6.5, 17, 13, 3); R(c, GLASS, 8, -6.5, 4.5, 13, 2.5); R(c, GLASS, -15, -6, 4, 12, 2);
      R(c, '#fff3a8', -4, -3.5, 8, 7, 1.5); R(c, '#14161f', -2, -1.2, 4, 2.4, 0.6);
      lamps(c, '#fff6c9', 18.5, 6, 2); lamps(c, '#ff4d4d', -19.2, 6, 1.5);
    },
    rickshaw(c) {
      R(c, '#1b1b1b', -12, -10.8, 8, 3, 1.4); R(c, '#1b1b1b', -12, 7.8, 8, 3, 1.4);   // rear wheels
      R(c, '#1b1b1b', 12, -1.8, 5, 3.6, 1.5);                                         // front wheel
      R(c, '#ff9f1c', 5, -5, 10, 10, 5); R(c, '#222936', 9, -8, 2, 16, 1);
      R(c, '#ff9f1c', -15, -8, 20, 16, 5); R(c, '#a8332a', -12, -5, 8, 10, 2);
      R(c, '#1f9d6b', -16, -9, 22, 18, 6);                                            // canopy
      for (let x = -14; x < 5; x += 6) R(c, '#ffe9a8', x, -8, 2, 16, 1);
      R(c, GLASS, 5.5, -6, 2.4, 12, 1.2); lamps(c, '#fff6c9', 15.6, 0, 1.8);
    },
    cab(c) {
      R(c, '#171a26', -20, -10, 40, 20, 7);
      E(c, '#232838', 13, -8, 6, 2.6); E(c, '#232838', 13, 8, 6, 2.6);
      R(c, '#232838', -12, -8.5, 19, 17, 5); R(c, '#27324d', 7, -8, 5, 16, 2.5); R(c, GLASS, -16.5, -6, 4, 12, 2);
      R(c, '#ffc83d', -1, -3, 6, 6, 1.5); R(c, '#aab2c4', 19.2, -3, 1.6, 6, 0.8);
      lamps(c, '#fff6c9', 18.4, 6.6, 2.8); lamps(c, '#ff4d4d', -19.2, 6.5, 1.5);
    },
    electro(c) {
      R(c, '#f2fbff', -20, -9, 40, 18, 9); R(c, '#7fe3f5', -11, -7, 22, 14, 6);
      R(c, 'rgba(255,255,255,0.55)', -8, -6, 10, 3, 1.5); R(c, '#16c6e8', -18, -9, 12, 1.6, 0.8); R(c, '#16c6e8', -18, 7.4, 12, 1.6, 0.8);
      c.fillStyle = '#16c6e8'; c.beginPath();                                         // bolt
      c.moveTo(2, -3.5); c.lineTo(-3, 0.5); c.lineTo(0, 0.5); c.lineTo(-2, 3.5); c.lineTo(3, -0.5); c.lineTo(0, -0.5); c.closePath(); c.fill();
      R(c, '#a6f6ff', 18.4, -7, 1.8, 14, 0.9); R(c, '#ff4d6a', -20, -7, 1.6, 14, 0.8);
    },
    horse(c) {
      R(c, '#3a2a1a', -17, -12.5, 8, 2.6, 1.2); R(c, '#3a2a1a', -17, 9.9, 8, 2.6, 1.2);   // cart wheels
      R(c, '#a8743f', -22, -10, 18, 20, 2); R(c, '#8d5f31', -22, -3.4, 18, 1, 0.4); R(c, '#8d5f31', -22, 2.4, 18, 1, 0.4);
      R(c, '#c64b5a', -12, -6.5, 6, 13, 2);                                              // cushion
      R(c, '#7b4f26', -4, -5, 12, 1.3, 0.6); R(c, '#7b4f26', -4, 3.7, 12, 1.3, 0.6);     // shafts
      R(c, '#5b3a18', 4, -7.4, 2.2, 2.4, 1); R(c, '#5b3a18', 4, 5, 2.2, 2.4, 1);         // legs
      R(c, '#5b3a18', 11, -7.4, 2.2, 2.4, 1); R(c, '#5b3a18', 11, 5, 2.2, 2.4, 1);
      E(c, '#2b1a0e', 0.5, 0, 2.4, 1.6); E(c, '#8b5a2b', 8, 0, 8.5, 5.2); E(c, '#8b5a2b', 16.5, 0, 4.4, 3.2);
      E(c, '#8b5a2b', 21.5, 0, 3.6, 2.4); R(c, '#2b1a0e', 13, -1, 6, 2, 1);               // body, neck, head, mane
      E(c, '#2b1a0e', 19, -2.4, 1, 0.8); E(c, '#2b1a0e', 19, 2.4, 1, 0.8);
    }
  };

  // ---- car mods: tuning drawn over any skin (no brands). One choice per category; saved in `lanos.mods` ----
  const CATS = { paint: 'Фарба', decal: 'Наклейки', spoiler: 'Спойлер', rims: 'Диски', glow: 'Неон', roof: 'Шашка', exhaust: 'Вихлоп', lights: 'Фари' };
  const MODS = [
    { id: 'paint_red', name: 'Червоний', cat: 'paint', price: 20, c: '#e5233c' },
    { id: 'paint_blue', name: 'Синій металік', cat: 'paint', price: 20, c: '#2f6bff' },
    { id: 'paint_lime', name: 'Лайм', cat: 'paint', price: 20, c: '#8be31a' },
    { id: 'paint_violet', name: 'Фіолетовий', cat: 'paint', price: 25, c: '#9a4dff' },
    { id: 'paint_matte', name: 'Матовий чорний', cat: 'paint', price: 40, c: '#15171c', a: 0.82 },
    { id: 'paint_pearl', name: 'Перлинний', cat: 'paint', price: 50, c: '#fff0fb', c2: '#c9e4ff' },
    { id: 'decal_flames', name: 'Полум’я', cat: 'decal', price: 25 },
    { id: 'decal_azulejo', name: 'Азулежу', cat: 'decal', price: 30 },
    { id: 'decal_racing', name: 'Гоночні смуги', cat: 'decal', price: 20 },
    { id: 'spoiler_lip', name: 'Малий спойлер', cat: 'spoiler', price: 15 },
    { id: 'spoiler_wing', name: 'Крило', cat: 'spoiler', price: 35 },
    { id: 'rims_chrome', name: 'Хромовані диски', cat: 'rims', price: 15, c: '#e3eaf2' },
    { id: 'rims_gold', name: 'Золоті диски', cat: 'rims', price: 30, c: '#ffcf3a' },
    { id: 'rims_red', name: 'Червоні диски', cat: 'rims', price: 20, c: '#ff3b4d' },
    { id: 'glow_cyan', name: 'Неон бірюзовий', cat: 'glow', price: 30, c: '#27f0ff' },
    { id: 'glow_pink', name: 'Неон рожевий', cat: 'glow', price: 30, c: '#ff3fb4' },
    { id: 'glow_green', name: 'Неон зелений', cat: 'glow', price: 30, c: '#5dff6a' },
    { id: 'glow_violet', name: 'Неон фіолетовий', cat: 'glow', price: 30, c: '#a56bff' },
    { id: 'roof_classic', name: 'Класична шашка', cat: 'roof', price: 15 },
    { id: 'roof_led', name: 'Світлодіодна «ТАКСІ»', cat: 'roof', price: 35 },
    { id: 'roof_disco', name: 'Диско-шашка', cat: 'roof', price: 60 },
    { id: 'exhaust_grey', name: 'Сірий дим', cat: 'exhaust', price: 10, c: '#b4bac4' },
    { id: 'exhaust_pink', name: 'Рожевий дим', cat: 'exhaust', price: 25, c: '#ff8fd0' },
    { id: 'exhaust_blue', name: 'Блакитний дим', cat: 'exhaust', price: 25, c: '#7fc8ff' },
    { id: 'lights_xenon', name: 'Ксенон', cat: 'lights', price: 25, c: '#d6ecff' },
    { id: 'lights_fog', name: 'Жовті протитуманки', cat: 'lights', price: 20, c: '#ffe45c' }
  ];
  const MOD_BY = {};
  MODS.forEach(function (m) { MOD_BY[m.id] = m; });
  const STORE = 'lanos.mods';
  const STATIC = ['paint', 'decal', 'spoiler', 'rims', 'roof', 'lights'];
  let cur = load();

  function clean(o) {
    const r = {};
    if (o && typeof o === 'object') Object.keys(CATS).forEach(function (k) { if (MOD_BY[o[k]] && MOD_BY[o[k]].cat === k) r[k] = o[k]; });
    return r;
  }
  function load() {
    try { return clean(JSON.parse(root.localStorage.getItem(STORE))); } catch (e) { return {}; }
  }
  function setMods(o) {
    cur = clean(o);
    try { root.localStorage.setItem(STORE, JSON.stringify(cur)); } catch (e) { /* storage blocked: memory only */ }
    return cur;
  }
  function mods() { return Object.assign({}, cur); }
  function sig(m) { return m ? STATIC.map(function (k) { return m[k] || ''; }).join(',') : ''; }
  function isFast() { const G = PG.engine && PG.engine.G; return !!(G && G.fast); }
  function col(m, k, d) { return m[k] ? MOD_BY[m[k]].c : d; }

  // the skin with a paint tint: drawn on a side canvas so the glass and the lamps keep their depth
  function tintedBody(c, id, color, pa, res) {
    const cv = document.createElement('canvas');
    cv.width = cv.height = BOX * res;
    const t = cv.getContext('2d');
    t.scale(res, res);
    t.translate(BOX / 2, BOX / 2);
    (DRAW[id] || DRAW.lanos)(t, color);
    t.globalCompositeOperation = 'source-atop';
    t.globalAlpha = pa.a || 0.6;
    let f = pa.c;
    if (pa.c2) { f = t.createLinearGradient(-20, -10, 20, 10); f.addColorStop(0, pa.c); f.addColorStop(1, pa.c2); }
    t.fillStyle = f;
    t.fillRect(-BOX / 2, -BOX / 2, BOX, BOX);
    c.drawImage(cv, -BOX / 2, -BOX / 2, BOX, BOX);
  }

  function wheels(c, m) {
    if (!m.rims) return;
    const rc = col(m, 'rims');
    [-12, 11].forEach(function (x) {
      [-1, 1].forEach(function (sy) {
        R(c, '#0d0f14', x - 3.6, sy < 0 ? -12 : 9.4, 7.2, 2.6, 1.2);
        R(c, rc, x - 2, sy < 0 ? -11.5 : 10.2, 4, 1.3, 0.6);
      });
    });
  }

  function staticMods(c, m) {
    c.save();
    rrect(c, -20, -10, 40, 20, 7); c.clip();
    if (m.decal === 'decal_flames') {
      [-1, 1].forEach(function (sy) {
        c.fillStyle = '#ff7a1a';
        c.beginPath(); c.moveTo(19, sy * 9); c.lineTo(6, sy * 9); c.lineTo(9, sy * 7.2); c.lineTo(3, sy * 6); c.lineTo(11, sy * 5.6); c.lineTo(19, sy * 5); c.fill();
        c.fillStyle = '#ffd23a';
        c.beginPath(); c.moveTo(19, sy * 9); c.lineTo(11, sy * 9); c.lineTo(13, sy * 7.6); c.lineTo(9.5, sy * 7); c.lineTo(19, sy * 6.4); c.fill();
      });
    } else if (m.decal === 'decal_azulejo') {
      [[8, 19], [-19, -13]].forEach(function (r) {
        for (let x = r[0]; x < r[1]; x += 3) for (let y = -9; y < 9; y += 3) {
          c.fillStyle = ((x - r[0]) / 3 + (y + 9) / 3) % 2 ? '#f4f6fb' : '#2a5fb8';
          c.fillRect(x, y, 3, 3);
        }
      });
    } else if (m.decal === 'decal_racing') {
      c.fillStyle = '#f5f7fa'; c.fillRect(-20, -3.6, 40, 2.4);
      c.fillStyle = '#e5233c'; c.fillRect(-20, 1.2, 40, 2.4);
    }
    c.restore();
    if (m.spoiler === 'spoiler_wing') {
      R(c, '#1b1f2a', -24, -9.5, 4.6, 19, 1.4); R(c, '#e5233c', -24, -10.4, 4.6, 1.8, 0.8); R(c, '#e5233c', -24, 8.6, 4.6, 1.8, 0.8);
    } else if (m.spoiler === 'spoiler_lip') R(c, '#1b1f2a', -22, -8, 2.6, 16, 1.2);
    const r = m.roof;
    if (r === 'roof_classic') { R(c, '#1b1f2a', -6.4, -4.4, 6.8, 8.8, 1.4); R(c, '#ffd23a', -5.6, -3.6, 5.2, 7.2, 1); }
    else if (r === 'roof_led') {
      R(c, '#10131a', -6.4, -5.4, 6.8, 10.8, 1.4);
      c.save(); c.translate(-3, 0); c.rotate(Math.PI / 2); c.fillStyle = '#ff4d4d';
      c.font = 'bold 3.6px sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText('ТАКСІ', 0, 0); c.restore();
    } else if (r === 'roof_disco') R(c, '#10131a', -6.4, -5.4, 6.8, 10.8, 1.4);
    const lc = col(m, 'lights');
    if (lc) {
      const g = c.createLinearGradient(20, 0, 36, 0);
      g.addColorStop(0, lc); g.addColorStop(1, 'rgba(255,255,255,0)');
      c.globalAlpha = 0.45; c.fillStyle = g;
      c.beginPath(); c.moveTo(19, -5); c.lineTo(36, -11); c.lineTo(36, 11); c.lineTo(19, 5); c.closePath(); c.fill();
      c.globalAlpha = 1;
      lamps(c, lc, 18.4, 6, 2.2);
    }
  }

  // animated layers below the car (neon pulse, exhaust) and above it (disco lights)
  function under(c, m, t, fast) {
    const gc = col(m, 'glow');
    if (gc) {
      c.save(); c.globalAlpha = 0.45 + 0.25 * Math.sin(t * 3);
      const g = c.createRadialGradient(0, 0, 6, 0, 0, 27);
      g.addColorStop(0, gc); g.addColorStop(1, 'rgba(0,0,0,0)');
      c.fillStyle = g; c.beginPath(); c.ellipse(0, 0, 28, 19, 0, 0, TAU); c.fill(); c.restore();
    }
    if (!m.exhaust) return;
    if (fast) {
      [-5, 5].forEach(function (y) {
        const f = 8 + 4 * Math.sin(t * 40 + y);
        c.fillStyle = '#ff6a1a';
        c.beginPath(); c.moveTo(-20, y - 1.8); c.lineTo(-20 - f, y); c.lineTo(-20, y + 1.8); c.fill();
        c.fillStyle = '#ffe27a';
        c.beginPath(); c.moveTo(-20, y - 0.9); c.lineTo(-20 - f * 0.55, y); c.lineTo(-20, y + 0.9); c.fill();
      });
      return;
    }
    c.fillStyle = col(m, 'exhaust');
    for (let i = 0; i < 3; i++) {
      const ph = (t * 1.5 + i / 3) % 1;
      c.globalAlpha = 0.5 * (1 - ph);
      c.beginPath(); c.arc(-22 - ph * 14, 4 * Math.sin(t * 2 + i), 2 + ph * 3.5, 0, TAU); c.fill();
    }
    c.globalAlpha = 1;
  }

  function over(c, m, t) {
    if (m.roof !== 'roof_disco') return;
    const cs = ['#ff3b4d', '#3df5b0', '#4d7bff'], k = Math.floor(t * 6);
    for (let i = 0; i < 3; i++) {
      c.fillStyle = cs[(k + i) % 3];
      c.beginPath(); c.arc(-3, -3.2 + i * 3.2, 1.3, 0, TAU); c.fill();
    }
  }


  function shadow(c, id) {
    const w = SKIN_W[id] || WID, l = SKIN_L[id] || L;
    c.fillStyle = 'rgba(0,0,0,0.28)';                 // soft shadow, a little below the car
    if (id === 'horse') { rrect(c, -22, -8.5, 19, 20, 2); c.fill(); E(c, c.fillStyle, 11, 1.5, 12, 5.5); }
    else { rrect(c, -l / 2, -w / 2 + 1.5, l + 1, w + 1.5, 8); c.fill(); }
  }

  // Paints the skin vector-sharp around (0,0), no glow: the shop card photos and the sprites use it.
  // With mods it adds the static layers (paint, decal, spoiler, rims, roof sign, lights); res = pixels per unit.
  function paintSkin(c, id, color, mods, res) {
    shadow(c, id);
    const m = mods || {};
    const pa = m.paint && MOD_BY[m.paint];
    wheels(c, m);
    if (pa) tintedBody(c, id, color, pa, res || RES); else (DRAW[id] || DRAW.lanos)(c, color);
    if (id !== 'horse') staticMods(c, m);
  }

  function makeSkinSprite(id, color, mods) {
    const cv = document.createElement('canvas');
    cv.width = cv.height = BOX * RES;
    const c = cv.getContext('2d');
    c.scale(RES, RES);
    c.translate(BOX / 2, BOX / 2);
    const g = c.createRadialGradient(0, 0, 8, 0, 0, GLOW_R);
    g.addColorStop(0, color);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    c.globalAlpha = 0.22;
    c.fillStyle = g;
    c.beginPath(); c.arc(0, 0, GLOW_R, 0, TAU); c.fill();
    c.globalAlpha = 1;
    paintSkin(c, id, color, mods, RES);
    return cv;
  }

  function skinSprite(id, color, mods) {
    const k = id + '|' + color + '|' + sig(mods);
    return sprites[k] || (sprites[k] = makeSkinSprite(id, color, mods));
  }

  function setSkin(id) { skinId = DRAW[id] ? id : 'lanos'; }

  // Vector paint at length len (px) pointing right, centred on (px, py): for pictures outside the map.
  function paint(ctx, id, px, py, len, color, mods) {
    ctx.save();
    ctx.translate(px, py);
    ctx.scale(len / L, len / L);
    paintSkin(ctx, DRAW[id] ? id : 'lanos', color || '#3df5b0', mods, 4);
    ctx.restore();
  }

  function reset() { seen.fill(0); }

  // len: car length in screen px. kind 'hero' draws the chosen skin (or `skin`) with a mint glow and its mods
  // (`mods` overrides the saved ones, null = none), so other players' cars can wear theirs.
  function draw(ctx, px, py, a, len, color, alpha, kind, skin, mods) {
    const hero = kind === 'hero' || !!skin;
    const id = skin || skinId;
    const s = len * (hero ? SKIN_K[id] || 1 : 1) / L;
    const m = hero ? (mods === undefined ? cur : mods) : null;
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(a);
    ctx.scale(s, s);
    ctx.globalAlpha = alpha;
    const dyn = m && (m.glow || m.exhaust || m.roof === 'roof_disco');
    const t = Date.now() / 1000;
    if (dyn) under(ctx, m, t, isFast());
    ctx.drawImage(hero ? skinSprite(id, color, m) : sprite(color), -BOX / 2, -BOX / 2, BOX, BOX);
    if (dyn) over(ctx, m, t);
    ctx.restore();
  }

  // Big preview for the shop: the skin with the mods (all layers, animated if called every frame).
  function preview(canvas, skin, mods) {
    const c = canvas.getContext('2d'), w = canvas.width, h = canvas.height, id = DRAW[skin] ? skin : skinId;
    const m = mods === undefined ? cur : mods || {};
    c.clearRect(0, 0, w, h);
    c.save();
    c.translate(w / 2, h / 2);
    const k = Math.min(w / 78, h / 40);
    c.scale(k, k);
    const t = Date.now() / 1000;
    under(c, m, t, false);
    paintSkin(c, id, '#3df5b0', m, Math.max(RES, Math.ceil(k)));
    over(c, m, t);
    c.restore();
  }

  PG.cars = { draw: draw, preview: preview, setMods: setMods, mods: mods, MODS: MODS, turn: turn, reset: reset, paint: paint, setSkin: setSkin, skin: function () { return skinId; }, SKINS: SKINS };
})(typeof window !== 'undefined' ? window : globalThis);
