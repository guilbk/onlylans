// Node test of 68_shop.js: wallet from shift results, buying, choosing, tuning, listings and filters,
// demo unlock, storage, and the DOM containers of both layouts (phone chips, PC sidebar) on a small fake DOM.
import vm from 'node:vm'; import fs from 'node:fs'; import assert from 'node:assert';

function fresh(saved, store) {
  const mem = store || new Map();
  if (saved) mem.set('porto-lanosiv-shop-v1', JSON.stringify(saved));
  globalThis.localStorage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  globalThis.PG = {};
  for (const f of ['00_core', '41_cars', '68_shop']) {
    vm.runInThisContext(fs.readFileSync(new URL(`../game/src/js/${f}.js`, import.meta.url), 'utf8'));
  }
  return { PG, S: PG.shop, mem, end: (e) => PG.bus.emit('shift:end', { result: { earned: e } }) };
}

{ // start: only the Lanos, empty wallet
  const { S, PG } = fresh();
  assert.equal(S.wallet(), 0);
  assert.equal(S.skin(), 'lanos');
  assert.equal(S.ITEMS.length, 9);
  assert.deepEqual(S.ITEMS.map((i) => i.id), PG.cars.SKINS.map((s) => s.id));
  assert.deepEqual(S.ITEMS.map((i) => i.price), [0, 30, 60, 90, 120, 160, 200, 320, 500]);
  assert.ok(S.owned('lanos') && !S.owned('matiz'));
  assert.equal(S.need('matiz'), 30);
  assert.equal(S.buy('matiz'), false);
}

{ // shifts add up, buying spends and selects, the save survives a reload
  const { S, PG, end, mem } = fresh();
  end(12.5); end(20.25); end(0); end(-3); end(NaN);
  assert.equal(S.wallet(), 32.75);
  assert.equal(S.need('porto'), 28);                       // 60 - 32.75, rounded up
  assert.equal(S.buy('matiz'), true);
  assert.equal(S.wallet(), 2.75);
  assert.equal(S.skin(), 'matiz');
  assert.equal(PG.cars.skin(), 'matiz');
  assert.equal(S.buy('matiz'), false);                     // already owned
  assert.equal(S.pick('lanos'), true);
  assert.equal(S.pick('golf'), false);                     // not owned
  assert.equal(PG.cars.skin(), 'lanos');
  const again = fresh(JSON.parse(mem.get('porto-lanosiv-shop-v1')));
  assert.equal(again.S.wallet(), 2.75);
  assert.ok(again.S.owned('matiz'));
  assert.equal(again.S.skin(), 'lanos');
}

{ // the chosen skin is applied to the cars on load; unknown or not owned ones are ignored
  assert.equal(fresh({ earned: 0, spent: 0, owned: { lanos: 1, cab: 1 }, skin: 'cab' }).PG.cars.skin(), 'cab');
  assert.equal(fresh({ earned: 0, spent: 0, owned: { lanos: 1 }, skin: 'horse' }).PG.cars.skin(), 'lanos');
  assert.equal(fresh({ earned: -5, spent: 'x', owned: { nope: 1 }, skin: 7 }).S.wallet(), 0);
}

{ // demo unlock opens everything, wallet unchanged
  const { S } = fresh();
  S.unlockAll();
  assert.ok(S.ITEMS.every((i) => S.owned(i.id)));
  assert.equal(S.wallet(), 0);
  assert.equal(S.pick('horse'), true);
}

{ // an unknown skin falls back to the Lanos in the car module
  const { PG } = fresh();
  PG.cars.setSkin('nope');
  assert.equal(PG.cars.skin(), 'lanos');
}
{ // a listing for every skin, with a title, a seller, a May 2014 date and a joke; the Lanos one is the stated text
  const { S, PG } = fresh();
  for (const sk of PG.cars.SKINS) {
    const it = S.ITEMS.find((i) => i.id === sk.id);
    assert.ok(it, `listing for ${sk.id}`);
    assert.ok(it.title && it.who && it.desc, `texts of ${sk.id}`);
    assert.match(it.date, /травня 2014$/, `date of ${sk.id}`);
  }
  assert.equal(S.ITEMS[0].title, 'Ланос 2007, 1500 $, торг, не бита (майже)');
  assert.equal(S.ITEMS[0].price, 0);
  assert.ok(S.ITEMS.some((i) => i.torg));
  assert.equal(S.listings({ cat: 'all', max: 500, can: false, q: '' }).length, S.ITEMS.length + S.MODS.length + S.TUNES.length);
}

