// Node test of the car mods in 41_cars.js: catalog shape, setMods round-trip, draw/preview never throw.
import vm from 'node:vm'; import fs from 'node:fs'; import assert from 'node:assert';

const mem = new Map();
globalThis.localStorage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
const ctx = new Proxy({}, { get: (t, k) => (k in t ? t[k] : (k === 'createLinearGradient' || k === 'createRadialGradient' ? () => ({ addColorStop() {} }) : () => {})), set: (t, k, v) => { t[k] = v; return true; } });
globalThis.document = { createElement: () => ({ width: 0, height: 0, getContext: () => ctx }) };
globalThis.PG = {};
vm.runInThisContext(fs.readFileSync(new URL('../game/src/js/41_cars.js', import.meta.url), 'utf8'));
const C = PG.cars;

{ // catalog: ids unique, Ukrainian names, positive prices, the brief's counts per category
  const ids = C.MODS.map((m) => m.id);
  assert.equal(new Set(ids).size, ids.length);
  const n = (cat) => C.MODS.filter((m) => m.cat === cat).length;
  assert.deepEqual(['paint', 'decal', 'spoiler', 'rims', 'glow', 'roof', 'exhaust', 'lights'].map(n), [6, 3, 2, 3, 4, 3, 3, 2]);
  for (const m of C.MODS) {
    assert.ok(m.id.startsWith(m.cat + '_'), m.id);
    assert.ok(/[А-Яа-яІіЇїЄє]/.test(m.name), m.name);
    assert.ok(Number.isFinite(m.price) && m.price > 0, m.id);
  }
  assert.ok(ids.includes('paint_matte') && ids.includes('paint_pearl'));
}

{ // setMods round-trip, junk dropped, one choice per category, storage key
  assert.deepEqual(C.mods(), {});
  C.setMods({ paint: 'paint_red', glow: 'glow_pink', rims: 'paint_red', bogus: 'x', roof: 'nope' });
  assert.deepEqual(C.mods(), { paint: 'paint_red', glow: 'glow_pink' });
  assert.deepEqual(JSON.parse(mem.get('lanos.mods')), { paint: 'paint_red', glow: 'glow_pink' });
  C.mods().paint = 'x';                                   // the copy does not write through
  assert.equal(C.mods().paint, 'paint_red');
  C.setMods(null);
  assert.deepEqual(C.mods(), {});
}

{ // draw and preview do not throw for every skin x every mod, also with everything on, fast on and off
  const all = {};
  for (const m of C.MODS) all[m.cat] = m.id;
  const cv = { width: 240, height: 120, getContext: () => ctx };
  for (const fast of [false, true]) {
    PG.engine = { G: { fast } };
    for (const s of C.SKINS) {
      for (const m of [null, {}, all, ...C.MODS.map((x) => ({ [x.cat]: x.id }))]) {
        C.draw(ctx, 50, 50, 0.7, 36, '#3df5b0', 1, 'hero', s.id, m);
        C.preview(cv, s.id, m);
      }
    }
  }
  C.setMods({ glow: 'glow_cyan' });
  C.draw(ctx, 0, 0, 0, 30, '#3df5b0', 1, 'hero');         // hero without args uses the saved mods
  C.draw(ctx, 0, 0, 0, 30, '#ffffff', 1, 'rival');
}
console.log('cars_test ok');
