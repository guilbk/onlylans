(function (root) {
  const PG = root.PG = root.PG || {};

  const NP = 96;            // pooled particles
  const NC = 140;           // pooled confetti pieces
    const NR = 14;            // pooled expanding rings
  const NF = 8;             // pooled «+€N» floats that fly to the money counter
  const HOLD_S = 0.5;       // a fly float first rises where it was earned ...
  const FLY_S = 0.55;       // ... then flies to the money counter
  const TAU = Math.PI * 2;

  // particle pool (structure of arrays): world anchor + pixel offset
  const pLife = new Float32Array(NP), pMax = new Float32Array(NP);
  const pWx = new Float32Array(NP), pWy = new Float32Array(NP);
  const pOx = new Float32Array(NP), pOy = new Float32Array(NP);
  const pVx = new Float32Array(NP), pVy = new Float32Array(NP);
  const pSize = new Float32Array(NP);
  const pColor = new Array(NP).fill('#fff');
  let pNext = 0;

  // rings: world anchor (or screen px when rW is 0), radius r0 -> r1
  const rLife = new Float32Array(NR), rMax = new Float32Array(NR);
  const rX = new Float32Array(NR), rY = new Float32Array(NR);
  const rR0 = new Float32Array(NR), rR1 = new Float32Array(NR), rW = new Uint8Array(NR);
  const rColor = new Array(NR).fill('#fff');
  let rNext = 0;

  // fly floats (own overlay canvas above the HUD)
  const fAge = new Float32Array(NF), fWx = new Float32Array(NF), fWy = new Float32Array(NF);
  const fSx = new Float32Array(NF), fSy = new Float32Array(NF);
  const fOn = new Uint8Array(NF);
  const fText = new Array(NF).fill(''), fText2 = new Array(NF).fill(''), fColor = new Array(NF).fill('#fff');
  let fNext = 0, fActive = 0, flyEl = null, flyCtx = null, flyW = 0, flyH = 0, flyDpr = 1;
  const tgt = { x: 0, y: 0 };
  let moneyEl = null, moneyT = 0;

  // confetti (screen space, own overlay canvas)
  const cLife = new Float32Array(NC);
  const cX = new Float32Array(NC), cY = new Float32Array(NC);
  const cVx = new Float32Array(NC), cVy = new Float32Array(NC);
  const cRot = new Float32Array(NC), cVr = new Float32Array(NC), cW = new Float32Array(NC);
  const cColor = new Array(NC).fill('#fff');
  let cActive = 0;

  const MEDAL_COL = ['#8a96b3', '#cd7f32', '#c0c8d8', '#ffd700', '#b48cff'];
  const GOLD = '#ffd700';
  const pal = function () { return (PG.theme && PG.theme.pal) || PG.C.THEMES.night; };

  let initDone = false;
  let stageEl = null, mapEl = null, rankEl = null, comboEl = null, bannerEl = null, confEl = null, confCtx = null;
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

  function ring(x, y, r0, r1, life, color, world) {
    if (PG.REDUCED) return;
    const i = rNext; rNext = (rNext + 1) % NR;
    rLife[i] = life; rMax[i] = life; rX[i] = x; rY[i] = y; rR0[i] = r0; rR1[i] = r1;
    rW[i] = world ? 1 : 0; rColor[i] = color;
  }

  function fly(wx, wy, text, text2, color) {
    const i = fNext; fNext = (fNext + 1) % NF;
    if (!fOn[i]) fActive++;
    fAge[i] = 0; fWx[i] = wx; fWy[i] = wy; fOn[i] = 1;
    fText[i] = text; fText2[i] = text2; fColor[i] = color;
  }

  function burst(wx, wy, n, color, speed, life) {
    if (PG.REDUCED) n = Math.ceil(n / 3);
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
    if (cls === 'fx-bump') setTimeout(function () { el.classList.remove(cls); }, 400);
  }

  function showCombo(n, k) {
    if (!comboEl) return;
    if (n < 2) { comboEl.classList.remove('on'); comboT = 0; return; }
    setTop();
    comboEl.textContent = '×' + k.toFixed(1).replace('.', ',') ;
    comboEl.classList.add('on');
    restartClass(comboEl, 'pop', 400, 'combo');
  }

  function showBanner(text, sec) {
    if (!bannerEl) return;
    setTop();
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
    const cols = [MEDAL_COL[level], '#ffffff', pal().acc, '#5ee6ff', '#ffc857'];
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
    pLife.fill(0); rLife.fill(0); fOn.fill(0); fActive = 0;
    if (flyEl) flyEl.style.display = 'none';
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
    for (let i = 0; i < NR; i++) if (rLife[i] > 0) rLife[i] -= dt;
    if (fActive) updateFly(dt);
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
      const x = p.px, y = p.py, r = p.r * (p.k || 1);
      if (k === 'vip') {
        const pulse = 0.5 + 0.5 * Math.sin(t * 3 + i);
        ctx.fillStyle = GOLD;
        ctx.globalAlpha = 0.1 + 0.05 * pulse;
        ctx.beginPath(); ctx.arc(x, y, r + 10 + pulse * 2, 0, TAU); ctx.fill();
        ctx.strokeStyle = GOLD;
        ctx.lineWidth = 2;
        ctx.globalAlpha = 0.55 + 0.2 * pulse;
        ctx.beginPath(); ctx.arc(x, y, r + 10 + pulse * 2, 0, TAU); ctx.stroke();
      } else if (k === 'tourist') {
        // small suitcase above the pin
        const cx = x + r * 0.9, cy = y - r - 5;
        ctx.globalAlpha = 0.95;
        ctx.fillStyle = '#5ee6ff';
        ctx.fillRect(cx - 5, cy - 3, 10, 7);
        ctx.strokeStyle = pal().ink; ctx.lineWidth = 1;
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
    ctx.lineWidth = 3;
    for (let i = 0; i < NR; i++) {
      if (rLife[i] <= 0) continue;
      const f = 1 - rLife[i] / rMax[i];
      const q = rW[i] ? R.P(rX[i], rY[i]) : null;
      ctx.globalAlpha = 0.8 * (1 - f);
      ctx.strokeStyle = rColor[i];
      ctx.beginPath(); ctx.arc(q ? q.x : rX[i], q ? q.y : rY[i], rR0[i] + (rR1[i] - rR0[i]) * (1 - (1 - f) * (1 - f)), 0, TAU); ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  // «+€N» floats: rise where earned, then fly to the money counter (drawn above the HUD)
  function sizeFly() {
    const w = root.innerWidth || 400, h = root.innerHeight || 700;
    flyDpr = Math.min(root.devicePixelRatio || 1, 2);
    if (w !== flyW || h !== flyH) {
      flyW = w; flyH = h;
      flyEl.width = Math.round(w * flyDpr); flyEl.height = Math.round(h * flyDpr);
    }
  }

  function bumpMoney() {
    moneyEl = moneyEl || document.querySelector('.hud-money');
    restartClass(moneyEl, 'fx-bump', 0);
  }

  function updateFly(dt) {
    const R = PG.render;
    const st = document.getElementById('stage');
    moneyEl = moneyEl || document.querySelector('.hud-money');
    if (!flyEl || !R || !st || !moneyEl) { fOn.fill(0); fActive = 0; return; }
    const sr = st.getBoundingClientRect(), mr = moneyEl.getBoundingClientRect();
    tgt.x = mr.left + mr.width * 0.5; tgt.y = mr.top + mr.height * 0.5;
    sizeFly();
    flyEl.style.display = 'block';
    flyCtx.setTransform(flyDpr, 0, 0, flyDpr, 0, 0);
    flyCtx.clearRect(0, 0, flyW, flyH);
    flyCtx.font = '800 18px "Trebuchet MS", "Helvetica Neue", system-ui, sans-serif';
    flyCtx.textAlign = 'center';
    flyCtx.textBaseline = 'middle';
    const hold = PG.REDUCED ? HOLD_S * 1.6 : HOLD_S;
    for (let i = 0; i < NF; i++) {
      if (!fOn[i]) continue;
      fAge[i] += dt;
      const a = fAge[i];
      let x, y, sc = 1, al = 1, txt = fText[i];
      if (a < hold) {
        const s = a / hold, e = 1 - (1 - s) * (1 - s) * (1 - s);
        const q = R.P(fWx[i], fWy[i]);
        x = q.x + sr.left; y = q.y + sr.top - 14 - (PG.REDUCED ? 0 : 28 * e);
        sc = PG.REDUCED ? 1 : 1 + 0.3 * (1 - s);
        if (PG.REDUCED) al = 1 - s * s;
        fSx[i] = x; fSy[i] = y;
      } else if (PG.REDUCED) {
        fOn[i] = 0; fActive--; continue;
      } else {
        const s = (a - hold) / FLY_S;
        if (s >= 1) { fOn[i] = 0; fActive--; bumpMoney(); continue; }
        const e = s * s, u = 1 - e;
        const cxp = fSx[i] + (tgt.x - fSx[i]) * 0.5, cyp = fSy[i] - 50;
        x = u * u * fSx[i] + 2 * u * e * cxp + e * e * tgt.x;
        y = u * u * fSy[i] + 2 * u * e * cyp + e * e * tgt.y;
        sc = 1 - 0.25 * e; txt = fText2[i];
        al = s > 0.8 ? (1 - s) / 0.2 : 1;
      }
      flyCtx.globalAlpha = al;
      flyCtx.save();
      flyCtx.translate(x, y); flyCtx.scale(sc, sc);
      flyCtx.lineWidth = 4; flyCtx.strokeStyle = pal().casing; flyCtx.lineJoin = 'round';
      flyCtx.strokeText(txt, 0, 0);
      flyCtx.fillStyle = fColor[i];
      flyCtx.fillText(txt, 0, 0);
      flyCtx.restore();
    }
    flyCtx.globalAlpha = 1;
    if (!fActive) { flyCtx.clearRect(0, 0, flyW, flyH); flyEl.style.display = 'none'; }
  }

  function setTop() {          // banner and combo badge sit just below the HUD
    const R = PG.render;
    if (R && R.zone) root.document.documentElement.style.setProperty('--fx-top', Math.round(R.zone.top + 8) + 'px');
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
    const stage = stageEl = document.getElementById('stage') || document.body;
    mapEl = document.getElementById('map');
    rankEl = document.getElementById('hud-rank');
    comboEl = mk('div', 'fx-combo', stage);
    bannerEl = mk('div', 'fx-banner', stage);
    comboEl.setAttribute('aria-hidden', 'true');
    bannerEl.setAttribute('role', 'status');
    confEl = mk('canvas', 'fx-confetti', document.body);
    confEl.setAttribute('aria-hidden', 'true');
    confCtx = confEl.getContext('2d');
    flyEl = mk('canvas', 'fx-fly', document.body);
    flyEl.setAttribute('aria-hidden', 'true');
    flyCtx = flyEl.getContext('2d');
    if (PG.render && PG.render.onDraw) PG.render.onDraw(drawFx, 10);

    const bus = PG.bus;
    bus.on('frame', onFrame);
    bus.on('shift:start', clearAll);
    bus.on('ui:screen', function (e) { if (e && e.name !== 'result') stopConfetti(); });

    bus.on('pickup', function (p) {
      const o = p.o;
      const k = PG.rules ? PG.rules.kindOf(o) : 'regular';
      const col = k === 'vip' ? GOLD : k === 'rush' ? '#ff4d6a' : pal().acc;
      burst(o.x0, o.y0, 18, col, 110, 0.7);
      for (let i = 0; i < 4; i++) {
        spawn(o.x0, o.y0, (rnd() - 0.5) * 40, -60 - rnd() * 50, 0.9, 3.5, GOLD);
      }
      ring(o.x0, o.y0, 12, 70, 0.55, col, true);
      ring(o.x0, o.y0, 8, 42, 0.4, '#ffffff', true);
      if (PG.render && PG.render.kick) PG.render.kick(0.05);
      fly(o.x0, o.y0, '+' + fmtEur(p.fare), '+' + fmtEur(p.fare), pal().acc);
    });

    bus.on('dropoff', function (p) {
      const o = p.o;
      burst(o.x1, o.y1, p.tip > 0 ? 14 : 9, p.tip > 0 ? GOLD : pal().acc, 80, 0.6);
      ring(o.x1, o.y1, 10, p.tip > 0 ? 58 : 44, 0.5, p.tip > 0 ? GOLD : pal().acc, true);
      if (PG.render && PG.render.kick) PG.render.kick(0.035);
      if (p.tip > 0) fly(o.x1, o.y1, '+' + fmtEur(p.tip) + ' чайові', '+' + fmtEur(p.tip), GOLD);
    });

    bus.on('tap:fx', function (p) { ring(p.x, p.y, 6, p.pin ? 34 : 26, 0.35, p.pin ? pal().acc : pal().ink, false); });

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