{ // one listing per catalog mod: priced from the catalog, dated May 2014, with a seller and a joke, cosmetic only
  const { S, PG } = fresh();
  assert.equal(S.MODS.length, PG.cars.MODS.length);
  for (const m of PG.cars.MODS) {
    const t = S.MODS.find((x) => x.id === m.id);
    assert.ok(t, `listing for ${m.id}`);
    assert.equal(t.price, m.price);
    assert.equal(t.cat, m.cat);
    assert.ok(t.title && t.who && t.desc, m.id);
    assert.match(t.date, /травня 2014$/);
    assert.ok(!('speed' in t) && !('fare' in t) && !('boost' in t), `${m.id} has no gameplay field`);
    assert.ok(/[А-Яа-яІіЇїЄє]/.test(t.title + t.who + t.desc));
  }
  for (const cat of ['paint', 'decal', 'spoiler', 'rims', 'glow', 'roof', 'exhaust', 'lights']) assert.ok(S.CATN[cat], cat);
  assert.ok(S.MODS.some((t) => t.torg));
  assert.ok(!S.MODS.some((t) => S.ITEMS.some((i) => i.id === t.id)));
}

{ // mods: refused without money, bought with enough, fitted and taken off, saved, wallet reduced, map car updated
  const { S, PG, end, mem } = fresh();
  assert.equal(S.needMod('paint_red'), 20);
  assert.equal(S.buyMod('paint_red'), false);
  assert.equal(S.fitted('paint_red'), false);
  assert.equal(S.buyMod('nope'), false);
  assert.deepEqual(PG.cars.mods(), {});
  end(50);
  assert.equal(S.buyMod('paint_red'), true);
  assert.equal(S.wallet(), 30);
  assert.ok(S.ownedMod('paint_red') && S.fitted('paint_red'));
  assert.deepEqual(PG.cars.mods(), { paint: 'paint_red' });
  assert.equal(S.buyMod('paint_red'), false);              // already owned
  assert.equal(S.fitMod('paint_red'), true);               // flips to off
  assert.equal(S.fitted('paint_red'), false);
  assert.deepEqual(PG.cars.mods(), {});
  assert.equal(S.fitMod('glow_pink'), false);              // not owned
  assert.equal(S.fitMod('paint_red', true), true);
  // one per category: a second paint replaces the first; other categories stay
  assert.equal(S.buyMod('glow_pink'), true);
  assert.equal(S.buyMod('paint_blue'), false);             // 30 - 30 = 0 left, blue costs 20
  end(20);
  assert.equal(S.buyMod('paint_blue'), true);
  assert.deepEqual(PG.cars.mods(), { paint: 'paint_blue', glow: 'glow_pink' });
  assert.equal(S.fitted('paint_red'), false);
  assert.equal(S.fitMod('paint_red', true), true);
  assert.deepEqual(PG.cars.mods(), { paint: 'paint_red', glow: 'glow_pink' });
  assert.equal(S.skin(), 'lanos');                         // cosmetic: the skin and the wallet rules are untouched
  const again = fresh(JSON.parse(mem.get('porto-lanosiv-shop-v1')), mem);
  assert.equal(again.S.wallet(), 0);
  assert.ok(again.S.ownedMod('paint_red') && again.S.ownedMod('paint_blue') && again.S.fitted('paint_red'));
  assert.deepEqual(again.PG.cars.mods(), { paint: 'paint_red', glow: 'glow_pink' });
}

{ // on load the car module's selection is cut down to owned mods; old tuning ids load without errors
  const mem = new Map([['lanos.mods', JSON.stringify({ paint: 'paint_red', glow: 'glow_pink', roof: 'roof_led' })]]);
  const r = fresh({ earned: 0, spent: 0, owned: { lanos: 1 }, mods: { glow_pink: 1 } }, mem);
  assert.deepEqual(r.PG.cars.mods(), { glow: 'glow_pink' });
  assert.deepEqual(JSON.parse(mem.get('lanos.mods')), { glow: 'glow_pink' });
  const none = fresh({ earned: 0, spent: 0, owned: { lanos: 1 } }, new Map([['lanos.mods', JSON.stringify({ paint: 'paint_red' })]]));
  assert.deepEqual(none.PG.cars.mods(), {});
  const old = fresh({ earned: 500, spent: 14, owned: { lanos: 1 }, tune: { taxi: 1, rims: 1 }, fit: { taxi: 1, rims: 1 } });
  assert.equal(old.S.wallet(), 4.86);
  assert.deepEqual(old.S.selection(), {});
  assert.deepEqual(old.PG.cars.mods(), {});
  assert.ok(!old.S.ownedMod('taxi') && !old.S.ownedMod('rims'));
  assert.equal(fresh({ owned: { lanos: 1 }, mods: { nope: 1, rims_gold: 1 }, fit: { rims: 'rims_gold', glow: 'rims_gold' } }).S.fitted('rims_gold'), true);
  assert.deepEqual(fresh({ owned: { lanos: 1 }, mods: { rims_gold: 1 }, fit: { glow: 'rims_gold' } }).S.selection(), {});
}

