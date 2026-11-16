// Node test of 62_missions.js: progress from bus events, stars storage, no missions without data.
import vm from 'node:vm'; import fs from 'node:fs'; import assert from 'node:assert';

const M = {
  version: 1,
  shifts: {
    a: [
      { id: 'm1', kind: 'airport', n: 1, x: 1000, y: 1000, r: 500, title: 'A', short: 'Аеропорт' },
      { id: 'm2', kind: 'district', n: 2, x: 5000, y: 5000, r: 600, title: 'D', short: 'З X' },
      { id: 'm3', kind: 'long', n: 1, km: 8, title: 'L', short: 'Від 8 км' },
    ],
    b: [
      { id: 'm1', kind: 'combo', n: 3, title: 'C', short: 'Комбо' },
      { id: 'm2', kind: 'rival', n: 1, rival: 'ze', title: 'R', short: 'Обжени Зé' },
      { id: 'm3', kind: 'median', n: 1, eur: 10, by: 3600, title: 'M', short: '€10' },
    ],
  },
};

function fresh() {
  const handlers = {};
  const bus = {
    on: (ev, fn) => { (handlers[ev] = handlers[ev] || []).push(fn); },
    emit: (ev, p) => { (handlers[ev] || []).forEach((fn) => fn(p)); notes.push([ev, p]); },
  };
  const notes = [];
  const G = { t: 0, tot: 0, leg: { t0: 0 }, rivals: [{ id: 'ze', total: 20 }] };
  globalThis.PG = { bus, MISSIONS: M, engine: { G, party: null }, util: { eur: (x) => '€' + x.toFixed(2) } };
  vm.runInThisContext(fs.readFileSync(new URL('../game/src/js/62_missions.js', import.meta.url), 'utf8'));
  return { bus, G, notes, P: PG.missions };
}
const order = (x0, y0, x1, y1, km) => ({ x0, y0, x1, y1, km });
const done = (P) => P.items().map((it) => it.done);

{ // shift a: airport, district (2 pickups), long trip
  const { bus, P, notes } = fresh();
  bus.emit('shift:start', { idx: 0, sh: { id: 'a' } });
  assert.equal(P.items().length, 3);
  bus.emit('dropoff', { o: order(9000, 9000, 1100, 1100, 3) });           // ends at the airport
  assert.deepEqual(done(P), [true, false, false]);
  bus.emit('dropoff', { o: order(5100, 5100, 9000, 9000, 3) });
  assert.deepEqual(done(P), [true, false, false]);
  assert.equal(P.items()[1].got, 1);
  bus.emit('dropoff', { o: order(5200, 4900, 9000, 9000, 9) });           // second district pickup, long trip
  assert.deepEqual(done(P), [true, true, true]);
  assert.equal(notes.filter((n) => n[0] === 'note' && n[1].text === '★ Завдання виконано').length, 3);
  bus.emit('shift:end', { result: { earned: 5 } });
  assert.equal(P.best('a'), 3);
}

{ // shift b: combo, rival at the end, money before half-time
  const { bus, P, G } = fresh();
  bus.emit('shift:start', { idx: 1, sh: { id: 'b' } });
  bus.emit('combo', { n: 2, k: 1.1 });
  assert.deepEqual(done(P), [false, false, false]);
  bus.emit('combo', { n: 3, k: 1.2 });
  assert.equal(P.items()[0].done, true);
  G.tot = 11; G.t = 3000; G.leg.t0 = 3000;
  bus.emit('pickup', { o: {}, fare: 5 });
  assert.equal(P.items()[2].done, true, 'median reached before half-time');
  G.tot = 15; G.t = 7200;
  bus.emit('shift:end', { result: { earned: 15 } });                      // rival has 20: not beaten
  assert.equal(P.items()[1].fail, true);
  assert.equal(P.stars(), 2);
  assert.equal(P.best('b'), 2);
}

{ // money too late, rival beaten; the best stars are kept, never lowered
  const { bus, P, G } = fresh();
  bus.emit('shift:start', { idx: 1, sh: { id: 'b' } });
  G.tot = 0; G.t = 3700;
  bus.emit('frame', { now: 0, dt: 1 });
  assert.equal(P.items()[2].fail, true, 'deadline passed');
  G.tot = 30; G.t = 7200;
  bus.emit('shift:end', { result: { earned: 30 } });
  assert.equal(P.items()[1].done, true);
  assert.equal(P.items()[2].done, false);
  const first = P.best('b');
  bus.emit('shift:start', { idx: 1, sh: { id: 'b' } });
  bus.emit('shift:end', { result: { earned: 0 } });
  assert.equal(P.best('b'), first);
}

{ // no entry for the shift, or party mode: nothing is tracked
  const { bus, P } = fresh();
  bus.emit('shift:start', { idx: 5, sh: { id: 'zzz' } });
  assert.equal(P.items().length, 0);
  PG.engine.party = { clock() {} };
  bus.emit('shift:start', { idx: 0, sh: { id: 'a' } });
  assert.equal(P.items().length, 0);
}

{ // no missions.json in the build: inert
  const { bus, P } = fresh();
  delete PG.MISSIONS; P._reset();
  bus.emit('shift:start', { idx: 0, sh: { id: 'a' } });
  bus.emit('dropoff', { o: order(1000, 1000, 1000, 1000, 20) });
  assert.equal(P.items().length, 0);
}
console.log('missions ok');
