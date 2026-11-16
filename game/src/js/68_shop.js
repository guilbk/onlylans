/* 68_shop.js: «ОЛЕКС», the skin, look-mod and tuning marketplace (a parody of a classifieds site). Mods come from PG.cars.MODS.
   Tuning (§22): 3 performance upgrades x 3 levels bought with the wallet; they set PG.engine.tune (speed, radar, tips).
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
    { id: 'porto', price: 60, torg: true, title: 'Порту класик, чорний із зеленим дахом', who: 'Дона Тьотя Валя · Рібейра · не дзвоніть до обіду',
      date: '15 травня 2014',
      desc: 'Дід возив на ній туристів ще в 80-х. Салон пахне кавою і шкірою, а лічильник досі рахує в ескудо.' },
    { id: 'golf', price: 90, torg: true, title: 'Гольф, вічний, майже не іржавіє', who: 'Мігел · Гайя · пише лише голосовими',
      date: '14 травня 2014',
      desc: 'Німецька якість, португальський пробіг. Двері зачиняються з першого разу, іноді.' },
    { id: 'nyc', price: 120, torg: true, title: 'Жовте таксі з Нью-Йорка, шашечки в комплекті',
      who: 'Камран · Матозіньюш · «брат привіз контейнером»', date: '17 травня 2014',
      desc: 'Приїхала контейнером, принаймні так каже продавець. Ліхтар на даху працює, шашечки рідні.' },
    { id: 'rickshaw', price: 160, title: 'Рікша, три колеса, жодного дзеркала', who: 'Сатіш · Порту · відповідає дзвінком на дзвінок',
      date: '18 травня 2014',
      desc: 'Пролазить туди, куди іншим не можна. Дах із бахромою, гудок із характером.' },
    { id: 'cab', price: 200, torg: true, title: 'Лондонський кеб, парасолька в бардачку', who: 'ОлеКсій · Фош · не поспішає, і вам не раджу',
      date: '13 травня 2014',
      desc: 'Розвертається на семи метрах. Дощ у комплекті, а от на сонце не розраховуйте.' },
    { id: 'electro', price: 320, title: 'Електро, їде тихо як миша', who: 'Стьопа · Боавішта · пише тихо, їздить ще тихіше',
      date: '16 травня 2014',
      desc: 'Клієнти лякаються, бо не чують, як він під’їхав. Емблем немає, не питайте.' },
    { id: 'horse', price: 500, torg: true, top: true, title: 'Кінь з возом, їсть овес, не бензин',
      who: 'Люда · Кампаньян · лише дзвінки, з шостої ранку', date: '18 травня 2014',
      desc: 'Заводиться з морквини. Пробок не боїться, на світлофорі нервує. Подушка на возі м’яка. Торг за моркву.' }
  ];

  // The car mods (PG.cars.MODS) are sold as listings. PG.cars has no category names and no ad texts: they live here.
  const CATN = { tune: 'Тюнінг', paint: 'Фарба', decal: 'Наклейки', spoiler: 'Спойлери', rims: 'Диски', glow: 'Неон', roof: 'Шашки', exhaust: 'Вихлоп', lights: 'Фари' };
  const CAT_ORDER = ['paint', 'decal', 'spoiler', 'rims', 'glow', 'roof', 'exhaust', 'lights'];
  const TXT = {
    paint_red: { t: 'Фарба червона, пожежна, не розводити', who: 'Ансельму · гараж у Мафамуді · фарбує за готівку', d: 5, torg: 1,
      x: 'Видно здалеку, особливо з гелікоптера. Сохне довго, тому не торкайтеся.' },
    paint_blue: { t: 'Синій металік, як у дорогих', who: 'Рікарду · Лейшойнс · металік справжній, документи теж', d: 6,
      x: 'Блищить на сонці. Дощу не боїться, пташок боїться.' },
    paint_lime: { t: 'Лайм, кислотний, для сміливих', who: 'Тереза · Гайя · дзвонити лише після кави', d: 6, torg: 1,
      x: 'Помітний навіть уночі. Сусіди питали, чи він світиться сам.' },
    paint_violet: { t: 'Фіолетова фарба, колір кінця світу', who: 'Бруну · Ріо-Тінто · відповідає лише на повідомлення', d: 7,
      x: 'Колір вибирав дизайнер із почуттям гумору. Лишився один балон, беріть.' },
    paint_matte: { t: 'Матовий чорний, ні відблиску, ні совісті', who: 'Клара · Порту · «чорний це серйозно»', d: 7, torg: 1,
      x: 'Не блищить, тож подряпин не видно. Мити можна, полірувати не треба.' },
    paint_pearl: { t: 'Перлинна фарба, як зубна паста', who: 'Мануела · Фонтаїнгаш · пише лише смайликами', d: 8,
      x: 'Переливається з рожевого в блакитний. На сонці краще в окулярах.' },
    decal_flames: { t: 'Наклейки «Полум’я», комплект на два боки', who: 'Беатріш · друкарня на розі · гарантія до першої мийки', d: 10, torg: 1,
      x: 'Швидкості не додають, зате додають упевненості. Клеїти на суху і чисту, тобто не на Ланос.' },
    decal_azulejo: { t: 'Азулежу на двері, як на вокзалі Сан-Бенту', who: 'Дона Амелія · Алфама · плитку не відклеювати', d: 9,
      x: 'Синій візерунок, який видно здалеку. Бабусі вже плачуть від захвату.' },
    decal_racing: { t: 'Гоночні смуги, дві білі по центру', who: 'Едуарду · автобаза в Матозіньюш · торгується після обіду', d: 9,
      x: 'З ними Ланос здається швидшим, але лише поки стоїть.' },
    spoiler_lip: { t: 'Малий спойлер на багажник, майже для краси', who: 'Жуау · СТО «Три ключі» · приймає з 9 до 9:15', d: 8,
      x: 'Притискає машину до дороги міліметра на два. Інших ефектів не помічено.' },
    spoiler_wing: { t: 'Крило, як у літака, тільки без літака', who: 'Фернанду · аеродромчик у Віла-Реал · літак продав окремо', d: 8, torg: 1,
      x: 'Дві опори, чотири болти. На сильному вітрі машина злітає лише подумки.' },
    rims_chrome: { t: 'Хромовані диски, блищать навіть у дощ', who: 'Дієґу · Гайя · диски блищать, власник теж', d: 9,
      x: 'Колеса ті самі, видно їх тепер здалеку. Гальмівний пил теж видно.' },
    rims_gold: { t: 'Золоті диски, майже золоті', who: 'Сантуш · ломбард на Байші · пробу не питайте', d: 10, torg: 1,
      x: 'Блищать як золото, а ваги від них мало. Продавець клянеться, що на дотик справжні.' },
    rims_red: { t: 'Червоні диски, колеса як ґудзики', who: 'Лінда · шиномонтаж «Круглий» · без запису, але й без черги', d: 10,
      x: 'Один диск трохи світліший, бо з іншої партії. На швидкості не помітно.' },
    glow_cyan: { t: 'Неон бірюзовий під днище, ніч тепер ваша', who: 'Гонсалу · магазин «Світло» · Лапа', d: 11,
      x: 'Їдете і світитесь. Поліція теж помітить, але це вже ваша справа.' },
    glow_pink: { t: 'Неон рожевий, для тих, хто нічого не соромиться', who: 'Мафалда · Порту · підсвічує все, що не прибите', d: 11,
      x: 'Асфальт під машиною рожевий. Клієнти питають, чи далеко дискотека.' },
    glow_green: { t: 'Неон зелений, як ліхтар на розі', who: 'Руфіну · ліхтарник на пенсії · звик працювати вночі', d: 12, torg: 1,
      x: 'Світиться рівно і м’яко. Коти збираються, звідки, невідомо.' },
    glow_violet: { t: 'Неон фіолетовий, під вечір особливо корисний', who: 'Саломе · готель «Зірка» · біля стійки реєстрації', d: 12,
      x: 'Тихо пульсує, ніби машина дихає. Поряд лягати спати не раджу.' },
    roof_classic: { t: 'Шашка класична, шашечки в комплекті', who: 'Жозе · склад біля порту · шашки з різних міст', d: 12,
      x: 'Клієнти бачать здалеку. Чи сядуть, то вже їхня справа.' },
    roof_led: { t: 'Світлодіодна «ТАКСІ» на дах', who: 'Зіна · Порту · «у травні вже ні для чого»', d: 13, torg: 1,
      x: 'Горить рівно, видно з кінця вулиці. Підключати до запальнички, до серця не треба.' },
    roof_disco: { t: 'Диско-шашка, крутиться і мигає', who: 'Діогу · клуб «Бомба» · після закриття', d: 13, torg: 1,
      x: 'Мигає в такт, але не в ваш. Увечері пасажири просяться сісти, зранку просяться вийти.' },
    exhaust_grey: { t: 'Сірий дим, перевірений часом', who: 'Тоні · СТО на Рібейрі · руки в мастилі, совість чиста', d: 14,
      x: 'Класика. Саме такий дим був у діда, і нічого, возив.' },
    exhaust_pink: { t: 'Рожевий дим, ніби цукрова вата', who: 'Беа · ярмарок у Матозіньюш · по четвергах', d: 14,
      x: 'Пахне не так, як виглядає. Вітер розганяє вже на найближчому перехресті.' },
    exhaust_blue: { t: 'Блакитний дим, як із чарівної труби', who: 'Афонсу · пароплавна компанія · давно не пливе', d: 15,
      x: 'Тонка смужка за машиною. Коли тиснете газ, смужка стає веселішою.' },
    lights_xenon: { t: 'Ксенон, ближнє як на стадіоні', who: 'Рафа · Гайя · світить усім, навіть собі в очі', d: 15, torg: 1,
      x: 'Зустрічні моргають, а ви думаєте, що вітаються.' },
    lights_fog: { t: 'Жовті протитуманки, а туману немає', who: 'Вітор · гараж у Віла-Нова · дивіться на стовп', d: 16,
      x: 'Туман у Порту був у березні, фари чекають далі. Світять приємно, наче свічки.' }
  };

  // Performance tuning (§22): one listing per level; a level needs the one below. pct = the bonus in %.
  const TUNES = [
    { key: 'speed', name: 'Двигун', ico: '⚙', unit: 'швидкості авто', price: [40, 90, 160], pct: [5, 10, 15], d: 19,
      who: 'СТО «Три ключі» · Гайя · руки в мастилі', x: 'Ланос їде швидше, тож і до клієнта швидше. Масло в комплекті, совість окремо.' },
    { key: 'radar', name: 'Радар', ico: '◎', unit: 'радіуса радара', price: [30, 70, 130], pct: [15, 30, 45], d: 19,
      who: 'Рафа · радіомагазин · Порту', x: 'Антена з холодильника, зате бачить замовлення далі. Не питайте, як воно працює.' },
    { key: 'tips', name: 'Кондиціонер', ico: '❄', unit: 'до чайових', price: [25, 60, 110], pct: [10, 20, 30], d: 18,
      who: 'Беа · автомийка · Матозіньюш', x: 'У салоні прохолодно, пасажири добрі й щедрі. Ялинка у подарунок.' }
  ].reduce(function (a, t) {
    for (let i = 0; i < 3; i++) a.push({ id: 'tune_' + t.key + '_' + (i + 1), cat: 'tune', key: t.key, lvl: i + 1, price: t.price[i], pct: t.pct[i], ico: t.ico,
      title: t.name + ', рівень ' + (i + 1) + ': +' + t.pct[i] + ' % ' + t.unit, name: t.name, who: t.who, date: t.d + ' травня 2014', desc: t.x, torg: false,
      effect: '+' + t.pct[i] + ' % ' + t.unit });
    return a;
  }, []);

  function buildMods() {
    const src = PG.cars && Array.isArray(PG.cars.MODS) ? PG.cars.MODS : [];
    return src.map(function (m) {
      const x = TXT[m.id] || {};
      return { id: m.id, cat: m.cat, price: m.price, name: m.name, title: x.t || m.name,
        who: x.who || 'Продавець · Порту · на сайті з 2012', date: (x.d || 12) + ' травня 2014', desc: x.x || 'Без опису, зате з фото.', torg: !!x.torg };
    });
  }
  const MODS = buildMods();   // empty on an old build without PG.cars.MODS: the tuning section then hides

  // fit: the chosen mod per category (owned ones only); mods: the bought ones
  const st = { earned: 0, spent: 0, owned: { lanos: 1 }, skin: 'lanos', mods: {}, fit: {}, tune: { speed: 0, radar: 0, tips: 0 } };   // money in cents
  const flt = { cat: 'all', max: 500, can: false, q: '', sort: 'def' };   // the listing filter and sort (not saved)
  const cmp = [];   // the compared listings, 'kind:id', up to 3
  const CMAX = 3;
  const MAXP = 500;
  let dom = null;

  function store() { try { return root.localStorage || null; } catch (e) { return null; } }

  function load() {
    try {
      const ls = store();
      const raw = ls ? JSON.parse(ls.getItem(KEY) || 'null') : null;
      if (raw) {
        st.earned = Math.max(0, raw.earned | 0);
        st.spent = Math.max(0, raw.spent | 0);
        if (raw.owned) for (const k in raw.owned) if (byId(k)) st.owned[k] = 1;
        if (byId(raw.skin) && st.owned[raw.skin]) st.skin = raw.skin;
        // ids of the old tuning (taxi, stickers, ...) are simply not in the catalog and are dropped here
        if (raw.mods) for (const k in raw.mods) if (modById(k)) st.mods[k] = 1;
        if (raw.tune) for (const k in st.tune) st.tune[k] = Math.max(0, Math.min(3, raw.tune[k] | 0));
      }
    } catch (e) { /* a broken save is ignored */ }
    sanitise(raw0());
    setTune();
  }

  function raw0() {
    try { const ls = store(); const r = ls ? JSON.parse(ls.getItem(KEY) || 'null') : null; return r && r.fit && typeof r.fit === 'object' ? r.fit : {}; } catch (e) { return {}; }
  }

  // The car module keeps the selection it was given last time. Keep only owned mods, one per category.
  function sanitise(saved) {
    if (!MODS.length) return;
    const have = PG.cars && PG.cars.mods ? PG.cars.mods() : {};
    const fit = {};
    CAT_ORDER.forEach(function (cat) {
      [have[cat], saved && saved[cat]].some(function (id) {
        const m = modById(id);
        if (m && m.cat === cat && st.mods[id]) { fit[cat] = id; return true; }
        return false;
      });
    });
    st.fit = fit;
    apply(have);
  }

  function save() {
    try { const ls = store(); if (ls) ls.setItem(KEY, JSON.stringify(st)); } catch (e) { /* storage is full or off */ }
  }

  function byId(id) { for (let i = 0; i < ITEMS.length; i++) if (ITEMS[i].id === id) return ITEMS[i]; return null; }
  function modById(id) { for (let i = 0; i < MODS.length; i++) if (MODS[i].id === id) return MODS[i]; return null; }
  function wallet() { return (st.earned - st.spent) / 100; }
  function owned(id) { return !!st.owned[id]; }
  function ownedMod(id) { return !!st.mods[id]; }
  function fitted(id) { const m = modById(id); return !!(m && st.fit[m.cat] === id); }
  function lack(it) { return it ? Math.max(0, Math.ceil(it.price - wallet() - 1e-9)) : 0; }
  function need(id) { return lack(byId(id)); }
  function needMod(id) { return lack(modById(id)); }
  function tuneById(id) { for (let i = 0; i < TUNES.length; i++) if (TUNES[i].id === id) return TUNES[i]; return null; }
  function ownedTune(id) { const t = tuneById(id); return !!(t && st.tune[t.key] >= t.lvl); }
  function needTune(id) { return lack(tuneById(id)); }
  function lockedTune(id) { const t = tuneById(id); return !!(t && t.lvl > st.tune[t.key] + 1); }
  function buyTune(id) {
    const t = tuneById(id);
    if (!t || ownedTune(id) || lockedTune(id) || needTune(id) > 0) return false;
    st.spent += t.price * 100;
    st.tune[t.key] = t.lvl;
    save(); setTune();
    return true;
  }
  // The multipliers for the engine (1 + level bonus). In party mode the upgrades are off: all 1.
  function tuneK() {
    const k = { speed: 1, radar: 1, tips: 1 }, e = PG.engine;
    if (e && e.party) return k;
    TUNES.forEach(function (t) { if (st.tune[t.key] === t.lvl) k[t.key] = 1 + t.pct / 100; });
    return k;
  }
  function setTune() { if (PG.engine) PG.engine.tune = tuneK(); }
  function find(kind, id) { return kind === 'car' ? byId(id) : kind === 'tune' ? tuneById(id) : modById(id); }
  function isMine(kind, id) { return kind === 'car' ? owned(id) : kind === 'tune' ? ownedTune(id) : ownedMod(id); }
  function catName(kind, it) { return kind === 'car' ? 'Авто' : CATN[it.cat] || 'Тюнінг'; }
  function keyLine(kind, it) { return kind === 'car' ? 'Новий вигляд машини' : kind === 'tune' ? it.effect : 'Лише вигляд, без бонусів'; }
  function dayOf(it) { return parseInt(it.date, 10) || 0; }
  function selection() { const o = {}; for (const k in st.fit) o[k] = st.fit[k]; return o; }

  // Hands the owned selection to the car module (so the map car wears it); `before` skips a call when nothing changes.
  function apply(before) {
    if (!PG.cars || !PG.cars.setMods) return;
    const sel = selection();
    if (before) {
      const same = Object.keys(before).length === Object.keys(sel).length && Object.keys(sel).every(function (k) { return before[k] === sel[k]; });
      if (same) return;
    }
    PG.cars.setMods(sel);
  }

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

  // on: true fits, false takes it off, undefined flips; fitting replaces the mod of the same category
  function fitMod(id, on) {
    const m = modById(id);
    if (!m || !ownedMod(id)) return false;
    const want = on === undefined ? !fitted(id) : !!on;
    if (want) st.fit[m.cat] = id; else if (st.fit[m.cat] === id) delete st.fit[m.cat];
    apply();
    save();
    return true;
  }

  function buyMod(id) {
    const m = modById(id);
    if (!m || ownedMod(id) || needMod(id) > 0) return false;
    st.spent += m.price * 100;
    st.mods[id] = 1;
    return fitMod(id, true);
  }

  function unlockAll() {
    ITEMS.forEach(function (it) { st.owned[it.id] = 1; });
    MODS.forEach(function (m) { st.mods[m.id] = 1; });
    for (const k in st.tune) st.tune[k] = 3;
    save(); setTune();
  }

  // The visible listings for a filter: [{ kind: 'car' | 'mod', it }]. Cars first, then the mods by category.
  function listings(f) {
    f = f || flt;
    const q = String(f.q || '').trim().toLowerCase();
    const max = f.max >= MAXP ? Infinity : f.max;
    const out = [];
    function add(kind, it) {
      const mine = isMine(kind, it.id);
      if (it.price > max) return;
      if (f.can && (mine || lack(it) > 0 || (kind === 'tune' && lockedTune(it.id)))) return;
      const hay = it.title + ' ' + it.desc + ' ' + it.who + (kind === 'car' ? '' : ' ' + CATN[it.cat] + ' ' + (it.effect || ''));
      if (q && hay.toLowerCase().indexOf(q) < 0) return;
      out.push({ kind: kind, it: it });
    }
    if (f.cat === 'all' || f.cat === 'car') ITEMS.forEach(function (it) { add('car', it); });
    if (f.cat === 'all' || f.cat === 'look') CAT_ORDER.forEach(function (cat) { MODS.forEach(function (m) { if (m.cat === cat) add('mod', m); }); });
    if (f.cat === 'all' || f.cat === 'tune') TUNES.forEach(function (t) { add('tune', t); });
    const by = { asc: function (a, b) { return a.it.price - b.it.price; }, desc: function (a, b) { return b.it.price - a.it.price; },
      new: function (a, b) { return dayOf(b.it) - dayOf(a.it); }, eff: function (a, b) { return (b.it.pct || 0) - (a.it.pct || 0); } }[f.sort];
    return by ? out.map(function (r, i) { return [r, i]; }).sort(function (a, b) { return by(a[0], b[0]) || a[1] - b[1]; }).map(function (p) { return p[0]; }) : out;
  }

  // ---- DOM ----
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function isPhone() { try { return !!(root.matchMedia && root.matchMedia('(max-width: 600px)').matches); } catch (e) { return false; } }

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

  // The street background, drawn once per theme and copied under every photo.
  function background() {
    if (dom.bg) return dom.bg;
    const cv = document.createElement('canvas');
    cv.width = PHOTO.w * 2; cv.height = PHOTO.h * 2;
    const c = cv.getContext && cv.getContext('2d');
    if (!c) return null;
    c.scale(2, 2);
    scene(c, root.getComputedStyle(dom.root));
    return (dom.bg = cv);
  }

  // ---- one animation loop for the photos that move (neon, exhaust, disco); off when the shop closes ----
  let anim = [];
  let raf = 0;
  let seen = null;
  function moves(id) { return /^(glow|exhaust)_/.test(id) || id === 'roof_disco'; }

  function paintMod(a) {
    const c = a.cv.getContext('2d');
    c.clearRect(0, 0, a.cv.width, a.cv.height);
    const bg = background();
    if (bg) c.drawImage(bg, 0, 0, a.cv.width, a.cv.height);
    const sel = {}; sel[a.cat] = a.id;
    PG.cars.preview(a.off, st.skin, sel);
    c.drawImage(a.off, 0, 0);
  }

  function frame() {
    raf = 0;
    if (!dom || dom.root.hidden) return;
    anim.forEach(function (a) { if (a.vis !== false && a.cv.isConnected !== false) paintMod(a); });
    raf = root.requestAnimationFrame(frame);
  }
  function startLoop() {
    if (raf || PG.REDUCED || !anim.length || typeof root.requestAnimationFrame !== 'function') return;
    raf = root.requestAnimationFrame(frame);
  }
  function stopLoop() {
    if (raf && typeof root.cancelAnimationFrame === 'function') root.cancelAnimationFrame(raf);
    raf = 0;
  }
  function watch(a) {
    if (typeof root.IntersectionObserver !== 'function') return;
    if (!seen) seen = new root.IntersectionObserver(function (es) { es.forEach(function (e) { if (e.target._a) e.target._a.vis = e.isIntersecting; }); });
    a.vis = false; a.cv._a = a; seen.observe(a.cv);
  }
  function dropAnim(sheetOnly) {
    anim = anim.filter(function (a) {
      const drop = sheetOnly ? a.sheet : !a.sheet;
      if (drop && seen) seen.unobserve(a.cv);
      return !drop;
    });
  }

  // The listing photo. A car: its skin on the street (with the chosen mods on the skin in use).
  // A mod: the selected skin with that one mod, through PG.cars.preview.
  function photo(row, sheet) {
    const it = row.it, car = row.kind === 'car';
    const cv = el('canvas', 'olx-photo');
    cv.width = car ? PHOTO.w * 2 : 540; cv.height = car ? PHOTO.h * 2 : 255;
    cv.setAttribute('role', 'img');
    cv.setAttribute('aria-label', it.title);
    const c = cv.getContext && cv.getContext('2d');
    if (!c) return cv;
    if (car) {
      const bg = background();
      if (bg) c.drawImage(bg, 0, 0);
      c.scale(2, 2);
      if (PG.cars) PG.cars.paint(c, it.id, PHOTO.w / 2, PHOTO.h / 2 - 6, PHOTO.car, '#3df5b0', st.skin === it.id ? selection() : {});
      return cv;
    }
    if (row.kind === 'tune') {
      const bg = background();
      if (bg) c.drawImage(bg, 0, 0, cv.width, cv.height);
      c.fillStyle = '#ffd23f'; c.textAlign = 'center'; c.textBaseline = 'middle';
      c.font = '700 120px system-ui, sans-serif'; c.fillText(it.ico, cv.width / 2, cv.height / 2 - 10);
      c.font = '800 34px system-ui, sans-serif'; c.fillText('+' + it.pct + ' %', cv.width / 2, cv.height - 34);
      return cv;
    }
    if (!PG.cars || !PG.cars.preview) return cv;
    const off = document.createElement('canvas');
    off.width = cv.width; off.height = cv.height;
    const a = { cv: cv, off: off, id: it.id, cat: it.cat, sheet: !!sheet };
    paintMod(a);
    if (moves(it.id) && !PG.REDUCED) { anim.push(a); watch(a); }
    return cv;
  }

  function badge(cls, text) { return el('span', 'olx-badge ' + cls, text); }

  function cmpKey(row) { return row.kind + ':' + row.it.id; }
  function cmpSync() {
    if (!dom) return;
    const boxes = dom.root.querySelectorAll ? dom.root.querySelectorAll('.olx-cmpbox') : [];
    for (let i = 0; i < boxes.length; i++) boxes[i].checked = cmp.indexOf(boxes[i].getAttribute('data-k')) >= 0;
    dom.tray.hidden = !cmp.length;
    dom.root.classList.toggle('has-tray', cmp.length > 0);
    dom.trayN.textContent = 'Порівняння: ' + cmp.length + ' з ' + CMAX;
    dom.trayGo.disabled = cmp.length < 2;
  }
  // on: true adds, false removes, undefined flips; a 4th listing is refused
  function toggleCmp(key, on) {
    const i = cmp.indexOf(key);
    const want = on === undefined ? i < 0 : !!on;
    if (want && i < 0) { if (cmp.length >= CMAX) { if (PG.bus) PG.bus.emit('note', { text: 'Порівняти можна до ' + CMAX + ' оголошень', ms: 1800 }); cmpSync(); return false; } cmp.push(key); }
    if (!want && i >= 0) cmp.splice(i, 1);
    cmpSync();
    return true;
  }

  // One listing. `full` is the sheet version; the grid shows a dense card (photo, price, category, one key line) and on a phone a tap opens the sheet.
  function card(row, full) {
    const kind = row.kind, car = kind === 'car', it = row.it;
    const mine = isMine(kind, it.id);
    const on = car && mine && st.skin === it.id;
    const lock = kind === 'tune' && lockedTune(it.id);
    const n = lack(it);
    const a = el('article', 'olx-ad' + (car ? '' : ' olx-tune') + (full ? ' full' : ''));
    a.setAttribute('data-' + (car ? 'skin' : kind), it.id);
    a.title = it.desc;
    const ph = el('div', 'olx-ph');
    ph.appendChild(photo(row, full));
    if (it.top) ph.appendChild(el('span', 'olx-top', 'ТОП'));
    if (kind === 'mod' && fitted(it.id)) ph.appendChild(el('span', 'olx-top fit', 'Встановлено'));
    a.appendChild(ph);
    const b = el('div', 'olx-body');
    const rowEl = el('div', 'olx-row');
    rowEl.appendChild(el('h3', 'olx-name', it.title));
    rowEl.appendChild(el('span', 'olx-price' + (it.cur ? ' own' : ''), it.cur || PG.util.eur(it.price)));
    b.appendChild(rowEl);
    const tags = el('div', 'olx-tags');
    tags.appendChild(badge('kind', catName(kind, it)));
    if (it.torg) tags.appendChild(badge('torg', 'торг'));
    if (mine) tags.appendChild(badge('mine', car ? 'у гаражі' : kind === 'tune' ? 'встановлено' : 'куплено'));
    b.appendChild(tags);
    b.appendChild(el('p', 'olx-key', keyLine(kind, it)));
    b.appendChild(el('p', 'olx-who', it.who));
    b.appendChild(el('p', 'olx-date', 'Опубліковано ' + it.date));
    b.appendChild(el('p', 'olx-desc', it.desc));
    if (!mine && n > 0 && !lock) {
      const bar = el('div', 'olx-need');
      const fill = el('i');
      fill.style.width = Math.min(100, Math.round(100 * Math.max(0, wallet()) / it.price)) + '%';
      bar.appendChild(fill);
      b.appendChild(bar);
    }
    const cl = el('label', 'olx-cmpl');
    const cb = el('input', 'olx-cmpbox'); cb.type = 'checkbox';
    cb.setAttribute('data-k', cmpKey(row));
    cb.checked = cmp.indexOf(cmpKey(row)) >= 0;
    cb.addEventListener('change', function () { if (!toggleCmp(cmpKey(row), cb.checked)) cb.checked = false; });
    cl.addEventListener('click', function (e) { if (e && e.stopPropagation) e.stopPropagation(); });
    cl.appendChild(cb); cl.appendChild(el('span', '', 'Порівняти'));
    b.appendChild(cl);
    let label, cls, off = false;
    if (car) {
      label = on ? 'Обрано' : mine ? 'Обрати' : n === 0 ? 'Купити' : 'Не вистачає ' + PG.util.eur(n);
      cls = on ? 'on' : mine || n === 0 ? 'buy' : 'no';
      off = on || (!mine && n > 0);
    } else if (kind === 'tune') {
      label = mine ? 'Встановлено' : lock ? 'Спершу рівень ' + (it.lvl - 1) : n === 0 ? 'Купити' : 'Не вистачає ' + PG.util.eur(n);
      cls = mine ? 'on' : lock || n > 0 ? 'no' : 'buy';
      off = mine || lock || n > 0;
    } else {
      label = mine ? (fitted(it.id) ? 'Зняти' : 'Встановити') : n === 0 ? 'Купити' : 'Не вистачає ' + PG.util.eur(n);
      cls = mine ? (fitted(it.id) ? 'alt' : 'buy') : n === 0 ? 'buy' : 'no';
      off = !mine && n > 0;
    }
    const act = el('button', 'olx-btn ' + cls, label);
    act.type = 'button';
    act.disabled = off;
    act.addEventListener('click', function (e) {
      if (e && e.stopPropagation) e.stopPropagation();
      if (car) { if (!mine) buy(it.id); else pick(it.id); }
      else if (kind === 'tune') buyTune(it.id);
      else if (!mine) buyMod(it.id);
      else fitMod(it.id);
      refresh();
    });
    b.appendChild(act);
    a.appendChild(b);
    if (!full) {
      const go = function () { if (isPhone()) openSheet(row.kind, it.id); };
      a.addEventListener('click', go);
      if (isPhone()) {
        a.setAttribute('tabindex', '0');
        a.setAttribute('aria-label', it.title + ', ' + (it.cur || PG.util.eur(it.price)));
        a.addEventListener('keydown', function (e) { if (e.target === a && (e.key === 'Enter' || e.key === ' ')) { if (e.preventDefault) e.preventDefault(); go(); } });
      }
    }
    return a;
  }

  // ---- the comparison table (up to 3 listings side by side), in the sheet layer ----
  function renderCmp() {
    const c = dom.cmp;
    c.panel.textContent = '';
    const rows = cmp.map(function (k) { const p = k.split(':'); const it = find(p[0], p.slice(1).join(':')); return it ? { kind: p[0], it: it } : null; }).filter(Boolean);
    const x = el('button', 'olx-sheet-x olx-cmp-x'); x.type = 'button'; x.setAttribute('aria-label', 'Закрити');
    x.appendChild(el('span', 'olx-x'));
    x.addEventListener('click', closeCmp);
    c.panel.appendChild(el('h2', 'olx-cmp-h', 'Порівняння'));
    const t = el('table', 'olx-table');
    const head = el('tr'); head.appendChild(el('th', 'olx-corner'));
    rows.forEach(function (r) { head.appendChild(el('th', '', r.it.name || r.it.title)); });
    t.appendChild(head);
    [['Ціна', function (r) { return r.it.cur || PG.util.eur(r.it.price); }],
     ['Категорія', function (r) { return catName(r.kind, r.it); }],
     ['Ефект', function (r) { return keyLine(r.kind, r.it); }],
     ['Вже є', function (r) { return isMine(r.kind, r.it.id) ? 'так' : 'ні'; }]].forEach(function (d) {
      const tr = el('tr'); tr.appendChild(el('th', '', d[0]));
      rows.forEach(function (r) { tr.appendChild(el('td', '', d[1](r))); });
      t.appendChild(tr);
    });
    c.panel.appendChild(t);
    c.panel.appendChild(x);
  }
  function openCmp() {
    if (!dom || cmp.length < 2) return false;
    renderCmp();
    dom.cmp.root.hidden = false;
    return true;
  }
  function closeCmp() { if (dom) dom.cmp.root.hidden = true; }
  function clearCmp() { cmp.length = 0; closeCmp(); cmpSync(); }

  // ---- the sheet: the full listing over the phone gallery ----
  function rowOf(kind, id) { const it = find(kind, id); return it ? { kind: kind, it: it } : null; }

  function renderSheet() {
    if (!dom || !dom.sheet) return;
    const sh = dom.sheet;
    dropAnim(true);
    sh.panel.textContent = '';
    const row = sh.key ? rowOf(sh.key[0], sh.key[1]) : null;
    if (!row) { sh.root.hidden = true; return; }
    const x = el('button', 'olx-sheet-x'); x.type = 'button'; x.setAttribute('aria-label', 'Закрити');
    x.appendChild(el('span', 'olx-x'));
    x.addEventListener('click', closeSheet);
    sh.panel.appendChild(card(row, true));
    sh.panel.appendChild(x);
    sh.root.hidden = false;
    startLoop();
  }

  function openSheet(kind, id) {
    if (!dom || !dom.sheet) return false;
    if (!rowOf(kind, id)) return false;
    dom.sheet.key = [kind, id];
    dom.root.className = 'sheet-open';
    renderSheet();
    if (dom.sheet.panel.querySelector) { const x = dom.sheet.panel.querySelector('.olx-sheet-x'); if (x && x.focus) x.focus(); }
    return true;
  }

  function closeSheet() {
    if (!dom || !dom.sheet) return;
    dom.sheet.key = null;
    dom.sheet.root.hidden = true;
    dom.sheet.panel.textContent = '';
    dom.root.className = '';
    dropAnim(true);
  }

  function refresh() {
    if (!dom) return;
    dom.wal.textContent = PG.util.eur(wallet());
    renderAds();
    renderSheet();
    if (!dom.cmp.root.hidden) renderCmp();
    updateButton();
  }

  function renderAds() {
    dropAnim(false);
    dom.ads.textContent = '';
    const rows = listings(flt);
    dom.count.textContent = rows.length ? 'Знайдено: ' + rows.length : '';
    if (!rows.length) {
      dom.ads.appendChild(el('p', 'olx-empty', flt.can ? 'Поки що нічого не по кишені. Відкатайте ще одну зміну.' : 'Нічого не знайшли. Спробуйте інший запит.'));
      return;
    }
    // sections: the cars, then one per mod category (the gallery on a phone, the grid on a PC)
    if (flt.cat === 'tune' && flt.sort !== 'def') dom.ads.appendChild(el('p', 'olx-note', 'Покращення діють в одиночній грі. У «Гра разом» вони вимкнені, бій чесний. Вигляд працює скрізь.'));
    let last = '';
    rows.forEach(function (r) {
      const key = r.kind === 'car' ? 'car' : r.it.cat;
      if (key !== last && flt.cat !== 'car' && flt.sort === 'def') {
        const h = el('h2', 'olx-sec', key === 'car' ? 'Авто' : CATN[key]);
        h.setAttribute('data-sec', key);
        dom.ads.appendChild(h);
        if (key === 'tune') dom.ads.appendChild(el('p', 'olx-note', 'Покращення діють в одиночній грі. У «Гра разом» вони вимкнені, бій чесний. Вигляд працює скрізь.'));
      }
      last = key;
      dom.ads.appendChild(card(r, false));
    });
    startLoop();
  }

  function updateButton() {
    if (typeof document === 'undefined') return;
    const b = document.getElementById('btn-shop');
    if (b) b.querySelector('.olx-open-wal').textContent = PG.util.eur(wallet());
  }

  // Both filter sets (phone chips, PC sidebar) write into `flt` and are kept in step.
  function syncFilter() {
    if (!dom) return;
    if (!MODS.length && flt.cat === 'look') flt.cat = 'all';
    dom.chips.forEach(function (c) {
      const on = c.key === 'cheap' ? flt.max < MAXP : c.key === 'can' ? flt.can : c.key === flt.cat;
      c.btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      c.btn.className = 'olx-chip' + (on ? ' on' : '');
    });
    dom.radios.forEach(function (r) { r.checked = r.value === flt.cat; });
    dom.can.checked = flt.can;
    dom.sort.value = flt.sort;
    dom.range.value = String(flt.max);
    dom.rangeOut.textContent = flt.max >= MAXP ? 'без обмеження' : 'до ' + PG.util.eur(flt.max);
    renderAds();
  }

  function buildFilters(bar, side) {
    const CATS = [['all', 'Усе'], ['car', 'Авто']];
    if (MODS.length) CATS.push(['look', 'Вигляд']);
    CATS.push(['tune', 'Тюнінг']);
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
    chip('cheap', 'До €100', function () { flt.max = flt.max < MAXP ? MAXP : 100; });
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
    r.setAttribute('role', 'dialog'); r.setAttribute('aria-label', 'ОЛЕКС');
    const head = el('div', 'olx-head');
    const top = el('div', 'olx-topbar');
    const back = el('button', 'olx-back'); back.type = 'button'; back.setAttribute('aria-label', 'Назад');
    back.appendChild(el('span', 'olx-chev'));
    back.addEventListener('click', close);
    top.appendChild(back);
    const logo = el('div', 'olx-logo');
    logo.appendChild(el('span', 'olx-mark'));
    logo.appendChild(el('span', '', 'ОЛЕКС'));
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
    const qrow = el('div', 'olx-qrow');
    qrow.appendChild(q);
    const sort = el('select', 'olx-sort'); sort.setAttribute('aria-label', 'Сортування');
    [['def', 'Сортування'], ['asc', 'Ціна ↑'], ['desc', 'Ціна ↓'], ['new', 'Новизна'], ['eff', 'Ефект']].forEach(function (o) {
      const op = el('option', '', o[1]); op.value = o[0]; sort.appendChild(op);
    });
    sort.addEventListener('change', function () { flt.sort = sort.value; renderAds(); });
    qrow.appendChild(sort);
    bar.appendChild(qrow);
    const main = el('div', 'olx-main');
    const side = el('aside', 'olx-side'); side.setAttribute('aria-label', 'Фільтри');
    const list = el('div', 'olx-list');
    const count = el('p', 'olx-count', '');
    count.setAttribute('aria-live', 'polite');
    const ads = el('div', 'olx-ads');
    list.appendChild(count); list.appendChild(ads);
    main.appendChild(side); main.appendChild(list);
    dom = { root: r, wal: wal, ads: ads, count: count, q: q, sort: sort, bg: null, sheet: null };
    buildFilters(bar, side);
    r.appendChild(bar);
    r.appendChild(main);
    const sr = el('div', 'olx-sheet'); sr.hidden = true;
    sr.setAttribute('role', 'dialog'); sr.setAttribute('aria-label', 'Оголошення');
    const panel = el('div', 'olx-sheet-panel');
    sr.appendChild(panel);
    sr.addEventListener('click', function (e) { if (e.target === sr) closeSheet(); });
    r.appendChild(sr);
    dom.sheet = { root: sr, panel: panel, key: null };
    const cr = el('div', 'olx-cmp'); cr.hidden = true;
    cr.setAttribute('role', 'dialog'); cr.setAttribute('aria-label', 'Порівняння');
    const cpanel = el('div', 'olx-sheet-panel');
    cr.appendChild(cpanel);
    cr.addEventListener('click', function (e) { if (e.target === cr) closeCmp(); });
    r.appendChild(cr);
    dom.cmp = { root: cr, panel: cpanel };
    const tray = el('div', 'olx-tray'); tray.hidden = true;
    dom.trayN = el('span', 'olx-tray-n', '');
    dom.trayGo = el('button', 'olx-btn buy olx-tray-go', 'Порівняти'); dom.trayGo.type = 'button';
    dom.trayGo.addEventListener('click', openCmp);
    const trayX = el('button', 'olx-btn alt olx-tray-x', 'Очистити'); trayX.type = 'button';
    trayX.addEventListener('click', clearCmp);
    tray.appendChild(dom.trayN); tray.appendChild(dom.trayGo); tray.appendChild(trayX);
    r.appendChild(tray);
    dom.tray = tray;
    r.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !dom.cmp.root.hidden) { closeCmp(); if (e.stopPropagation) e.stopPropagation(); }
      else if (e.key === 'Escape' && dom.sheet.key) { closeSheet(); if (e.stopPropagation) e.stopPropagation(); } });
    if (root.addEventListener) {
      let was = isPhone();
      root.addEventListener('resize', function () {
        const now = isPhone();
        if (now !== was) { was = now; if (!now) closeSheet(); if (!dom.root.hidden) renderAds(); }
      });
    }
    (document.getElementById('app') || document.body).appendChild(r);
  }

  function open() {
    if (typeof document === 'undefined') return;
    if (!dom) build();
    dom.bg = null;                                   // the theme may have changed since the last visit
    dom.q.value = flt.q;
    closeSheet();
    dom.root.hidden = false;
    syncFilter();
    refresh();
    cmpSync();
    dom.root.scrollTop = 0;
  }

  function close() {
    stopLoop();
    if (dom) { closeSheet(); closeCmp(); dom.root.hidden = true; dropAnim(false); }
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
    ITEMS: ITEMS, MODS: MODS, CATN: CATN, KEY: KEY, wallet: wallet, owned: owned, need: need, earn: earn, buy: buy, pick: pick,
    ownedMod: ownedMod, needMod: needMod, buyMod: buyMod, fitMod: fitMod, fitted: fitted, selection: selection,
    listings: listings, filter: flt, unlockAll: unlockAll, skin: function () { return st.skin; }, open: open, close: close,
    openSheet: openSheet, closeSheet: closeSheet, TUNES: TUNES, tuneLevel: function (k) { return st.tune[k] || 0; },
    ownedTune: ownedTune, needTune: needTune, buyTune: buyTune, tuneK: tuneK, setTune: setTune,
    compare: { list: function () { return cmp.slice(); }, toggle: toggleCmp, open: openCmp, close: closeCmp, clear: clearCmp, max: CMAX }
  };
  if (PG.bus) {
    PG.bus.on('shift:end', function (e) { if (e && e.result) { earn(e.result.earned); updateButton(); } });
    PG.bus.on('ui:screen', function (e) {
      if (typeof document === 'undefined' || !e) return;
      if (e.name === 'menu') ensureButton();
      setTune();
      if (e.name !== 'menu') close();
    });
  }
})(typeof window !== 'undefined' ? window : globalThis);
