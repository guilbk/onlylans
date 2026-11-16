(function (root) {
  const PG = root.PG = root.PG || {};
  // Golden order (CONTRACT §20): every WINDOW game seconds one open order turns gold; the player gets ×2 for it.
  // The pick depends only on the shift id, the window number and the order list, so every phone agrees.
  const WINDOW = 1800;            // 45 real seconds (x40)
  const GOLD = '#ffc233';

  const S = { sh: null, w: 0, list: [] };   // golds picked so far for the shift (window 1..w)

  function curG() { return PG.engine && PG.engine.G ? PG.engine.G : null; }

  // The order of window w (>= 1): among orders whose pin is open at the window start, the lowest hash wins.
  function pick(sh, w) {
    const T = w * WINDOW, lead = PG.C.LEAD;
    let best = null, bh = 0;
    for (let i = 0; i < sh.orders.length; i++) {
      const o = sh.orders[i];
      if (o.t <= T) continue;
      if (o.t - lead[o.c] > T) continue;        // its pin is not open yet
      const h = PG.rules._fnv1a32(sh.id + '#gold#' + w + '#' + o.i);
      if (!best || h < bh) { best = o; bh = h; }
    }
    return best;
  }

  // Golds of the shift up to game time t (extends the cache window by window).
  function golds(sh, t) {
    if (S.sh !== sh) { S.sh = sh; S.w = 0; S.list = []; }
    const w = Math.floor(t / WINDOW);
    while (S.w < w) {
      S.w++;
      const o = pick(sh, S.w);
      if (o) { S.list.push(o); announce(o); }
    }
    return S.list;
  }

  function announce(o) {
    const G = curG();
    if (!G || !PG.bus || (G.taken && G.taken.has(o.i))) return;
    PG.bus.emit('note', { text: 'Золоте замовлення: ×2 до плати', ms: 3500 });
    if (PG.audio && PG.audio.play) { try { PG.audio.play('coin'); } catch (e) { /* sound is optional */ } }
  }

  function isGold(o) {
    const G = curG();
    return !!(G && G.sh && o && golds(G.sh, G.t).indexOf(o) >= 0);
  }

  function draw(ctx, now) {
    const G = curG(), R = PG.render;
    if (!G || !G.sh || !R || !R.pins || G.over) return;
    const list = golds(G.sh, G.t);
    if (!list.length) return;
    for (let i = 0; i < R.pins.length; i++) {
      const p = R.pins[i];
      if (list.indexOf(p.o) < 0) continue;
      const pulse = PG.REDUCED ? 0 : 0.5 + 0.5 * Math.sin(now * 5);
      const r = 26 + 4 * pulse;
      ctx.save();
      const g = ctx.createRadialGradient(p.px, p.py, 4, p.px, p.py, r);
      g.addColorStop(0, 'rgba(255,194,51,0.75)');
      g.addColorStop(1, 'rgba(255,194,51,0)');
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(p.px, p.py, r, 0, 6.2832); ctx.fill();
      ctx.lineWidth = 3; ctx.strokeStyle = GOLD;
      ctx.beginPath(); ctx.arc(p.px, p.py, p.r + 2, 0, 6.2832); ctx.stroke();
      ctx.font = '800 12px system-ui, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      const bx = p.px + 14, by = p.py - 20;
      ctx.fillStyle = GOLD; ctx.fillRect(bx - 14, by - 9, 28, 18);
      ctx.fillStyle = '#2a1c00'; ctx.fillText('×2', bx, by + 1);
      ctx.restore();
    }
  }

  const bus = PG.bus;
  if (bus) {
    bus.on('shift:start', function () { S.sh = null; S.w = 0; S.list = []; });
    // the player's drop-off only: rivals never emit it, so they never get the bonus
    bus.on('dropoff', function (p) {
      const G = curG();
      const o = p && p.o;
      if (!G || !G.sh || !o || o._goldPaid || !isGold(o)) return;
      o._goldPaid = true;
      const fare = p.fare != null ? p.fare : o.fare;
      const bonus = Math.round(fare * 100) / 100;
      p.tip = Math.round(((p.tip || 0) + bonus) * 100) / 100;
      G.tips = Math.round(((G.tips || 0) + bonus) * 100) / 100;
      const t = G.leg && isFinite(G.leg.t1) ? G.leg.t1 : G.t;
      const eur = PG.util && PG.util.eur ? PG.util.eur(bonus) : '€' + bonus.toFixed(2).replace('.', ',');
      if (G.floats) G.floats.push({ x: o.x1, y: o.y1, text: '+' + eur + ' ×2', color: GOLD, born: t });
    });
    if (PG.render && PG.render.onDraw) PG.render.onDraw(draw, 6);
  }

  PG.gold = { WINDOW: WINDOW, pick: pick, golds: golds, isGold: isGold };
})(typeof window !== 'undefined' ? window : globalThis);
