// Node test of 47_gold.js: deterministic pick, ×2 bonus once, none for rivals / non-gold orders.
import vm from 'node:vm'; import fs from 'node:fs'; import assert from 'node:assert';

function fresh(sid) {
  globalThis.PG = {};
  for (const f of ['00_core', '22_rules', '47_gold']) {
    vm.runInThisContext(fs.readFileSync(new URL(`../game/src/js/${f}.js`, import.meta.url), 'utf8'));
  }
  PG.C = { LEAD: [600, 600, 600] };
  const orders = [];
  for (let i = 0; i < 400; i++) orders.push({ i, t: 100 + i * 20, c: i % 3, fare: 10 + (i % 7), x0: 0, y0: 0, x1: 5, y1: 5 });
  const G = { sh: { id: sid, orders }, t: 0, taken: new Set(), tips: 0, floats: [], leg: { t1: 0 } };
  PG.engine = { G };
  return { G, orders };
}
const names = [];

{ // deterministic: the same shift and window give the same order; another window or shift may differ
  const a = fresh('s1'), b = fresh('s1');
  for (const w of [1, 2, 3]) {
    const pa = PG.gold.pick(a.G.sh, w);
    assert.ok(pa && pa.t > w * 1800 && pa.t - 600 <= w * 1800);
    assert.equal(pa.i, PG.gold.pick(b.G.sh, w).i);
  }
  const ids = [1, 2, 3, 4].map((w) => PG.gold.pick(a.G.sh, w).i);
  assert.ok(new Set(ids).size > 1);
  const c = fresh('s2');
  assert.ok([1, 2, 3, 4].some((w) => PG.gold.pick(c.G.sh, w).i !== ids[w - 1]));
}

{ // golds appear with the window, announce once, late joiner sees the same list
  const { G } = fresh('s1');
  const notes = []; PG.bus.on('note', (e) => notes.push(e.text));
  G.t = 1000; assert.deepEqual(PG.gold.golds(G.sh, G.t), []);
  G.t = 1800; assert.equal(PG.gold.golds(G.sh, G.t).length, 1);
  G.t = 1900; assert.equal(PG.gold.golds(G.sh, G.t).length, 1);
  assert.deepEqual(notes, ['Золоте замовлення: ×2 до плати']);
  G.t = 5500; assert.equal(PG.gold.golds(G.sh, G.t).length, 3);
  const first = PG.gold.golds(G.sh, G.t)[0].i;
  const late = fresh('s1'); late.G.t = 5500;
  assert.equal(PG.gold.golds(late.G.sh, 5500)[0].i, first);
}

{ // the bonus equals the fare, paid once; a normal order and a rival's loss pay nothing extra
  const { G, orders } = fresh('s1');
  G.t = 1800;
  const g = PG.gold.golds(G.sh, G.t)[0];
  const plain = orders.find((o) => o !== g && o.fare === g.fare);
  let p = { o: plain, fare: plain.fare, tip: 0 };
  PG.bus.emit('dropoff', p);
  const base = p.tip;                       // the rules tip of an order with this fare
  assert.equal(G.tips, base);
  assert.equal(G.floats.length, 0);
  p = { o: g, fare: g.fare, tip: 0 };
  PG.bus.emit('dropoff', p);
  assert.equal(p.tip, Math.round((base + g.fare) * 100) / 100);
  assert.equal(G.floats.length, 1);
  assert.ok(G.floats[0].text.endsWith('×2'));
  const after = G.tips;
  assert.ok(after > 2 * base);
  p = { o: g, fare: g.fare, tip: 0 };
  PG.bus.emit('dropoff', p);                // paid once: the second drop-off has no bonus
  assert.equal(p.tip, base);
  assert.equal(G.floats.length, 1);
  // rivals: they take orders through order:lost, never through dropoff
  PG.bus.emit('order:lost', { o: g, by: 'r1' });
  assert.equal(G.floats.length, 1);
}
console.log('gold_test: ok');
