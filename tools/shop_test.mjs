// Node test of 68_shop.js: wallet from shift results, buying, choosing, tuning, listings and filters,
// demo unlock, storage, and the DOM containers of both layouts (phone chips, PC sidebar) on a small fake DOM.
import vm from 'node:vm'; import fs from 'node:fs'; import assert from 'node:assert';

function fresh(saved) {
  const mem = new Map(saved ? [['porto-lanosiv-shop-v1', JSON.stringify(saved)]] : []);
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
  assert.equal(S.listings({ cat: 'all', max: 500, can: false, q: '' }).length, S.ITEMS.length + S.TUNING.length);
}

{ // tuning items: present, priced, dated, cosmetic only
  const { S } = fresh();
  assert.ok(S.TUNING.length >= 5);
  const ids = S.TUNING.map((t) => t.id);
  for (const id of ['taxi', 'stickers', 'rims', 'tree', 'garland']) assert.ok(ids.includes(id), id);
  for (const t of S.TUNING) {
    assert.ok(t.price > 0 && t.title && t.who && t.desc, t.id);
    assert.match(t.date, /травня 2014$/);
    assert.ok(!('speed' in t) && !('fare' in t) && !('boost' in t), `${t.id} has no gameplay field`);
  }
  assert.ok(!ids.some((id) => S.ITEMS.some((i) => i.id === id)));
}

{ // tuning: refused without money, bought with enough, fitted and taken off, saved, wallet reduced
  const { S, end, mem } = fresh();
  assert.equal(S.needTune('taxi'), 14);
  assert.equal(S.buyTune('taxi'), false);
  assert.equal(S.fitted('taxi'), false);
  assert.equal(S.buyTune('nope'), false);
  end(20);
  assert.equal(S.buyTune('taxi'), true);
  assert.equal(S.wallet(), 6);
  assert.ok(S.ownedTune('taxi') && S.fitted('taxi'));
  assert.equal(S.buyTune('taxi'), false);                  // already owned
  assert.equal(S.fitTune('taxi'), true);                   // flips to off
  assert.equal(S.fitted('taxi'), false);
  assert.equal(S.fitTune('rims'), false);                  // not owned
  assert.equal(S.fitTune('taxi', true), true);
  assert.deepEqual(S.fittedList(), ['taxi']);
  assert.equal(S.skin(), 'lanos');                         // cosmetic: the skin and the wallet rules are untouched
  const again = fresh(JSON.parse(mem.get('porto-lanosiv-shop-v1')));
  assert.equal(again.S.wallet(), 6);
  assert.ok(again.S.ownedTune('taxi') && again.S.fitted('taxi'));
  assert.equal(fresh({ earned: 0, spent: 0, owned: { lanos: 1 }, tune: { taxi: 1 }, fit: { taxi: 1, rims: 1 } }).S.fitted('taxi'), true);
  assert.equal(fresh({ earned: 0, spent: 0, owned: { lanos: 1 }, tune: { nope: 1 }, fit: { rims: 1 } }).S.fitted('rims'), false);
}

{ // the demo unlock opens the tuning too
  const { S } = fresh();
  S.unlockAll();
  assert.ok(S.TUNING.every((t) => S.ownedTune(t.id)));
  assert.equal(S.wallet(), 0);
}

{ // filters: category, price, can-buy, search
  const { S, end } = fresh();
  const F = (o) => S.listings(Object.assign({ cat: 'all', max: 500, can: false, q: '' }, o));
  assert.equal(F({ cat: 'car' }).length, 9);
  assert.equal(F({ cat: 'tune' }).length, S.TUNING.length);
  assert.ok(F({ cat: 'car' }).every((r) => r.kind === 'car'));
  assert.ok(F({ max: 100 }).every((r) => r.it.price <= 100));
  assert.ok(F({ max: 100 }).some((r) => r.it.id === 'lanos'));
  assert.equal(F({ can: true }).length, 0);                // empty wallet, the Lanos is owned
  end(40);
  assert.deepEqual(F({ can: true }).map((r) => r.it.id).sort(), ['garland', 'matiz', 'rims', 'stickers', 'taxi', 'tree'].sort());
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
  assert.equal(has(shop, 'olx-chip').length, 5);
  assert.equal(has(shop, 'olx-side').length, 1);           // filter sidebar (PC)
  assert.equal(has(shop, 'olx-ads').length, 1);
  assert.equal(has(shop, 'olx-ad').length, S.ITEMS.length + S.TUNING.length);
  const labels = () => has(shop, 'olx-btn').map((b) => b.textContent);
  assert.ok(labels().includes('Обрано'));
  assert.ok(labels().includes('Купити'));
  assert.ok(labels().some((t) => t.startsWith('Не вистачає')));
  const card = (id) => has(shop, 'olx-ad').find((a) => a.attrs['data-skin'] === id);
  const btn = (a) => has(a, 'olx-btn')[0];
  btn(card('matiz')).listeners.click[0]();                 // press «Купити» on the Matiz
  assert.ok(S.owned('matiz') && S.skin() === 'matiz');
  assert.equal(btn(card('matiz')).textContent, 'Обрано');
  S.filter.cat = 'tune';                                   // the phone and the PC filters write the same state
  S.close();
  S.open();
  assert.equal(has(shop, 'olx-ad').length, S.TUNING.length);
  delete globalThis.document;
}

console.log('shop_test: ok');
