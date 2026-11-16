(function (root) {
  const PG = root.PG = root.PG || {};

  // Heat map «Де заробляли» (CONTRACT §21): a soft layer of where real drivers earned in this hour of the shift.
  // The cells come from Python (heat.json); this file only paints them under the pins and the cars.
  const SIDE_M = 400;       // fallback cell side, metres (the file says its own)
  const HOUR_S = 3600;
  const RAMP = {
    day: { a: [255, 170, 20], b: [214, 30, 50], max: 0.8, op: 'source-over' },
    night: { a: [255, 170, 40], b: [255, 60, 120], max: 0.75, op: 'source-over' },
  };

  let doc = null;
  let on = false;
  let btn = null;
  let legend = null;
  let cache = null;          // {key, cv}
  let shown = '';

  function load() {
    try {
      const e = document.getElementById('heat-data');
      if (e) doc = JSON.parse(e.textContent);
    } catch (err) { doc = null; }
  }
  function game() { return PG.engine && PG.engine.G; }
  function hourIdx(G) { return G.t >= HOUR_S ? 1 : 0; }
  function themeName() { return PG.theme && PG.theme.name === 'day' ? 'day' : 'night'; }

  // one pixel per grid cell; the browser smooths it when it is stretched over the map
  function paint(cells, theme) {
    const cv = document.createElement('canvas');
    cv.width = doc.cols;
    cv.height = doc.rows;
    const c = cv.getContext('2d');
    const img = c.createImageData(doc.cols, doc.rows);
    const k = RAMP[theme];
    let at = 0;
    for (let i = 0; i + 1 < cells.length; i += 2) {
      at += cells[i];
      const v = cells[i + 1] / 99;
      const o = at * 4;
      for (let j = 0; j < 3; j++) img.data[o + j] = Math.round(k.a[j] + (k.b[j] - k.a[j]) * v);
      img.data[o + 3] = Math.round(255 * k.max * Math.min(1, v * 2));
    }
    c.putImageData(img, 0, 0);
    return cv;
  }

  function draw(ctx) {
    const G = game();
    if (!on || !doc || !G || !G.sh || !PG.render) return;
    const hours = doc.shifts[G.sh.id];
    if (!hours) return;
    const h = hourIdx(G), theme = themeName();
    const key = G.sh.id + h + theme;
    if (!cache || cache.key !== key) cache = { key: key, cv: paint(hours[h] || [], theme) };
    const side = doc.cell_m || SIDE_M;
    const R = PG.render, p0 = R.P(0, 0), ax = p0.x, ay = p0.y;   // P() returns one shared object
    const p1 = R.P(doc.cols * side, doc.rows * side);
    ctx.save();
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.globalCompositeOperation = RAMP[theme].op;
    ctx.drawImage(cache.cv, ax, ay, p1.x - ax, p1.y - ay);
    ctx.restore();
  }

  function hh(G) {
    const n = (G.sh.startHour + hourIdx(G)) % 24;
    return (n < 10 ? '0' : '') + n + ':00';
  }

  function sync() {
    const z = document.getElementById('map-zoom');
    const vis = !!z && !z.hidden && !!doc;
    btn.hidden = !vis;
    const G = game();
    const text = on && vis && G && G.sh ? 'Де заробляли справжні таксисти о ' + hh(G) : '';
    legend.hidden = !text;
    if (text !== shown) { legend.textContent = text; shown = text; }
  }

  function toggle() {
    on = !on;
    btn.classList.toggle('on', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    sync();
  }

  function init() {
    const stage = document.getElementById('stage');
    if (!stage) return;
    load();
    if (!doc) return;
    btn = document.createElement('button');
    btn.id = 'map-heat';
    btn.type = 'button';
    btn.textContent = '🔥';
    btn.hidden = true;
    btn.setAttribute('aria-label', 'Де заробляли справжні таксисти');
    btn.setAttribute('aria-pressed', 'false');
    btn.setAttribute('data-no-map', '');
    btn.addEventListener('click', toggle);
    stage.appendChild(btn);
    legend = document.createElement('div');
    legend.id = 'heat-legend';
    legend.hidden = true;
    stage.appendChild(legend);
    PG.render.onDraw(draw, -3);   // above the ground and the basemap (z -4), under the landmarks, pins and cars
    PG.bus.on('frame', sync);
    PG.bus.on('shift:start', function () { on = false; btn.classList.remove('on'); btn.setAttribute('aria-pressed', 'false'); });
  }

  PG.heat = { init: init, toggle: toggle };
  if (typeof document !== 'undefined' && PG.render && PG.render.onDraw && document.getElementById('stage')) init();
})(typeof window !== 'undefined' ? window : globalThis);
