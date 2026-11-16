(function (root) {
  const PG = root.PG = root.PG || {};
  const KEY = 'porto-ghost-audio-v1';
  const MAX_VOICES = 8;
  const cfg = { master: 0.8, music: 0.7, sfx: 0.9, muted: false };
  let ctx = null, master, comp, sfxBus, musicBus, duckG, engBus, engGain, engFilt, engO1, engO2;
  let noiseBuf = null, voices = [], btn = null, inited = false;
  let wantMood = null, intensity = 0.2, engWant = 0, engCur = -1;
  let mood = null, moodGain = null, timer = 0, nextT = 0, step = 0;

  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const hz = (m) => 440 * Math.pow(2, (m - 69) / 12);

  function load() {
    try {
      const s = JSON.parse(root.localStorage.getItem(KEY) || 'null');
      if (s) {
        ['master', 'music', 'sfx'].forEach((k) => { if (typeof s[k] === 'number') cfg[k] = clamp(s[k], 0, 1); });
        cfg.muted = !!s.muted;
      }
    } catch (e) { /* storage blocked: keep defaults */ }
  }
  function save() {
    try { root.localStorage.setItem(KEY, JSON.stringify(cfg)); } catch (e) { /* ignore */ }
  }

  function applyGains() {
    if (!ctx) return;
    const t = ctx.currentTime;
    master.gain.setTargetAtTime(cfg.muted ? 0 : cfg.master, t, 0.02);
    sfxBus.gain.setTargetAtTime(cfg.sfx, t, 0.02);
    musicBus.gain.setTargetAtTime(cfg.music * 0.5, t, 0.02);
  }

  function stopTimer() { if (timer) { root.clearInterval(timer); timer = 0; } }

  // Build the whole graph on a context (real, or offline for level tests).
  function attach(c) {
    stopTimer();
    ctx = c; voices = []; mood = null; moodGain = null; engCur = -1;
    master = c.createGain();
    comp = c.createDynamicsCompressor();
    comp.threshold.value = -12; comp.knee.value = 8; comp.ratio.value = 12;
    comp.attack.value = 0.003; comp.release.value = 0.2;
    master.connect(comp); comp.connect(c.destination);
    sfxBus = c.createGain(); sfxBus.connect(master);
    musicBus = c.createGain(); duckG = c.createGain();
    duckG.connect(musicBus); musicBus.connect(master);
    engBus = c.createGain(); engBus.gain.value = 0.6; engBus.connect(master);
    engGain = c.createGain(); engGain.gain.value = 0;
    engFilt = c.createBiquadFilter(); engFilt.type = 'lowpass'; engFilt.frequency.value = 200;
    engO1 = c.createOscillator(); engO1.type = 'sawtooth'; engO1.frequency.value = 45;
    engO2 = c.createOscillator(); engO2.type = 'triangle'; engO2.frequency.value = 90.7;
    engO1.connect(engFilt); engO2.connect(engFilt); engFilt.connect(engGain); engGain.connect(engBus);
    engO1.start(); engO2.start();
    const n = c.sampleRate;
    noiseBuf = c.createBuffer(1, n, n);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    applyGains();
  }

  function unlock() {
    try {
      if (!ctx) {
        const AC = root.AudioContext || root.webkitAudioContext;
        if (!AC) return;
        attach(new AC());
        // iOS: a silent buffer inside the gesture really starts the context
        const b = ctx.createBuffer(1, 1, 22050), s = ctx.createBufferSource();
        s.buffer = b; s.connect(ctx.destination); s.start(0);
        if (wantMood) startMusic(wantMood);
        engineSet(engWant);
      }
      if (ctx.resume && ctx.state === 'suspended') ctx.resume();
    } catch (e) { /* no WebAudio: stay silent */ }
  }

  // ---------- synthesis helpers ----------
  function tone(dest, o) {
    const t = o.t, a = o.a || 0.006, dur = o.dur;
    const os = ctx.createOscillator(), g = ctx.createGain();
    os.type = o.type || 'sine';
    os.frequency.setValueAtTime(o.f, t);
    if (o.f2) os.frequency.exponentialRampToValueAtTime(o.f2, t + dur);
    if (o.det) os.detune.value = o.det;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(o.v, t + a);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    let out = g;
    os.connect(g);
    if (o.lp) {
      const f = ctx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = o.lp;
      g.connect(f); out = f;
    }
    out.connect(dest);
    os.start(t); os.stop(t + dur + 0.03);
  }
  function noise(dest, o) {
    const t = o.t, a = o.a || 0.004, dur = o.dur;
    const s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    s.buffer = noiseBuf;
    f.type = o.ftype || 'bandpass'; f.Q.value = o.q || 1;
    f.frequency.setValueAtTime(o.f, t);
    if (o.f2) f.frequency.exponentialRampToValueAtTime(o.f2, t + dur);
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(o.v, t + a);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.connect(f); f.connect(g); g.connect(dest);
    s.start(t, Math.random() * 0.5); s.stop(t + dur + 0.03);
  }
  // bell-like note: sine plus a quiet inharmonic partial
  function bell(d, t, f, dur, v) {
    tone(d, { t, f, dur, v });
    tone(d, { t, f: f * 2.01, dur: dur * 0.6, v: v * 0.3 });
  }
  const seq = (d, t, fs, gap, dur, v, type, lp) =>
    fs.forEach((f, i) => tone(d, { t: t + i * gap, f, dur, v, type: type || 'triangle', lp }));

  // ---------- sounds: [duration s, fn(dest, t, opts)] ----------
  const S = {
    click: [0.08, (d, t) => tone(d, { t, f: 1300, f2: 800, dur: 0.05, v: 0.4, type: 'triangle' })],
    book: [0.3, (d, t) => {
      tone(d, { t, f: 660, dur: 0.1, v: 0.22, type: 'triangle' });
      tone(d, { t: t + 0.09, f: 880, dur: 0.16, v: 0.22, type: 'triangle' });
    }],
    pickup: [0.45, (d, t) => seq(d, t, [523, 659, 784], 0.09, 0.2, 0.22, 'triangle')],
    dropoff: [0.7, (d, t) => { bell(d, t, 784, 0.25, 0.22); bell(d, t + 0.14, 1047, 0.5, 0.22); }],
    coin: [0.4, (d, t) => {
      tone(d, { t, f: 1319, dur: 0.07, v: 0.2, type: 'square', lp: 4000 });
      tone(d, { t: t + 0.06, f: 1976, dur: 0.3, v: 0.2, type: 'square', lp: 4000 });
    }],
    lost: [0.4, (d, t) => tone(d, { t, f: 420, f2: 130, dur: 0.35, v: 0.4, type: 'sawtooth', lp: 900 })],
    steal: [0.4, (d, t) => {
      tone(d, { t, f: 700, f2: 300, dur: 0.18, v: 0.16, type: 'square', lp: 1800 });
      tone(d, { t: t + 0.16, f: 500, f2: 180, dur: 0.22, v: 0.16, type: 'square', lp: 1500 });
      noise(d, { t, f: 3000, f2: 800, dur: 0.3, v: 0.08, q: 2 });
    }],
    combo: [0.5, (d, t, o) => {
      const f = 523 * Math.pow(2, 2 * clamp((o.n || 1) - 1, 0, 8) / 12);
      seq(d, t, [f, f * 1.26, f * 1.5], 0.06, 0.22, 0.2, 'triangle');
    }],
    combo_break: [0.5, (d, t) => seq(d, t, [330, 247, 185], 0.09, 0.22, 0.18, 'sawtooth', 700)],
    rank_up: [0.4, (d, t) => {
      tone(d, { t, f: 440, f2: 880, dur: 0.22, v: 0.2, type: 'triangle' });
      bell(d, t + 0.2, 1175, 0.2, 0.18);
    }],
    rank_down: [0.4, (d, t) => tone(d, { t, f: 440, f2: 220, dur: 0.34, v: 0.4, type: 'sine' })],
    overtake: [0.5, (d, t) => {
      noise(d, { t, f: 400, f2: 3500, dur: 0.3, v: 0.12, q: 1.5 });
      bell(d, t + 0.1, 988, 0.35, 0.2);
    }],
    behind: [0.5, (d, t) => {
      tone(d, { t, f: 330, dur: 0.14, v: 0.2, type: 'triangle' });
      tone(d, { t: t + 0.18, f: 262, dur: 0.25, v: 0.2, type: 'triangle' });
    }],
    shift_start: [1.0, (d, t) => seq(d, t, [392, 523, 659, 784], 0.13, 0.35, 0.2, 'triangle', 3000)],
    countdown: [0.12, (d, t) => tone(d, { t, f: 880, dur: 0.09, v: 0.4, type: 'sine' })],
    shift_end: [1.6, (d, t) => {
      [784, 659, 523, 392].forEach((f, i) => bell(d, t + i * 0.18, f, 0.9, 0.18));
    }],
    medal: [2.6, (d, t, o) => {
      const L = clamp(Math.round(o.level || 0), 0, 4);
      const sc = [523, 587, 659, 784, 880, 1047, 1319];
      for (let i = 0; i <= 1 + L; i++) bell(d, t + i * 0.1, sc[i], 0.4, 0.13);
      const t2 = t + (2 + L) * 0.1;
      [523, 659, 784, 1047].slice(0, 2 + (L > 1 ? 2 : 0)).forEach((f) =>
        tone(d, { t: t2, f, dur: 0.5 + L * 0.3, v: 0.08, type: 'triangle', lp: 3500 }));
      if (L >= 4) for (let i = 0; i < 6; i++) tone(d, { t: t2 + i * 0.08, f: 1568 * (1 + i * 0.12), dur: 0.5, v: 0.06 });
    }],
    horn: [0.5, (d, t) => {
      tone(d, { t, f: 311, dur: 0.4, v: 0.2, type: 'sawtooth', lp: 1200, a: 0.02 });
      tone(d, { t, f: 392, dur: 0.4, v: 0.2, type: 'sawtooth', lp: 1200, a: 0.02 });
    }],
    denied: [0.3, (d, t) => {
      tone(d, { t, f: 160, dur: 0.1, v: 0.2, type: 'square', lp: 600 });
      tone(d, { t: t + 0.13, f: 130, dur: 0.14, v: 0.2, type: 'square', lp: 600 });
    }],
    whoosh: [0.35, (d, t) => noise(d, { t, f: 300, f2: 3200, dur: 0.28, v: 0.5, q: 1.2, a: 0.08 })],
    pause: [0.2, (d, t) => tone(d, { t, f: 620, f2: 400, dur: 0.13, v: 0.4, type: 'triangle' })]
  };

  function play(name, opts) {
    const def = S[name];
    if (!def || !ctx || cfg.muted || (ctx.state === 'suspended' && !ctx.startRendering)) return;
    try {
      opts = opts || {};
      const now = ctx.currentTime, t = now + 0.01 + (opts.delay || 0);
      voices = voices.filter((v) => v.end > now);
      while (voices.length >= MAX_VOICES) voices.shift().g.gain.setTargetAtTime(0, now, 0.01);
      const g = ctx.createGain();
      g.connect(sfxBus);
      def[1](g, t, opts);
      voices.push({ g, end: t + def[0] });
    } catch (e) { /* never break the game over a sound */ }
  }

  // ---------- music ----------
  // chords as midi notes, 4 bars of 16 steps; bass = first note - 12
  const MOODS = {
    menu: { bpm: 90, ch: [[57, 60, 64], [53, 57, 60], [48, 55, 60, 64], [55, 59, 62, 67]], arp: [0, 8], pad: 0.05, lp: 800 },
    day: { bpm: 104, ch: [[60, 64, 67], [55, 62, 67], [57, 64, 69], [53, 60, 65, 69]], arp: [0, 4, 8, 12], pad: 0.04, lp: 1400 },
    night: { bpm: 96, ch: [[50, 57, 60, 65], [46, 58, 62, 65], [55, 58, 62, 65], [45, 57, 61, 67]], arp: [0, 6, 10], pad: 0.045, lp: 700 }
  };

  function scheduleStep(m, g, t, s) {
    const I = intensity, pos = s % 16, ch = m.ch[(s >> 4) % 4], sd = 60 / m.bpm / 4;
    if (pos === 0) {
      ch.forEach((n, i) => {
        tone(g, { t, f: hz(n), dur: sd * 16, v: m.pad, type: 'triangle', a: 0.5, lp: m.lp, det: i % 2 ? 6 : -6 });
      });
    }
    if (pos === 0 || pos === 8) tone(g, { t, f: hz(ch[0] - 12), dur: sd * 6, v: 0.2, a: 0.01 });
    if (m === MOODS.day && pos === 6) tone(g, { t, f: hz(ch[0] - 12), dur: sd * 3, v: 0.14, a: 0.01 });
    if (m.arp.indexOf(pos) >= 0) {
      const k = ((s >> 2) + pos) % ch.length;
      tone(g, { t, f: hz(ch[k] + 12), dur: sd * 3, v: 0.07, type: 'triangle', a: 0.004 });
    }
    // percussion: always very soft, more layers join with intensity
    if ((pos === 0 || pos === 8) && (I > 0.3 || pos === 0)) tone(g, { t, f: 130, f2: 45, dur: 0.14, v: 0.12 + 0.2 * I, a: 0.003 });
    if ((pos === 4 || pos === 12) && I > 0.5) noise(g, { t, f: 1600, dur: 0.1, v: 0.06 + 0.08 * I, q: 0.8 });
    if ((pos % 4 === 2 && I > 0.15) || (pos % 2 === 1 && I > 0.7) || pos % 8 === 4) {
      noise(g, { t, f: 7000, dur: 0.03, v: 0.025 + 0.05 * I, ftype: 'highpass' });
    }
  }

  function tick() {
    if (!ctx || !mood) return;
    const now = ctx.currentTime, m = MOODS[mood];
    if (nextT < now - 0.1) nextT = now + 0.05; // tab was throttled: resync, no burst
    while (nextT < now + 0.25) {
      scheduleStep(m, moodGain, nextT, step);
      nextT += 60 / m.bpm / 4;
      step = (step + 1) % 64;
    }
  }

  function fadeOut(g, tc) {
    g.gain.setTargetAtTime(0, ctx.currentTime, tc);
    root.setTimeout(() => { try { g.disconnect(); } catch (e) { /* gone */ } }, tc * 8000);
  }

  function startMusic(name) {
    if (!MOODS[name]) return;
    wantMood = name;
    if (!ctx || mood === name) return;
    try {
      if (moodGain) fadeOut(moodGain, 0.5);
      moodGain = ctx.createGain();
      moodGain.gain.value = 0;
      moodGain.gain.setTargetAtTime(1, ctx.currentTime, 0.5);
      moodGain.connect(duckG);
      mood = name; step = 0; nextT = ctx.currentTime + 0.05;
      if (!timer) timer = root.setInterval(tick, 50);
      tick();
    } catch (e) { /* ignore */ }
  }
  function stopMusic() {
    wantMood = null;
    if (!ctx || !mood) return;
    fadeOut(moodGain, 0.4);
    mood = null; moodGain = null; stopTimer();
  }
  function setIntensity(v) { intensity = clamp(+v || 0, 0, 1); }
  function duck(on) {
    if (ctx) duckG.gain.setTargetAtTime(on ? 0.35 : 1, ctx.currentTime, 0.1);
  }

  function engineSet(v) {
    engWant = clamp(+v || 0, 0, 1);
    if (!ctx || Math.abs(engWant - engCur) < 0.01) return;
    engCur = engWant;
    const t = ctx.currentTime, s = engWant;
    engO1.frequency.setTargetAtTime(42 + s * 70, t, 0.15);
    engO2.frequency.setTargetAtTime(84.7 + s * 140, t, 0.15);
    engFilt.frequency.setTargetAtTime(160 + s * 500, t, 0.15);
    engGain.gain.setTargetAtTime(s > 0 ? 0.05 + 0.07 * s : 0, t, s > 0 ? 0.2 : 0.1);
  }

  function setMuted(m) {
    cfg.muted = !!m; save(); applyGains();
    if (btn) btn.textContent = cfg.muted ? '🔇' : '🔊';
  }
  function setVolume(v) {
    ['master', 'music', 'sfx'].forEach((k) => { if (v && typeof v[k] === 'number') cfg[k] = clamp(v[k], 0, 1); });
    save(); applyGains();
  }

  function init() {
    if (inited) return;
    inited = true;
    load();
    const host = root.document && (root.document.getElementById('hud-extra') || root.document.getElementById('hud'));
    if (!host) return;
    btn = root.document.createElement('button');
    btn.type = 'button'; btn.className = 'audio-mute'; btn.id = 'audio-mute';
    btn.setAttribute('aria-label', 'Звук');
    btn.textContent = cfg.muted ? '🔇' : '🔊';
    btn.addEventListener('click', () => { unlock(); setMuted(!cfg.muted); });
    host.appendChild(btn);
  }

  PG.audio = {
    init, unlock, play,
    music: { start: startMusic, setIntensity, stop: stopMusic, duck },
    engine: { set: engineSet },
    setVolume, setMuted,
    getSettings: () => ({ master: cfg.master, music: cfg.music, sfx: cfg.sfx, muted: cfg.muted }),
    names: Object.keys(S),
    _attach: attach // level tests with an OfflineAudioContext
  };
  load();
})(typeof window !== 'undefined' ? window : globalThis);
