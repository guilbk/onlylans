// node tools/radio_test.mjs : timing of PG.radio.update (DOM-free)
import vm from 'node:vm';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const root = new URL('../game/src/js/', import.meta.url).pathname;
const ev = [], says = [];
globalThis.PG = {
  bus: { emit: (e, p) => ev.push([e, p]), on() {} },
  engine: { say: (t, ms) => says.push([t, ms]) },
};
vm.runInThisContext(fs.readFileSync(root + '28_radio.js', 'utf8'));
const s = { x: 1, y: 1, r: 200, t0: 1000, t1: 1300, n: 12, name: 'Campanhã' };
const sh = { surgesM: [s], hotM: [] };
const G = { sh, t: 0 };
const names = () => ev.map(e => e[0]).join(',');
PG.radio.update(G); assert.equal(names(), ''); assert.equal(PG.radio.phase, 'none');
G.t = 759; PG.radio.update(G); assert.equal(names(), '');
G.t = 760; PG.radio.update(G);
assert.equal(names(), 'radio:surge'); assert.equal(ev[0][1].inSec, 240);
assert.match(says[0][0], /за 4 хв хвиля замовлень біля Campanhã \(≈12\)/); assert.equal(says[0][1], 4200);
assert.equal(PG.radio.phase, 'upcoming');
G.t = 800; PG.radio.update(G); assert.equal(ev.length, 1, 'announced once');
G.t = 1000; PG.radio.update(G); assert.equal(PG.radio.phase, 'active');
G.t = 1300; PG.radio.update(G); assert.equal(names(), 'radio:surge,radio:surge:end'); assert.equal(PG.radio.phase, 'none');
G.t = 1400; PG.radio.update(G); assert.equal(ev.length, 2, 'end once');
// big jump into the middle of the surge: announced as "зараз"
ev.length = 0; says.length = 0;
const G2 = { sh: { surgesM: [s] }, t: 1100 }; PG.radio.update(G2);
assert.match(says[0][0], /зараз хвиля/); assert.equal(PG.radio.phase, 'active');
// surge near the start: announce at max(0, t0-240)
ev.length = 0; says.length = 0;
const s2 = Object.assign({}, s, { t0: 150, t1: 400 });
const G3 = { sh: { surgesM: [s2] }, t: 0 }; PG.radio.update(G3);
assert.equal(ev[0][1].inSec, 150); assert.match(says[0][0], /за 3 хв/);
// jump past the end: nothing announced
ev.length = 0;
const G4 = { sh: { surgesM: [s] }, t: 5000 }; PG.radio.update(G4); assert.equal(ev.length, 0);
console.log('radio_test ok');
