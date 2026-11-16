(function (root) {
  const PG = root.PG = root.PG || {};
  if (!PG.bus || !PG.audio) return;
  const on = PG.bus.on.bind(PG.bus), A = PG.audio;
  const CD_FROM = 7200 - 10 * 40; // last 10 real seconds of a shift, game s
  let lastRank = 0, cdAcc = 0, cdOn = false;

  on('ui:click', () => A.play('click'));
  on('order:book', () => A.play('book'));
  on('pickup', () => { A.play('pickup'); A.play('coin', { delay: 0.12 }); });
  on('dropoff', (e) => { A.play('dropoff'); if (e && e.tip > 0) A.play('coin', { delay: 0.2 }); });
  on('order:lost', () => A.play('lost'));
  on('rival:lost', () => A.play('steal'));
  on('combo', (e) => A.play('combo', { n: e && e.n }));
  on('combo:break', () => A.play('combo_break'));
  on('rank:change', (e) => {
    const now = Date.now();
    if (!e || now - lastRank < 2000) return;
    lastRank = now;
    A.play(e.rank < e.prev ? 'rank_up' : 'rank_down');
  });
  on('ghost:overtake', (e) => A.play(e && e.ahead ? 'overtake' : 'behind'));
  on('shift:start', (e) => {
    const h = e && e.sh ? e.sh.startHour : 8;
    cdAcc = 0; cdOn = false;
    A.play('shift_start');
    A.music.start(h >= 21 || h < 5 ? 'night' : 'day');
  });
  on('shift:end', () => { A.play('shift_end'); A.music.setIntensity(0.1); A.engine.set(0); });
  on('medal', (e) => A.play('medal', { level: e && e.level }));
  on('pause', (e) => { A.play('pause'); A.music.duck(!!(e && e.paused)); });
  on('ui:screen', (e) => {
    if (e && e.name === 'menu') { A.music.start('menu'); A.music.setIntensity(0.2); A.engine.set(0); }
  });
  on('radio:surge', () => A.play('horn'));

  on('frame', (f) => {
    const G = PG.engine && PG.engine.G;
    if (!G || PG.screen !== 'play') { A.engine.set(0); return; }
    let sp = 0;
    if (!G.over && !G.paused && (G.mode === 'ride' || G.mode === 'pickup' || G.mode === 'cruise')) {
      const sh = G.sh, h = ((sh ? sh.startHour : 8) + Math.floor(G.t / 3600)) % 24;
      sp = sh && sh.speedByHour ? sh.speedByHour[h] / 60 : 0.5;
    }
    A.engine.set(sp);
    if (G.over) return;
    A.music.setIntensity(Math.min(1, 0.25 + 0.2 * (G.combo || 0) + (G.t > 6000 ? 0.2 : 0)));
    if (G.t >= CD_FROM && !G.paused) {
      cdAcc += f ? f.dt : 0;
      if (!cdOn || cdAcc >= 1) { A.play('countdown'); cdAcc = cdOn ? cdAcc - 1 : 0; cdOn = true; }
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
