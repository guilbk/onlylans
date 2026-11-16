// Node test of 63_achievements.js: progress from bus events, unlock toasts, storage, no badges without data.
import vm from 'node:vm'; import fs from 'node:fs'; import assert from 'node:assert';

const DOC = {
  version: 1, weekend: ['sat', 'sun'],
  badges: [
    { id: 'night', title: 'Нічна', n: 2 }, { id: 'airport', title: 'Аеро', n: 2, x: 1000, y: 1000, r: 500 },
    { id: 'long', title: 'Далека', n: 1, km: 8 }, { id: 'ghost', title: 'Привид', n: 2 },
    { id: 'rivals', title: 'Усі сім', n: 1 }, { id: 'pax', title: 'Сотня', n: 3 },
    { id: 'districts', title: 'Порту', n: 2, r: 600, spots: [{ name: 'A', x: 5000, y: 5000 }, { name: 'B', x: 9000, y: 9000 }] },
    { id: 'legend', title: 'Легенда', n: 1 }, { id: 'top10', title: 'Десятка', n: 1 },
    { id: 'week', title: 'Тиждень', n: 2 }, { id: 'money', title: 'Гроші', n: 20 }, { id: 'combo', title: 'Серія', n: 5 },
  ],
};
const order = (x0, y0, x1, y1, km) => ({ x0, y0, x1, y1, km });
const res = (o) => Object.assign({ earned: 5, medal: 0, racePlace: 5, raceSize: 8, shiftId: 'mon-am' }, o);

function fresh(doc = DOC) {
  const handlers = {}, notes = [], mem = {};
  const bus = {
    on: (ev, fn) => { (handlers[ev] = handlers[ev] || []).push(fn); },
    emit: (ev, p) => { (handlers[ev] || []).forEach((fn) => fn(p)); if (ev === 'note') notes.push(p.text); },
  };
  globalThis.PG = { bus, ACHIEVEMENTS: doc, engine: { party: null } };
  globalThis.window = globalThis; globalThis.localStorage = { getItem: (k) => mem[k] || null, setItem: (k, v) => { mem[k] = v; } };
  vm.runInThisContext(fs.readFileSync(new URL('../game/src/js/63_achievements.js', import.meta.url), 'utf8'));
  return { bus, notes, mem, A: PG.achievements };
}

{ // trips: passengers, airport, long, districts
  const { bus, A, notes } = fresh();
  bus.emit('dropoff', { o: order(9000, 9000, 1100, 1100, 3) });     // district B, airport
  assert.equal(A.progress('pax'), 1); assert.equal(A.progress('airport'), 1); assert.equal(A.progress('districts'), 1);
  bus.emit('dropoff', { o: order(5100, 5100, 1000, 900, 9) });      // district A, airport, long
  assert.ok(A.done('airport') && A.done('long') && A.done('districts'));
  assert.equal(A.progress('pax'), 2);
  assert.ok(notes[0].startsWith('🏅 Досягнення: '));                // first toast at once, the rest queued
  assert.equal(notes.length, 1);
  bus.emit('dropoff', { o: order(9000, 9000, 9000, 9000, 1) });     // the same district again: no double count
  assert.equal(A.progress('districts'), 2); assert.ok(A.done('pax'));
}
{ // combo keeps the best run; shift end badges
  const { bus, A } = fresh();
  bus.emit('combo', { n: 3 }); bus.emit('combo', { n: 2 });
  assert.equal(A.progress('combo'), 3);
  bus.emit('combo', { n: 5 }); assert.ok(A.done('combo'));
  bus.emit('shift:end', { result: res({ shiftId: 'mon-night', medal: 3, racePlace: 1 }) });
  assert.equal(A.progress('night'), 1); assert.equal(A.progress('ghost'), 1); assert.ok(A.done('rivals')); assert.ok(A.done('top10'));
  assert.ok(!A.done('legend'));
  bus.emit('shift:end', { result: res({ shiftId: 'sat-night', medal: 4 }) });
  assert.ok(A.done('legend') && A.done('night') && A.done('ghost') && A.done('week'));
  assert.equal(A.progress('money'), 10);
  bus.emit('shift:end', { result: res({ shiftId: 'tue-am', earned: 12 }) });
  assert.ok(A.done('money'));
}
{ // saved progress survives a reload; party mode and a missing file count nothing
  const a = fresh();
  a.bus.emit('dropoff', { o: order(0, 0, 0, 0, 1) });
  const b = (() => { const mem = a.mem; const f = fresh(); return { f, mem }; })();
  assert.equal(b.f.A.progress('pax'), 0);                           // a new empty storage
  const p = fresh(); PG.engine.party = {};
  p.bus.emit('dropoff', { o: order(0, 0, 0, 0, 1) }); p.bus.emit('shift:end', { result: res({ medal: 4 }) });
  assert.equal(p.A.progress('pax'), 0); assert.equal(p.A.progress('ghost'), 0);
  const n = fresh(null); n.bus.emit('dropoff', { o: order(0, 0, 0, 0, 1) });
  assert.equal(n.A.progress('pax'), 0);
}
{ // reload from localStorage
  const { bus, mem } = fresh();
  bus.emit('dropoff', { o: order(0, 0, 0, 0, 1) });
  const key = Object.keys(mem)[0];
  assert.equal(JSON.parse(mem[key]).p.pax, 1);
  const again = fresh(); globalThis.localStorage.setItem(key, mem[key]);
  again.A._reset(); again.bus.emit('dropoff', { o: order(0, 0, 0, 0, 1) });
  assert.equal(again.A.progress('pax'), 2);
}
console.log('achievements_test: ok');
