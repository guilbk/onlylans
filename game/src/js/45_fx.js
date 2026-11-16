(function (root) {
  const PG = root.PG = root.PG || {};

  const NP = 96;            // pooled particles
  const NC = 140;           // pooled confetti pieces
  const NT = 10;            // pooled floating texts
  const TAU = Math.PI * 2;

  // particle pool (structure of arrays): world anchor + pixel offset
  const pLife = new Float32Array(NP), pMax = new Float32Array(NP);
  const pWx = new Float32Array(NP), pWy = new Float32Array(NP);
  const pOx = new Float32Array(NP), pOy = new Float32Array(NP);
  const pVx = new Float32Array(NP), pVy = new Float32Array(NP);
  const pSize = new Float32Array(NP);
  const pColor = new Array(NP).fill('#fff');
  let pNext = 0;

  // floating texts
  const tLife = new Float32Array(NT), tMax = new Float32Array(NT);
  const tWx = new Float32Array(NT), tWy = new Float32Array(NT), tOy = new Float32Array(NT);
  const tText = new Array(NT).fill('');
  const tColor = new Array(NT).fill('#fff');
  let tNext = 0;

  // confetti (screen space, own overlay canvas)
  const cLife = new Float32Array(NC);
  const cX = new Float32Array(NC), cY = new Float32Array(NC);
  const cVx = new Float32Array(NC), cVy = new Float32Array(NC);
  const cRot = new Float32Array(NC), cVr = new Float32Array(NC), cW = new Float32Array(NC);
  const cColor = new Array(NC).fill('#fff');
  let cActive = 0;

  const MEDAL_COL = ['#8a96b3', '#cd7f32', '#c0c8d8', '#ffd700', '#b48cff'];
  const GOLD = '#ffd700';

  let initDone = false;
  let mapEl = null, rankEl = null, comboEl = null, bannerEl = null, confEl = null, confCtx = null;
  let shakeT = 0, shakeMax = 0, shaking = false;
  let bannerT = 0, comboT = 0, rankT = 0;
  let confDirty = false, confW = 0, confH = 0;
  let lastNow = 0;

  function fmtEur(x) { return PG.util && PG.util.eur ? PG.util.eur(x) : '€' + x.toFixed(2).replace('.', ','); }
  function G() { return PG.engine && PG.engine.G ? PG.engine.G : null; }
  function rnd() { return Math.random(); }

  function spawn(wx, wy, vx, vy, life, size, color) {
    const i = pNext; pNext = (pNext + 1) % NP;
    pLife[i] = life; pMax[i] = life;
    pWx[i] = wx; pWy[i] = wy; pOx[i] = 0; pOy[i] = 0;
    pVx[i] = vx; pVy[i] = vy; pSize[i] = size; pColor[i] = color;
  }

  function floatText(wx, wy, text, color, life) {
    const i = tNext; tNext = (tNext + 1) % NT;
    tLife[i] = life; tMax[i] = life; tWx[i] = wx; tWy[i] = wy; tOy[i] = 0;
    tText[i] = text; tColor[i] = color;
  }

  function burst(wx, wy, n, color, speed, life) {
    for (let k = 0; k < n; k++) {
      const a = rnd() * TAU, s = speed * (0.4 + rnd() * 0.6);
      spawn(wx, wy, Math.cos(a) * s, Math.sin(a) * s, life * (0.6 + rnd() * 0.4), 2 + rnd() * 2, color);
    }
  }

  function restartClass(el, cls, ms, which) {
    if (!el) return;
    el.classList.remove(cls);
    void el.offsetWidth;            // restart the CSS animation
    el.classList.add(cls);
    if (which === 'rank') rankT = ms; else if (which === 'combo') comboT = ms;
  }

  function showCombo(n, k) {
    if (!comboEl) return;
    if (n < 2) { comboEl.classList.remove('on'); comboT = 0; return; }
    comboEl.textContent = '×' + k.toFixed(1).replace('.', ',') ;
    comboEl.classList.add('on');
    restartClass(comboEl, 'pop', 400, 'combo');
  }

  function showBanner(text, sec) {
    if (!bannerEl) return;
    bannerEl.textContent = text;
    bannerEl.classList.remove('on');
    void bannerEl.offsetWidth;
    bannerEl.classList.add('on');
    bannerT = sec;
  }

  function sizeConf() {
    const w = root.innerWidth || 400, h = root.innerHeight || 700;
    if (w !== confW || h !== confH) { confW = w; confH = h; confEl.width = w; confEl.height = h; }
  }

  function startConfetti(level) {
    if (!confEl || level < 1) return;
    sizeConf();
    const n = Math.min(NC, (PG.REDUCED ? 20 : 30) + level * (PG.REDUCED ? 10 : 25));
    const cols = [MEDAL_COL[level], '#ffffff', '#3df5b0', '#5ee6ff', '#ffc857'];
    cActive = 0;
    for (let i = 0; i < n; i++) {
      cLife[i] = 2.2 + rnd() * 1.4;
      cX[i] = confW * (0.15 + rnd() * 0.7); cY[i] = -10 - rnd() * confH * 0.25;
      cVx[i] = (rnd() - 0.5) * 140; cVy[i] = 120 + rnd() * 160;
      cRot[i] = rnd() * TAU; cVr[i] = (rnd() - 0.5) * 12; cW[i] = 5 + rnd() * 5;
      cColor[i] = i % 3 === 0 ? cols[0] : cols[i % cols.length];
      cActive++;
    }
    confEl.style.display = 'block';
    confDirty = true;
  }

  function updateConfetti(dt) {
    if (!cActive) return;
    confCtx.clearRect(0, 0, confW, confH);
    let alive = 0;
    for (let i = 0; i < NC; i++) {
      if (cLife[i] <= 0) continue;
      cLife[i] -= dt;
      if (cLife[i] <= 0) continue;
      alive++;
      cX[i] += cVx[i] * dt; cY[i] += cVy[i] * dt; cRot[i] += cVr[i] * dt;
      cVx[i] += Math.sin(cRot[i]) * 30 * dt;
      confCtx.globalAlpha = cLife[i] < 0.5 ? cLife[i] * 2 : 1;
      confCtx.fillStyle = cColor[i];
      confCtx.save();
      confCtx.translate(cX[i], cY[i]);
      confCtx.rotate(cRot[i]);
      confCtx.fillRect(-cW[i] / 2, -cW[i] / 4, cW[i], cW[i] / 2);
      confCtx.restore();
    }
    confCtx.globalAlpha = 1;
    if (!alive) { cActive = 0; confCtx.clearRect(0, 0, confW, confH); confEl.style.display = 'none'; }
  }

  function stopConfetti() {
    for (let i = 0; i < NC; i++) cLife[i] = 0;
    cActive = 0;
    if (confEl) { confEl.style.display = 'none'; if (confCtx) confCtx.clearRect(0, 0, confW, confH); }
  }

  function clearAll() {
    pLife.fill(0); tLife.fill(0);
    shakeT = 0;
    if (shaking && mapEl) { mapEl.style.transform = ''; shaking = false; }
    if (comboEl) comboEl.classList.remove('on');
    if (bannerEl) bannerEl.classList.remove('on');
    stopConfetti();
  }

  function onFrame(e) {
    const dt = e && e.dt ? e.dt : 0.016;
    for (let i = 0; i < NP; i++) {
      if (pLife[i] <= 0) continue;
      pLife[i] -= dt;
      pOx[i] += pVx[i] * dt; pOy[i] += pVy[i] * dt;
      pVx[i] *= 0.96; pVy[i] *= 0.96;
    }
    for (let i = 0; i < NT; i++) {
      if (tLife[i] <= 0) continue;
      tLife[i] -= dt; tOy[i] -= 38 * dt;
    }
    if (shakeT > 0) {
      shakeT -= dt;
      if (mapEl) {
        if (shakeT > 0) {
          const a = 7 * (shakeT / shakeMax);
          mapEl.style.transform = 'translate(' + ((rnd() - 0.5) * 2 * a).toFixed(1) + 'px,' + ((rnd() - 0.5) * 2 * a).toFixed(1) + 'px)';
          shaking = true;
        } else { mapEl.style.transform = ''; shaking = false; }
      }
    }
    if (bannerT > 0) { bannerT -= dt; if (bannerT <= 0 && bannerEl) bannerEl.classList.remove('on'); }
    if (confDirty || cActive) { confDirty = false; updateConfetti(dt); }
  }

  function drawPinDecor(ctx, now) {
    const pins = PG.render && PG.render.pins;
    const R = PG.rules;
    if (!pins || !R) return;
    const t = now / 1000;
    for (let i = 0; i < pins.length; i++) {
      const p = pins[i];
      if (!p.reach) continue;
      const k = R.kindOf(p.o);
      if (k === 'regular') continue;
      const x = p.px, y = p.py, r = p.r;
      if (k === 'vip') {
        const pulse = 0.5 + 0.5 * Math.sin(t * 3 + i);
        ctx.fillStyle = GOLD;
        ctx.globalAlpha = 0.14 + 0.14 * pulse;
        ctx.beginPath(); ctx.arc(x, y, r + 12 + pulse * 3, 0, TAU); ctx.fill();
        ctx.strokeStyle = GOLD;
        ctx.lineWidth = 2;
        ctx.globalAlpha = 0.5 + 0.4 * pulse;
        ctx.beginPath(); ctx.arc(x, y, r + 12 + pulse * 3, 0, TAU); ctx.stroke();
      } else if (k === 'tourist') {
        // small suitcase above the pin
        const cx = x + r * 0.9, cy = y - r - 5;
        ctx.globalAlpha = 0.95;
        ctx.fillStyle = '#5ee6ff';
        ctx.fillRect(cx - 5, cy - 3, 10, 7);
        ctx.strokeStyle = '#0e1424'; ctx.lineWidth = 1;
        ctx.strokeRect(cx - 5, cy - 3, 10, 7);
        ctx.strokeStyle = '#5ee6ff';
        ctx.beginPath(); ctx.moveTo(cx - 2, cy - 3); ctx.lineTo(cx - 2, cy - 5); ctx.lineTo(cx + 2, cy - 5); ctx.lineTo(cx + 2, cy - 3); ctx.stroke();
      } else if (k === 'rush') {
        // short, hurried ring: a rotating arc
        ctx.strokeStyle = '#ff4d6a'; ctx.lineWidth = 2.5; ctx.globalAlpha = 0.95;
        const a0 = t * 7 + i;
        ctx.beginPath(); ctx.arc(x, y, r + 4, a0, a0 + 1.6); ctx.stroke();
        ctx.beginPath(); ctx.arc(x, y, r + 4, a0 + Math.PI, a0 + Math.PI + 1.6); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }

  function drawFx(ctx, now) {
    lastNow = now;
    drawPinDecor(ctx, now);
    const R = PG.render;
    if (!R || !R.P) return;
    for (let i = 0; i < NP; i++) {
      if (pLife[i] <= 0) continue;
      const q = R.P(pWx[i], pWy[i]);
      ctx.globalAlpha = Math.max(0, pLife[i] / pMax[i]);
      ctx.fillStyle = pColor[i];
      ctx.beginPath(); ctx.arc(q.x + pOx[i], q.y + pOy[i], pSize[i], 0, TAU); ctx.fill();
    }
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    ctx.font = 'bold 14px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
    for (let i = 0; i < NT; i++) {
      if (tLife[i] <= 0) continue;
      const q = R.P(tWx[i], tWy[i]);
      const a = Math.min(1, tLife[i] / (tMax[i] * 0.4));
      ctx.globalAlpha = a;
      ctx.fillStyle = '#0e1424';
      ctx.fillText(tText[i], q.x + 1, q.y + tOy[i] + 1);
      ctx.fillStyle = tColor[i];
      ctx.fillText(tText[i], q.x, q.y + tOy[i]);
    }
    ctx.globalAlpha = 1;
  }

  function mk(tag, id, parent) {
    const el = document.createElement(tag);
    el.id = id;
    parent.appendChild(el);
    return el;
  }

  function init() {
    if (initDone) return;
    initDone = true;
    const stage = document.getElementById('stage') || document.body;
    mapEl = document.getElementById('map');
    rankEl = document.getElementById('hud-rank');
    comboEl = mk('div', 'fx-combo', stage);
    bannerEl = mk('div', 'fx-banner', stage);
    comboEl.setAttribute('aria-hidden', 'true');
    bannerEl.setAttribute('role', 'status');
    confEl = mk('canvas', 'fx-confetti', document.body);
    confEl.setAttribute('aria-hidden', 'true');
    confCtx = confEl.getContext('2d');
    if (PG.render && PG.render.onDraw) PG.render.onDraw(drawFx, 10);

    const bus = PG.bus;
    bus.on('frame', onFrame);
    bus.on('shift:start', clearAll);
    bus.on('ui:screen', function (e) { if (e && e.name !== 'result') stopConfetti(); });

    bus.on('pickup', function (p) {
      const o = p.o;
      const k = PG.rules ? PG.rules.kindOf(o) : 'regular';
      burst(o.x0, o.y0, 14, k === 'vip' ? GOLD : k === 'rush' ? '#ff4d6a' : '#3df5b0', 95, 0.7);
      for (let i = 0; i < 4; i++) {
        spawn(o.x0, o.y0, (rnd() - 0.5) * 40, -60 - rnd() * 50, 0.9, 3.5, GOLD);
      }
    });

    bus.on('dropoff', function (p) {
      const o = p.o;
      if (p.tip > 0) {
        floatText(o.x1, o.y1, '+' + fmtEur(p.tip) + ' чайові', GOLD, 1.5);
        burst(o.x1, o.y1, 8, GOLD, 70, 0.6);
      } else {
        burst(o.x1, o.y1, 5, '#3df5b0', 50, 0.5);
      }
    });

    bus.on('combo', function (p) { showCombo(p.n, p.k); });
    bus.on('combo:break', function () { showCombo(0, 1); });

    bus.on('rank:change', function (p) {
      if (p.prev != null && p.rank < p.prev) {
        rankEl = rankEl || document.getElementById('hud-rank');
        restartClass(rankEl, 'fx-rank-up', 800, 'rank');
        if (rankEl) setTimeout(function () { rankEl.classList.remove('fx-rank-up'); }, 850);
      }
    });

    bus.on('ghost:overtake', function (p) {
      if (p.ahead) showBanner('Ти попереду привида!', 2.2);
    });

    bus.on('order:lost', function (p) {
      const g = G();
      if (!g || PG.REDUCED) return;
      if (p.by === 'real' || g.cur === p.o || g.next === p.o) { shakeT = shakeMax = 0.32; }
    });

    bus.on('medal', function (p) { startConfetti(p.level | 0); });
  }

  PG.fx = { init, _burst: burst };
})(typeof window !== 'undefined' ? window : globalThis);
