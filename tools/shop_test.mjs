// Node test of 68_shop.js: wallet from shift results, buying, choosing, demo unlock, storage.
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
console.log('shop_test: ok');