{ // tuning: 3 levels each, in order, bought with the wallet, saved, multipliers for the engine, off in party mode
  const { S, PG, end, mem } = fresh();
  assert.equal(S.TUNES.length, 9);
  assert.deepEqual(S.TUNES.filter((t) => t.key === 'speed').map((t) => [t.price, t.pct]), [[40, 5], [90, 10], [160, 15]]);
  assert.deepEqual(S.TUNES.filter((t) => t.key === 'radar').map((t) => t.pct), [15, 30, 45]);
  assert.deepEqual(S.TUNES.filter((t) => t.key === 'tips').map((t) => t.pct), [10, 20, 30]);
  assert.deepEqual(S.tuneK(), { speed: 1, radar: 1, tips: 1 });
  PG.engine = { tune: { speed: 1, radar: 1, tips: 1 }, party: null };
  assert.equal(S.buyTune('tune_speed_1'), false);          // empty wallet
  end(500);
  assert.equal(S.buyTune('tune_speed_2'), false);          // level 2 needs level 1
  assert.equal(S.buyTune('tune_speed_1'), true);
  assert.equal(S.wallet(), 460);
  assert.equal(S.buyTune('tune_speed_1'), false);          // already there
  assert.ok(S.ownedTune('tune_speed_1') && !S.ownedTune('tune_speed_2'));
  assert.equal(PG.engine.tune.speed, 1.05);
  assert.equal(S.buyTune('tune_speed_2'), true);
  assert.equal(PG.engine.tune.speed, 1.1);
  assert.ok(S.ownedTune('tune_speed_1') && S.ownedTune('tune_speed_2'));   // lower levels count as owned
  assert.equal(S.buyTune('tune_radar_1'), true);
  assert.equal(PG.engine.tune.radar, 1.15);
  assert.equal(PG.engine.tune.tips, 1);
  assert.equal(S.tuneLevel('speed'), 2);
  assert.ok(JSON.parse(mem.get('porto-lanosiv-shop-v1')).tune.speed === 2);
  PG.engine.party = { clock() { return 0; } };             // party: a fair battle, all 1
  S.setTune();
  assert.deepEqual(PG.engine.tune, { speed: 1, radar: 1, tips: 1 });
  PG.engine.party = null; S.setTune();
  assert.equal(PG.engine.tune.speed, 1.1);
  const again = fresh(JSON.parse(mem.get('porto-lanosiv-shop-v1')));   // the levels survive a reload
  assert.equal(again.S.tuneLevel('speed'), 2);
  assert.equal(again.S.tuneLevel('radar'), 1);
  assert.equal(fresh({ owned: { lanos: 1 }, tune: { speed: 9, radar: -2, taxi: 1 } }).S.tuneLevel('speed'), 3);
  assert.equal(fresh({ owned: { lanos: 1 }, tune: { speed: 9, radar: -2 } }).S.tuneLevel('radar'), 0);
  const un = fresh(); un.S.unlockAll();
  assert.ok(['speed', 'radar', 'tips'].every((k) => un.S.tuneLevel(k) === 3));
}

