(function (root) {
  'use strict';
  const PG = root.PG = root.PG || {};

  const INIT_ORDER = ['progress', 'render', 'hud', 'audio', 'radio', 'orders', 'fx', 'screens', 'input'];
  const DT_CAP = 0.1;

  let last = 0;

  function runInits() {
    for (let i = 0; i < INIT_ORDER.length; i++) {
      const m = PG[INIT_ORDER[i]];
      if (m && m.init) m.init();
    }
  }

  function frame(nowMs) {
    root.requestAnimationFrame(frame);
    const now = nowMs / 1000;
    let dt = last ? now - last : 0;
    last = now;
    if (dt > DT_CAP) dt = DT_CAP;
    if (dt < 0) dt = 0;
    if (root.document && root.document.hidden) return;

    const C = PG.C;
    const eng = PG.engine;
    const G = eng && eng.G;
    if (PG.screen === 'play' && G && !G.over && !G.paused) {
      eng.step(dt * C.BASE_SCALE * (G.fast ? C.FAST : 1));
    }
    PG.bus.emit('frame', { now: now, dt: dt });
    if (PG.render && PG.render.draw) PG.render.draw(now);
    if (PG.hud && PG.hud.update) PG.hud.update(now);
  }

  function boot() {
    runInits();
    root.__porto = { PG: PG };
    root.requestAnimationFrame(frame);
    // after a hidden tab comes back, do not count the gap as game time
    root.document.addEventListener('visibilitychange', function () { last = 0; });
  }

  boot();
})(typeof window !== 'undefined' ? window : globalThis);
