// Porto landmarks: small flat-vector silhouettes under pins and cars.
// Positions, label spots and tiers come from PG.landmarks (pipeline/landmarks.py, game model).
(function (root) {
  const PG = root.PG = root.PG || {};
  const TAU = Math.PI * 2;
  const FADE_LO = 0.07, FADE_HI = 0.12;     // px per metre: labels fade in between these
  const TIER1_K = 0.11;                      // tier-1 landmarks appear only when zoomed in this far
  const MARGIN = 60;                         // px outside the screen still drawn

  // [body, roof/accent, shade] per theme
  const DAY = { body: '#e8d3a8', accent: '#c4552f', shade: '#2456c4', lit: '#2456c4', text: '#12234a' };
  const NIGHT = { body: '#2f4280', accent: '#8fb8ff', shade: '#16244d', lit: '#ffd98a', text: '#eaf0ff' };

  let glow = null;

  function makeGlow() {
    if (typeof document === 'undefined') return null;
    const c = document.createElement('canvas');
    c.width = c.height = 64;
    const g = c.getContext('2d');
    const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, 'rgba(255,217,138,0.5)');
    gr.addColorStop(1, 'rgba(255,217,138,0)');
    g.fillStyle = gr;
    g.fillRect(0, 0, 64, 64);
    return c;
  }

  function isNight() {
    if (PG.theme && PG.theme.name) return PG.theme.name === 'night';
    const G = PG.engine && PG.engine.G;
    if (!G || !G.sh) return true;           // the map is dark outside a shift
    const h = Math.floor(G.sh.startHour + (G.t || 0) / 3600) % 24;
    return h >= 22 || h <= 5;
  }

  function rect(ctx, x, y, w, h, c) { ctx.fillStyle = c; ctx.fillRect(x, y, w, h); }
  function tri(ctx, ax, ay, bx, by, cx, cy, c) {
    ctx.fillStyle = c; ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.lineTo(cx, cy); ctx.fill();
  }
  function disc(ctx, x, y, r, c) { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.fill(); }
  function dome(ctx, x, y, r, c) { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(x, y, r, Math.PI, TAU); ctx.fill(); }

  // Each drawer works in a box x -14..14, y -32..0 around the base point (0, 0).
  const DRAW = {
    tower(ctx, p) {            // Torre dos Clérigos: tall baroque tower
      rect(ctx, -6, -24, 12, 24, p.body); rect(ctx, -5, -30, 10, 6, p.body);
      rect(ctx, -7, -25, 14, 2, p.accent); tri(ctx, -5, -30, 5, -30, 0, -34, p.accent);
      rect(ctx, -1.5, -20, 3, 6, p.lit); rect(ctx, -1.5, -10, 3, 5, p.lit);
    },
    bridge(ctx, p) {           // Ponte Luís I: double-deck iron arch
      rect(ctx, -15, -20, 30, 3, p.accent); rect(ctx, -15, -6, 30, 2, p.accent);
      ctx.strokeStyle = p.body; ctx.lineWidth = 3; ctx.beginPath();
      ctx.arc(0, 0, 14, Math.PI * 1.08, Math.PI * 1.92); ctx.stroke();
      for (let i = -9; i <= 9; i += 6) rect(ctx, i, -18, 1.5, 12, p.shade);
    },
    cathedral(ctx, p) {        // Sé: fortress church, two towers
      rect(ctx, -13, -14, 26, 14, p.body); rect(ctx, -13, -24, 7, 10, p.body); rect(ctx, 6, -24, 7, 10, p.body);
      tri(ctx, -14, -24, -5, -24, -9.5, -29, p.accent); tri(ctx, 5, -24, 14, -24, 9.5, -29, p.accent);
      ctx.fillStyle = p.shade; ctx.beginPath(); ctx.arc(0, -7, 4, Math.PI, TAU); ctx.fillRect(-4, -7, 8, 7); ctx.fill();
      disc(ctx, 0, -17, 3, p.lit);
    },
    station(ctx, p) {          // São Bento: long hall with clock and mansard roofs
      rect(ctx, -15, -14, 30, 14, p.body); rect(ctx, -15, -17, 30, 3, p.accent);
      rect(ctx, -4, -26, 8, 12, p.body); tri(ctx, -5, -26, 5, -26, 0, -31, p.accent);
      disc(ctx, 0, -20, 2.5, p.lit);
      for (let i = -12; i <= 8; i += 6) rect(ctx, i, -9, 4, 9, p.shade);
    },
    bookshop(ctx, p) {         // Lello: narrow neo-gothic front with a rose window
      rect(ctx, -8, -22, 16, 22, p.body); tri(ctx, -9, -22, 9, -22, 0, -30, p.accent);
      disc(ctx, 0, -16, 3.5, p.lit); rect(ctx, -3, -8, 6, 8, p.shade);
      rect(ctx, -8, -3, 16, 1.5, p.accent);
    },
    hall(ctx, p) {             // Casa da Música: faceted crystal block
      ctx.fillStyle = p.body; ctx.beginPath();
      ctx.moveTo(-14, 0); ctx.lineTo(-10, -16); ctx.lineTo(-2, -22); ctx.lineTo(12, -18); ctx.lineTo(14, 0); ctx.fill();
      tri(ctx, -10, -16, -2, -22, 2, -6, p.accent); tri(ctx, 12, -18, 14, 0, 2, -6, p.shade);
      rect(ctx, -6, -9, 4, 3, p.lit);
    },
    palace(ctx, p) {           // Palácio da Bolsa: neoclassical front with a dome
      rect(ctx, -14, -12, 28, 12, p.body); tri(ctx, -14, -12, 14, -12, 0, -20, p.accent);
      dome(ctx, 0, -20, 6, p.accent); rect(ctx, -0.8, -29, 1.6, 4, p.accent);
      for (let i = -10; i <= 8; i += 6) rect(ctx, i, -10, 2.5, 10, p.shade);
    },
    museum(ctx, p) {           // Serralves: low white villa and a tree
      rect(ctx, -14, -10, 18, 10, p.body); rect(ctx, -14, -12, 18, 2, p.accent);
      rect(ctx, -10, -7, 4, 4, p.lit); rect(ctx, -2, -7, 4, 4, p.lit);
      rect(ctx, 9, -8, 2, 8, p.shade); disc(ctx, 10, -13, 6, p.accent);
    },
    square(ctx, p) {           // Aliados: boulevard with town hall tower
      rect(ctx, -14, -4, 28, 4, p.shade); rect(ctx, -3, -1, 6, 1, p.lit);
      rect(ctx, -6, -18, 12, 14, p.body); rect(ctx, -2.5, -25, 5, 7, p.body);
      tri(ctx, -3.5, -25, 3.5, -25, 0, -30, p.accent); disc(ctx, 0, -21, 1.6, p.lit);
      disc(ctx, -11, -8, 3, p.accent); disc(ctx, 11, -8, 3, p.accent);
    },
    market(ctx, p) {           // Bolhão: market hall with striped awning
      rect(ctx, -14, -14, 28, 14, p.body);
      for (let i = 0; i < 7; i++) rect(ctx, -14 + i * 4, -18, 4, 7, i % 2 ? p.accent : p.lit);
      rect(ctx, -3, -8, 6, 8, p.shade);
    },
    houses(ctx, p) {           // Ribeira: row of narrow coloured houses
      const col = [p.accent, p.body, p.lit, p.body];
      for (let i = 0; i < 4; i++) {
        const h = 12 + (i % 2) * 4;
        rect(ctx, -14 + i * 7, -h, 7, h, col[i]);
        tri(ctx, -14 + i * 7, -h, -7 + i * 7, -h, -10.5 + i * 7, -h - 3, p.shade);
      }
    },
  };

  function draw(ctx, now) {
    const L = PG.landmarks, R = PG.render;
    if (!glow) glow = makeGlow();
    if (!L || !R || !R.P) return;
    const items = L.items, p = isNight() ? NIGHT : DAY, night = p === NIGHT;
    const W = ctx.canvas.clientWidth || 800, H = ctx.canvas.clientHeight || 800;
    const a = R.P(0, 0), x0 = a.x, y0 = a.y;
    const k = Math.abs(R.P(100, 0).x - x0) / 100;       // px per metre, same helper as PG.fx
    if (k < FADE_LO * 0.5) return;
    const alphaLabel = Math.max(0, Math.min(1, (k - 0.16) / 0.04));   // names only when zoomed in
    const grow = Math.max(1.25, Math.min(2.0, 0.9 + k * 5)) * (root.innerWidth < 640 ? 0.7 : 1);   // gentle icon scale with zoom; smaller on phones
    ctx.save();
    ctx.font = '700 13px Trebuchet MS, Helvetica Neue, system-ui, sans-serif';
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.tier && k < TIER1_K) continue;
      const sx = x0 + it.x * k, sy = y0 + it.y * k;
      if (sx < -MARGIN || sy < -MARGIN || sx > W + MARGIN || sy > H + MARGIN) continue;
      ctx.save();
      ctx.translate(sx, sy);
      if (night && glow) {
        ctx.globalAlpha = 0.8;
        ctx.drawImage(glow, -34, -52, 68, 68);
      }
      ctx.globalAlpha = night ? 0.35 : 0.4;       // soft halo ring so a landmark stands out from the buildings
      ctx.lineWidth = 2; ctx.strokeStyle = p.accent;
      ctx.beginPath(); ctx.arc(0, -14 * grow, 19 * grow, 0, TAU); ctx.stroke();
      ctx.globalAlpha = 0.97;
      ctx.scale(grow, grow);
      DRAW[it.kind](ctx, p);
      ctx.restore();
      if (alphaLabel > 0) {
        ctx.globalAlpha = alphaLabel;
        ctx.textAlign = it.align === 'l' ? 'left' : it.align === 'r' ? 'right' : 'center';
        ctx.lineWidth = 4;
        ctx.strokeStyle = night ? 'rgba(8,15,36,0.85)' : 'rgba(255,250,240,0.9)';
        const lx = it.align === 'l' ? Math.min(it.lx, -(16 * grow + 4)) : it.align === 'r' ? Math.max(it.lx, 16 * grow + 4) : it.lx;
        const ly = it.align === 'l' || it.align === 'r' ? it.ly : it.ly >= 0 ? Math.max(it.ly, 14) : Math.min(it.ly, -(36 * grow + 4));   // clear of the icon
        ctx.strokeText(it.label, sx + lx, sy + ly);
        ctx.fillStyle = p.text;
        ctx.fillText(it.label, sx + lx, sy + ly);
      }
    }
    ctx.restore();
  }

  // 99_boot.js only inits known modules, so register the layer at load (PG.render exists already)
  if (PG.render && PG.render.onDraw) PG.render.onDraw(draw, -2);
})(typeof window !== 'undefined' ? window : globalThis);