{ // sort and compare
  const { S } = fresh();
  const F = (o) => S.listings(Object.assign({ cat: 'all', max: 500, can: false, q: '' }, o)).map((r) => r.it);
  const asc = F({ sort: 'asc' }).map((i) => i.price);
  assert.deepEqual(asc, [...asc].sort((a, b) => a - b));
  const desc = F({ sort: 'desc' }).map((i) => i.price);
  assert.deepEqual(desc, [...desc].sort((a, b) => b - a));
  assert.equal(F({ sort: 'eff' })[0].pct, 45);
  assert.ok(F({ sort: 'new' })[0].date.startsWith('19'));
  assert.equal(F({ cat: 'tune', sort: 'new' }).length, 9);
  const C = S.compare;
  assert.equal(C.toggle('car:matiz'), true);
  assert.equal(C.toggle('tune:tune_radar_1'), true);
  assert.equal(C.toggle('mod:paint_red'), true);
  assert.equal(C.toggle('car:golf'), false);               // a 4th is refused
  assert.deepEqual(C.list(), ['car:matiz', 'tune:tune_radar_1', 'mod:paint_red']);
  C.toggle('car:matiz', false);
  assert.equal(C.list().length, 2);
  C.clear();
  assert.equal(C.list().length, 0);
}

{ // no PG.cars.MODS (old build): no mod listings, the shop loads
  globalThis.localStorage = { getItem: () => null, setItem() {} };
  globalThis.PG = {};
  for (const f of ['00_core', '68_shop']) vm.runInThisContext(fs.readFileSync(new URL(`../game/src/js/${f}.js`, import.meta.url), 'utf8'));
  assert.equal(PG.shop.MODS.length, 0);
  assert.equal(PG.shop.listings({ cat: 'all', max: 500, can: false, q: '' }).length, PG.shop.ITEMS.length + PG.shop.TUNES.length);
  assert.equal(PG.shop.listings({ cat: 'look', max: 500, can: false, q: '' }).length, 0);
  assert.equal(PG.shop.buyMod('paint_red'), false);
}

{ // the demo unlock opens the mods too
  const { S } = fresh();
  S.unlockAll();
  assert.ok(S.MODS.every((t) => S.ownedMod(t.id)));
  assert.equal(S.wallet(), 0);
}

{ // filters: category, price, can-buy, search
  const { S, end } = fresh();
  const F = (o) => S.listings(Object.assign({ cat: 'all', max: 500, can: false, q: '' }, o));
  assert.equal(F({ cat: 'car' }).length, 9);
  assert.equal(F({ cat: 'look' }).length, S.MODS.length);
  assert.equal(F({ cat: 'tune' }).length, 9);
  assert.ok(F({ cat: 'car' }).every((r) => r.kind === 'car'));
  assert.ok(F({ max: 100 }).every((r) => r.it.price <= 100));
  assert.ok(F({ max: 100 }).some((r) => r.it.id === 'lanos'));
  assert.equal(F({ can: true }).length, 0);                // empty wallet, the Lanos is owned
  end(40);
  assert.deepEqual(F({ can: true }).map((r) => r.it.id).sort(), ['matiz', 'tune_radar_1', 'tune_speed_1', 'tune_tips_1', ...S.MODS.filter((m) => m.price <= 40).map((m) => m.id)].sort());
  assert.ok(F({ q: 'Неон' }).length >= 4 && F({ q: 'Неон' }).every((r) => r.kind === 'mod'));
  assert.deepEqual(F({ q: 'ЕЛЕКТРО' }).map((r) => r.it.id), ['electro']);
  assert.equal(F({ q: 'x-no-such-listing' }).length, 0);
}

