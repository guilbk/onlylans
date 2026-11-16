(function (root) {
  const PG = root.PG = root.PG || {};

  // Share card: a 1080x1350 PNG of the finished shift, drawn on an offscreen canvas.
  // Records its own path (shift:start / frame / shift:end) and adds a button to the result screen.
  const W = 1080, H = 1350, SAMPLE_S = 10, MEDALS = ['Без медалі', 'Бронза', 'Срібло', 'Золото', 'Легенда'];
  const MEDAL_VARS = ['--muted', '--bronze', '--silver', '--gold', '--legend'];
  const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

  let path = null;   // flat [x, y, ...] of the player
  let last = 0;
  let res = null;    // result of the shift just finished

  function curG() { return PG.engine && PG.engine.G ? PG.engine.G : null; }
  function css(name, fb) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fb;
  }

  function onStart() {
    const G = curG();
    path = PG.engine && PG.engine.party || !G ? null : [G.x, G.y];
    last = 0;
    res = null;
  }
  function onFrame() {
    const G = curG();
    if (!path || !G || G.t - last < SAMPLE_S) return;
    last = G.t;
    path.push(G.x, G.y);
  }
  function onEnd(p) {
    const G = curG();
    if (path && G) path.push(G.x, G.y);
    res = p && p.result || null;
  }

  // what the card says; mission stars are read from the missions block of the result screen
  function model() {
    if (!res) return null;
    const sh = PG.data && PG.data.shifts ? PG.data.shifts[res.idx] : null;
    const rows = document.querySelectorAll('#msn-res .msn-row');
    const done = document.querySelectorAll('#msn-res .msn-row.done').length;
    return {
      hero: 'Ріїн Гіслінг',
      shift: sh ? sh.name : '', day: sh ? sh.day : '',
      earned: PG.util.eur(res.earned), medal: res.medal,
      rank: '#' + Math.min(res.rank, res.nDrivers) + ' з ' + res.nDrivers + ' ' +
        PG.util.plural(res.nDrivers, 'справжнього водія', 'справжніх водіїв', 'справжніх водіїв'),
      vs: (res.vsGhost >= 0 ? '+' : '−') + PG.util.eur(Math.abs(res.vsGhost)) + ' до привида',
      ahead: res.vsGhost > 0,
      stars: rows.length ? '★'.repeat(done) + '☆'.repeat(rows.length - done) : '',
      path: path || [],
      link: /^https?:$/.test(root.location.protocol) ? root.location.host + root.location.pathname : 'Зіграй свою зміну'
    };
  }

  function text(ctx, s, x, y, size, weight, col) {
    ctx.font = weight + ' ' + size + 'px ' + FONT;
    ctx.fillStyle = col;
    ctx.fillText(s, x, y);
  }

  function miniMap(ctx, pts, x0, y0, w, h) {
    ctx.fillStyle = css('--panel-solid', '#0e1424');
    ctx.beginPath(); ctx.roundRect(x0, y0, w, h, 28); ctx.fill();
    if (pts.length < 4) return;
    let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
    for (let i = 0; i < pts.length; i += 2) {
      a = Math.min(a, pts[i]); c = Math.max(c, pts[i]); b = Math.min(b, pts[i + 1]); d = Math.max(d, pts[i + 1]);
    }
    const pad = 40, bw = Math.max(c - a, 500), bh = Math.max(d - b, 500);
    const k = Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh);
    const ox = x0 + (w - bw * k) / 2, oy = y0 + (h - bh * k) / 2;
    ctx.strokeStyle = css('--hero', '#3df5b0'); ctx.lineWidth = 6; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    ctx.beginPath();
    for (let i = 0; i < pts.length; i += 2) {
      const px = ox + (pts[i] - a) * k, py = oy + (pts[i + 1] - b) * k;
      if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py);
    }
    ctx.stroke();
  }

  function render(m) {
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d');
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, css('--bg', '#070b14')); g.addColorStop(1, css('--panel-solid', '#0e1424'));
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
    const text1 = css('--text', '#e8eefc'), muted = css('--muted', '#8a96b3'), hero = css('--hero', '#3df5b0');
    text(ctx, '7 ланосів', W / 2, 130, 84, 800, hero);
    text(ctx, m.hero, W / 2, 210, 48, 600, text1);
    text(ctx, m.shift, W / 2, 270, 38, 500, muted);
    text(ctx, m.day, W / 2, 322, 30, 400, muted);
    text(ctx, m.earned, W / 2, 470, 150, 800, text1);
    text(ctx, MEDALS[m.medal], W / 2, 550, 64, 700, css(MEDAL_VARS[m.medal], '#ffd700'));
    text(ctx, m.rank, W / 2, 625, 40, 500, text1);
    text(ctx, m.vs, W / 2, 685, 38, 600, css(m.ahead ? '--ahead' : '--behind', hero));
    if (m.stars) text(ctx, 'Завдання ' + m.stars, W / 2, 745, 40, 600, css('--gold', '#ffd700'));
    miniMap(ctx, m.path, 90, 790, W - 180, 400);
    text(ctx, m.link, W / 2, 1275, 34, 500, muted);
    return cv;
  }

  function share() {
    const m = model();
    if (!m) return;
    render(m).toBlob(function (blob) {
      if (!blob) return;
      const file = new File([blob], '7-lanosiv.png', { type: 'image/png' });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        navigator.share({ files: [file], title: '7 ланосів' }).catch(function () {});
        return;
      }
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = file.name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
    }, 'image/png');
  }

  function onScreen(p) {
    if (typeof document === 'undefined' || !p || p.name !== 'result' || !res) return;
    const row = document.querySelector('#result .res-buttons');
    if (!row || row.querySelector('#btn-share')) return;
    const b = document.createElement('button');
    b.type = 'button';
    b.id = 'btn-share';
    b.className = 'btn-big alt share-btn';
    b.textContent = 'Поділитися';
    b.addEventListener('click', share);
    row.insertBefore(b, row.firstChild);
  }

  PG.share = { model: model, render: render };
  if (PG.bus) {
    PG.bus.on('shift:start', onStart);
    PG.bus.on('frame', onFrame);
    PG.bus.on('shift:end', onEnd);
    PG.bus.on('ui:screen', onScreen);
  }
})(typeof window !== 'undefined' ? window : globalThis);
