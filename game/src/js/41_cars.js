/* 41_cars.js: drawn top-down cars from cached sprites, with smooth turning. No DOM at load. */
(function (root) {
  const PG = root.PG = root.PG || {};

  const L = 40;            // sprite car length, logical units (the car points to +x)
  const WID = 20;
  const BOX = 76;          // sprite box side, logical units (room for the glow)
  const RES = 2;           // sprite pixels per logical unit
  const GLOW_R = 34;
  const TURN_RATE = 11;    // 1/s: how fast the heading follows the target
  const TAU = Math.PI * 2;

  const sprites = {};
  const ang = new Float32Array(32);
  const seen = new Uint8Array(32);

  function rrect(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
  }

  function makeSprite(color, hero) {
    const cv = document.createElement('canvas');
    cv.width = cv.height = BOX * RES;
    const c = cv.getContext('2d');
    c.scale(RES, RES);
    c.translate(BOX / 2, BOX / 2);
    const g = c.createRadialGradient(0, 0, 8, 0, 0, GLOW_R);
    g.addColorStop(0, color);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    c.globalAlpha = hero ? 0.22 : 0.12;
    c.fillStyle = g;
    c.beginPath(); c.arc(0, 0, GLOW_R, 0, TAU); c.fill();
    c.globalAlpha = 1;
    c.fillStyle = 'rgba(0,0,0,0.45)';             // soft contact shadow
    rrect(c, -L / 2 - 1.5, -WID / 2 - 1.5, L + 3, WID + 3, 9); c.fill();
    c.fillStyle = color;                         // body
    rrect(c, -L / 2, -WID / 2, L, WID, 7.5); c.fill();
    c.fillStyle = 'rgba(255,255,255,0.28)';      // top light
    rrect(c, -L / 2 + 4, -WID / 2 + 1.5, L - 8, 4, 2); c.fill();
    c.fillStyle = 'rgba(7,11,20,0.82)';          // windscreen, roof gap, rear window
    rrect(c, 1, -WID / 2 + 2.5, 11, WID - 5, 3); c.fill();
    rrect(c, -15, -WID / 2 + 3.5, 5.5, WID - 7, 2); c.fill();
    c.fillStyle = 'rgba(0,0,0,0.22)';            // roof
    rrect(c, -9, -WID / 2 + 2, 9.5, WID - 4, 2); c.fill();
    c.fillStyle = '#fff6c9';                     // headlights
    c.beginPath(); c.arc(L / 2 - 2.5, -WID / 2 + 4, 2.2, 0, TAU); c.arc(L / 2 - 2.5, WID / 2 - 4, 2.2, 0, TAU); c.fill();
    c.fillStyle = '#ff4d4d';                     // tail lights
    c.fillRect(-L / 2, -WID / 2 + 2.5, 1.8, 4);
    c.fillRect(-L / 2, WID / 2 - 6.5, 1.8, 4);
    if (hero) {
      c.fillStyle = '#ffffff';                   // plain roof light bar
      rrect(c, -6, -4, 6, 8, 2); c.fill();
      c.lineWidth = 1.6; c.strokeStyle = 'rgba(255,255,255,0.9)';
      rrect(c, -L / 2, -WID / 2, L, WID, 7.5); c.stroke();
    }
    return cv;
  }

  function sprite(color, hero) {
    const k = color + (hero ? '!' : '');
    return sprites[k] || (sprites[k] = makeSprite(color, hero));
  }

  // Heading follows the target by the shortest way round, so the car turns instead of snapping.
  function turn(slot, hx, hy, dt, still) {
    if (hx || hy) {
      const t = Math.atan2(hy, hx);
      if (!seen[slot]) { seen[slot] = 1; ang[slot] = t; }
      else {
        let d = t - ang[slot];
        d -= TAU * Math.round(d / TAU);
        ang[slot] += still ? d : d * (1 - Math.exp(-dt * TURN_RATE));
      }
    }
    return ang[slot];
  }

  function reset() { seen.fill(0); }

  // len: car length in screen px. kind 'hero' adds the roof light and a white outline.
  function draw(ctx, px, py, a, len, color, alpha, kind) {
    const s = len / L;
    const sz = BOX * s;
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(a);
    ctx.globalAlpha = alpha;
    ctx.drawImage(sprite(color, kind === 'hero'), -sz / 2, -sz / 2, sz, sz);
    ctx.restore();
  }

  PG.cars = { draw: draw, turn: turn, reset: reset };
})(typeof window !== 'undefined' ? window : globalThis);