{ // DOM: both layouts have their containers, one card per listing, and the button states
  const mk = (tag) => {
    const kids = [];
    const e = {
      tag, children: kids, className: '', style: {}, attrs: {}, _t: '', listeners: {}, hidden: false, id: '',
      appendChild(c) { kids.push(c); c.parent = e; return c; },
      insertBefore(c) { kids.push(c); return c; },
      setAttribute(k, v) { e.attrs[k] = String(v); },
      addEventListener(ev, fn) { (e.listeners[ev] = e.listeners[ev] || []).push(fn); },
      getContext() { return null; },
      querySelector() { return null; },
      getAttribute(k) { return e.attrs[k] ?? null; },
      querySelectorAll(sel) { const c = sel.slice(1); const out = []; const walk = (n) => n.children.forEach((k) => { if (` ${k.className} `.includes(` ${c} `)) out.push(k); walk(k); }); walk(e); return out; },
      classList: { toggle(c, on) { const l = e.className.split(' ').filter((x) => x && x !== c); if (on) l.push(c); e.className = l.join(' '); } },
      get textContent() { return e._t + kids.map((k) => k.textContent).join(''); },
      set textContent(v) { e._t = v; kids.length = 0; }
    };
    return e;
  };
  const all = (e, out = []) => { out.push(e); e.children.forEach((c) => all(c, out)); return out; };
  const has = (e, cls) => all(e).filter((n) => ` ${n.className} `.includes(` ${cls} `));
  const body = mk('body');
  globalThis.document = { createElement: mk, getElementById: () => null, body };
  const { S, end } = fresh();
  end(100);
  S.open();
  const shop = body.children[0];
  assert.equal(shop.id, 'shop');
  assert.equal(shop.hidden, false);
  assert.equal(has(shop, 'olx-bar').length, 1);            // sticky search and chips (phone)
  assert.equal(has(shop, 'olx-chips').length, 1);
  assert.equal(has(shop, 'olx-chip').length, 6);
  assert.equal(has(shop, 'olx-side').length, 1);           // filter sidebar (PC)
  assert.equal(has(shop, 'olx-ads').length, 1);
  assert.equal(has(shop, 'olx-ad').length, S.ITEMS.length + S.MODS.length + S.TUNES.length);
  const labels = () => has(shop, 'olx-btn').map((b) => b.textContent);
  assert.ok(labels().includes('Обрано'));
  assert.ok(labels().includes('Купити'));
  assert.ok(labels().some((t) => t.startsWith('Не вистачає')));
  const card = (id) => has(shop, 'olx-ad').find((a) => a.attrs['data-skin'] === id);
  const btn = (a) => has(a, 'olx-btn')[0];
  btn(card('matiz')).listeners.click[0]();                 // press «Купити» on the Matiz
  assert.ok(S.owned('matiz') && S.skin() === 'matiz');
  assert.equal(btn(card('matiz')).textContent, 'Обрано');
  S.filter.cat = 'look';                                   // the phone and the PC filters write the same state
  S.close();
  S.open();
  assert.equal(has(shop, 'olx-ad').length, S.MODS.length);
  // sections: the cars, then one heading per mod category
  S.filter.cat = 'all'; S.close(); S.open();
  const secs = has(shop, 'olx-sec').map((h) => h.attrs['data-sec']);
  assert.deepEqual(secs, ['car', 'paint', 'decal', 'spoiler', 'rims', 'glow', 'roof', 'exhaust', 'lights', 'tune']);
  assert.equal(has(shop, 'olx-sheet').length, 1);
  assert.equal(has(shop, 'olx-sheet')[0].hidden, true);
  // phone gallery: tiles in the grid, a tap opens the full listing in the sheet, the buy button lives there
  globalThis.matchMedia = (q) => ({ matches: /600px/.test(q) });
  S.close(); S.open();
  const tile = (id) => has(shop, 'olx-ad').find((a) => a.attrs['data-mod'] === id);
  assert.equal(tile('glow_cyan').attrs.tabindex, '0');
  assert.equal(has(shop, 'olx-sheet')[0].hidden, true);
  tile('glow_cyan').listeners.click[0]();
  const sheet = has(shop, 'olx-sheet')[0];
  assert.equal(sheet.hidden, false);
  assert.equal(shop.className, 'sheet-open');
  assert.equal(has(sheet, 'olx-ad').length, 1);
  assert.ok(has(sheet, 'olx-ad')[0].className.includes('full'));
  assert.ok(has(sheet, 'olx-sheet-x').length === 1 && has(sheet, 'olx-desc').length === 1);
  assert.equal(has(sheet, 'olx-btn')[0].textContent, 'Купити');
  has(sheet, 'olx-btn')[0].listeners.click[0]();           // 100 € earned, neon costs 30
  assert.ok(S.ownedMod('glow_cyan') && S.fitted('glow_cyan'));
  assert.equal(has(sheet, 'olx-btn')[0].textContent, 'Зняти');
  has(sheet, 'olx-btn')[0].listeners.click[0]();
  assert.equal(S.fitted('glow_cyan'), false);
  assert.equal(has(sheet, 'olx-btn')[0].textContent, 'Встановити');
  has(sheet, 'olx-sheet-x')[0].listeners.click[0]();
  assert.equal(sheet.hidden, true);
  assert.equal(shop.className, '');
  tile('glow_cyan').listeners.click[0]();
  S.close();                                               // closing the shop closes the sheet too
  assert.equal(sheet.hidden, true);
  globalThis.matchMedia = () => ({ matches: false });      // PC: a tap on a card does not open the sheet
  S.open();
  tile('glow_pink').listeners.click[0]();
  assert.equal(sheet.hidden, true);
  delete globalThis.matchMedia;
  delete globalThis.document;
}

console.log('shop_test: ok');
