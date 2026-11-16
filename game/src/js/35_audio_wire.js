(function (root) {
  const PG = root.PG = root.PG || {};
  if (!PG.bus || !PG.audio) return;
  const on = PG.bus.on.bind(PG.bus), A = PG.audio;
  const CD_FROM = 7200 - 10 * 40; // last 10 real seconds of a shift, game s
  let lastRank = 0, cdAcc = 0, cdOn = false, startH = 8;
  const isNight = (h) => h >= 21 || h < 5;
  // 0 day .. 1 night; dusk 19-21 and dawn 5-7 fade gradually
  const nightW = (h) => (h >= 21 || h < 5 ? 1 : h >= 19 ? (h - 19) / 2 : h >= 5 && h < 7 ? (7 - h) / 2 : 0);
  function hash(str) { // fnv1a32
    let x = 0x811c9dc5;
    for (let i = 0; i < str.length; i++) { x ^= str.charCodeAt(i); x = Math.imul(x, 0x01000193) >>> 0; }
    return x >>> 0;
  }
  let rlvl = -1;
  const radioLvl = (l) => { if (l !== rlvl) { rlvl = l; A.radio.level(l); } };
  function menuBed() { // no tune in the menu: only a very soft city bed
    A.fast.set(false); radioLvl(0);
    A.ambience.set({ night: 0, rain: 0, traffic: 0.12, speed: 0, hour: 12 });
  }
  function sceneOff() { A.fast.set(false); A.ambience.stop(); radioLvl(0); }

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
    cdAcc = 0; cdOn = false; startH = h;
    A.play('shift_start');
    const hs = hash(String(e && e.sh && e.sh.id != null ? e.sh.id : e && e.idx != null ? e.idx : 0));
    A.radio.seed(hs); // each shift gets its own station order
    A.music.start(isNight(h) ? 'night' : 'day');
    rlvl = -1; radioLvl(0.4);
    // rain: about one shift in four, fixed by the shift id
    A.fast.set(false);
    A.ambience.set({
      night: nightW(h), rain: hs % 4 === 0 ? 0.4 + ((hs >>> 8) % 50) / 100 : 0,
      traffic: 0.5 + ((hs >>> 16) % 40) / 100, speed: 0, hour: h
    });
  });
  on('shift:end', () => { A.play('shift_end'); A.music.setIntensity(0.1); A.engine.set(0); sceneOff(); });
  on('medal', (e) => A.play('medal', { level: e && e.level }));
  on('pause', (e) => { A.play('pause'); A.music.duck(!!(e && e.paused)); });
  on('ui:screen', (e) => {
    if (e && e.name === 'menu') { A.music.start('menu'); A.engine.set(0); menuBed(); }
  });
  on('radio:surge', () => { A.play('horn'); A.radio.next(); });

  on('frame', (f) => {
    const G = PG.engine && PG.engine.G;
    if (!G || PG.screen !== 'play') { A.engine.set(0); return; }
    let sp = 0;
    const sh = G.sh, h = ((sh ? sh.startHour : startH) + Math.floor(G.t / 3600)) % 24;
    if (!G.over && !G.paused && (G.mode === 'ride' || G.mode === 'pickup' || G.mode === 'cruise')) {
      sp = sh && sh.speedByHour ? sh.speedByHour[h] / 60 : 0.5;
    }
    A.engine.set(sp, { run: !G.over });
    if (G.over) return;
    A.fast.set(!!G.fast);
    radioLvl(G.mode === 'ride' ? 1 : 0.4);
    A.ambience.set({ night: nightW(h + (G.t % 3600) / 3600), speed: sp, hour: h });
    A.music.setIntensity(Math.min(1, 0.25 + 0.2 * (G.combo || 0) + (G.t > 6000 ? 0.2 : 0)));
    if (G.t >= CD_FROM && !G.paused) {
      cdAcc += f ? f.dt : 0;
      if (!cdOn || cdAcc >= 1) { A.play('countdown'); cdAcc = cdOn ? cdAcc - 1 : 0; cdOn = true; }
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
