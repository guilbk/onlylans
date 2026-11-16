(function (root) {
  const PG = root.PG = root.PG || {};

  // Dispatcher radio: announces demand surges ahead of time and draws them,
  // plus faint glows at the hotspots. The core (update) is DOM-free.
  const LEAD_S = 240;          // announce this many game s before t0
  const CLOSE_PX = 0.1;        // hotspot names show when 1 m >= this many px
  const MAX = 16;

  let sh = null;               // shift the state belongs to
  let lastT = 0;
  const ann = new Uint8Array(MAX);   // 1 = announced
  const fin = new Uint8Array(MAX);   // 1 = ended (or skipped)
  const EMPTY = [];

  const radio = {
    surges: EMPTY,
    phase: 'none',             // none | upcoming | active
    init: init,
    update: update,
  };
  PG.radio = radio;

  function reset(newSh) {
    sh = newSh;
    ann.fill(0); fin.fill(0);
    radio.surges = (sh && sh.surgesM) || EMPTY;
    radio.phase = 'none';
    lastT = 0;
  }

  function minutesText(inSec) {
    if (inSec <= 0) return 'зараз';
    return 'за ' + Math.max(1, Math.ceil(inSec / 60)) + ' хв';
  }

  function place(s) {            // «район Boavista» -> «Boavista» (reads right after «біля»)
    return String(s.name).replace(/^район\s+/, '');
  }

  function announce(G, s, inSec) {
    PG.bus.emit('radio:surge', { s: s, inSec: inSec });
    if (PG.engine && PG.engine.say) {
      PG.engine.say('📻 Диспетчер: ' + minutesText(inSec) + ' хвиля замовлень біля ' +
        place(s) + ' (≈' + s.n + ')', 4200);
    }
  }

  function update(G) {
    if (!G || !G.sh) return;
    if (G.sh !== sh || G.t < lastT) reset(G.sh);
    lastT = G.t;
    const list = radio.surges, t = G.t;
    let phase = 'none';
    for (let i = 0; i < list.length && i < MAX; i++) {
      const s = list[i];
      if (fin[i]) continue;
      if (t >= s.t1) {                       // over; never announced late stuff that is already gone
        if (ann[i]) PG.bus.emit('radio:surge:end', { s: s });
        ann[i] = 1; fin[i] = 1;
        continue;
      }
      if (!ann[i] && t >= Math.max(0, s.t0 - LEAD_S)) {
        ann[i] = 1;
        announce(G, s, Math.max(0, s.t0 - t));
      }
      if (ann[i]) {
        if (t >= s.t0) phase = 'active';
        else if (phase !== 'active') phase = 'upcoming';
      }
    }
    radio.phase = phase;
  }

  // ---- drawing (browser only) ----
  let glow = null;             // pre-rendered radial sprite
  const DASH = [10, 8], SOLID = [];
  const pa = { x: 0, y: 0 };

  const pal = function () { return (PG.theme && PG.theme.pal) || PG.C.THEMES.night; };
  let glowName = '';
  function rgbOf(hex) { const n = parseInt(hex.slice(1), 16); return (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255); }

  function makeGlow() {
    if (typeof document === 'undefined') return null;
    const rgb = rgbOf(pal().pins[0]);
    glowName = pal().name;
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const g = c.getContext('2d');
    const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    gr.addColorStop(0, 'rgba(' + rgb + ',0.55)');
    gr.addColorStop(0.5, 'rgba(' + rgb + ',0.18)');
    gr.addColorStop(1, 'rgba(' + rgb + ',0)');
    g.fillStyle = gr;
    g.fillRect(0, 0, 128, 128);
    return c;
  }

  function pxPerM(x, y) {
    const R = PG.render, a = R.P(x, y);
    pa.x = a.x; pa.y = a.y;
    const b = R.P(x + 100, y);
    return Math.abs(b.x - pa.x) / 100;
  }

  function drawHot(ctx, now) {
    const G = PG.engine && PG.engine.G;
    if (!G || !G.sh || !G.sh.hotM || !PG.render) return;
    const hot = G.sh.hotM;
    if (glowName !== pal().name) glow = makeGlow();
    for (let i = 0; i < hot.length; i++) {
      const h = hot[i];
      const k = pxPerM(h.x, h.y);
      const rad = Math.max(24, 220 * k);
      const x = pa.x, y = pa.y;
      ctx.globalAlpha = 0.35 + 0.65 * Math.min(1, h.w * 4);
      if (glow) ctx.drawImage(glow, x - rad, y - rad, rad * 2, rad * 2);
      ctx.globalAlpha = 1;
      if (k >= CLOSE_PX && h.name) {
        ctx.font = '11px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillStyle = pal().muted;
        ctx.fillText(place(h), x, y + 4);
      }
    }
  }

  function drawSurges(ctx, now) {
    const G = PG.engine && PG.engine.G;
    if (!G || G.sh !== sh || !PG.render) return;
    const list = radio.surges;
    for (let i = 0; i < list.length && i < MAX; i++) {
      if (!ann[i] || fin[i]) continue;
      const s = list[i];
      const active = G.t >= s.t0;
      const k = pxPerM(s.x, s.y);
      const x = pa.x, y = pa.y;
      const r = Math.max(14, s.r * k);
      const pulse = PG.REDUCED ? 0 : Math.sin(now * 3);
      const rr = r * (1 + 0.04 * pulse);
      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, rr, 0, 6.2832);
      const amber = pal().pins[0];
      ctx.globalAlpha = active ? 0.18 : 0.07;
      ctx.fillStyle = amber;
      ctx.fill();
      ctx.globalAlpha = active ? 0.9 : 0.6;
      ctx.setLineDash(active ? SOLID : DASH);
      ctx.lineWidth = 2;
      ctx.strokeStyle = amber;
      ctx.stroke();
      ctx.setLineDash(SOLID);
      ctx.font = '600 12px system-ui, sans-serif';
      ctx.textAlign = 'center';
      const txt = '📻 Хвиля замовлень: ' + place(s);
      const tw = ctx.measureText(txt).width + 10;
      ctx.globalAlpha = 1;
      ctx.fillStyle = pal().card;
      ctx.fillRect(x - tw / 2, y - rr - 20, tw, 18);
      ctx.fillStyle = pal().ink;
      ctx.fillText(txt, x, y - rr - 6);
      ctx.restore();
    }
  }

  function init() {
    glow = makeGlow();
    if (PG.render && PG.render.onDraw) {
      PG.render.onDraw(drawHot, -1);
      PG.render.onDraw(drawSurges, 1);
    }
    PG.bus.on('frame', function () { update(PG.engine && PG.engine.G); });
    PG.bus.on('shift:start', function (e) { reset(e && e.sh); });
  }
})(typeof window !== 'undefined' ? window : globalThis);
