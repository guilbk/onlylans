(function (root) {
  const PG = root.PG = root.PG || {};
  const KEY = 'porto-ghost-audio-v1';
  const MAX_VOICES = 8;
  const cfg = { master: 0.8, music: 0.7, sfx: 0.9, amb: 0.8, muted: false };
  let ctx = null, master, comp, sfxBus, musicBus, duckG, engBus, engGain, engFilt, engO1, engO2, engO3, engNg, engLfoG, engDuck;
  let ambBus, ambDuck, ambOut, an = null, ambTimer = 0, ducked = false, fastOn = false;
  let engRun = false, engRunCur = false, engFastCur = false;
  const amb = { on: false, day: 1, night: 0, rain: 0, traffic: 0.6, speed: 0, hour: -1, fast: false };
  const nx = { car: 0, bird: 0, far: 0, drop: 0, thunder: 0 };
  let noiseBuf = null, voices = [], btn = null, inited = false;
  let wantMood = null, intensity = 0.2, engWant = 0, engCur = -1;
  let mood = null, moodGain = null, timer = 0, nextT = 0, step = 0;

  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const hz = (m) => 440 * Math.pow(2, (m - 69) / 12);

  function load() {
    try {
      const s = JSON.parse(root.localStorage.getItem(KEY) || 'null');
      if (s) {
        ['master', 'music', 'sfx', 'amb'].forEach((k) => { if (typeof s[k] === 'number') cfg[k] = clamp(s[k], 0, 1); });
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
    ambBus.gain.setTargetAtTime(cfg.amb * 0.3, t, 0.02);
  }

  function stopTimer() { if (timer) { root.clearInterval(timer); timer = 0; } }

  // Build the whole graph on a context (real, or offline for level tests).
  function attach(c) {
    stopTimer();
    if (ambTimer) { root.clearInterval(ambTimer); ambTimer = 0; }
    ctx = c; voices = []; mood = null; moodGain = null; engCur = -1;
    master = c.createGain();
    comp = c.createDynamicsCompressor();
    comp.threshold.value = -12; comp.knee.value = 8; comp.ratio.value = 12;
    comp.attack.value = 0.003; comp.release.value = 0.2;
    master.connect(comp); comp.connect(c.destination);
    sfxBus = c.createGain(); sfxBus.connect(master);
    musicBus = c.createGain(); duckG = c.createGain();
    duckG.connect(musicBus); musicBus.connect(master);
    const n = c.sampleRate * 3;
    noiseBuf = c.createBuffer(1, n, c.sampleRate);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    engDuck = c.createGain(); engDuck.connect(master);
    engBus = c.createGain(); engBus.gain.value = 0.6; engBus.connect(engDuck);
    engGain = c.createGain(); engGain.gain.value = 0;
    engFilt = c.createBiquadFilter(); engFilt.type = 'lowpass'; engFilt.frequency.value = 200;
    engO1 = c.createOscillator(); engO1.type = 'sawtooth'; engO1.frequency.value = 45;
    engO2 = c.createOscillator(); engO2.type = 'triangle'; engO2.frequency.value = 90.7;
    engO3 = c.createOscillator(); engO3.type = 'square'; engO3.frequency.value = 135;
    const h3 = c.createGain(); h3.gain.value = 0.18;
    const nf = c.createBiquadFilter(); nf.type = 'bandpass'; nf.frequency.value = 260; nf.Q.value = 0.8;
    engNg = c.createGain(); engNg.gain.value = 0;
    const ns = loop(0.3);
    const lfo = c.createOscillator(); lfo.frequency.value = 5.5;
    engLfoG = c.createGain(); engLfoG.gain.value = 0; // idle lope depth
    lfo.connect(engLfoG); engLfoG.connect(engGain.gain);
    engO1.connect(engFilt); engO2.connect(engFilt); engO3.connect(h3); h3.connect(engFilt);
    ns.connect(nf); nf.connect(engNg); engNg.connect(engFilt);
    engFilt.connect(engGain); engGain.connect(engBus);
    engO1.start(); engO2.start(); engO3.start(); lfo.start();
    // ambience chain: out (fade) -> duck -> bus -> master, under the effects
    ambBus = c.createGain(); ambBus.connect(master);
    ambDuck = c.createGain(); ambDuck.connect(ambBus);
    ambOut = c.createGain(); ambOut.gain.value = 0; ambOut.connect(ambDuck);
    an = null; ducked = false;
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
        engineSet(engWant, { run: engRun });
        if (amb.on) ambSet({});
      }
      if (ctx.resume && ctx.state === 'suspended') ctx.resume();
    } catch (e) { /* no WebAudio: stay silent */ }
  }

  // ---------- synthesis helpers ----------
  function loop(off) { // looping slice of the one shared noise buffer
    const s = ctx.createBufferSource();
    s.buffer = noiseBuf; s.loop = true; s.start(0, off);
    return s;
  }
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
    s.start(t, Math.random() * 2); s.stop(t + dur + 0.03);
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
    speed_up: [0.6, (d, t) => {
      noise(d, { t, f: 300, f2: 4500, dur: 0.5, v: 0.25, q: 1.2, a: 0.1 });
      tone(d, { t, f: 330, f2: 990, dur: 0.45, v: 0.14, type: 'triangle', lp: 3000 });
    }],
    slow_down: [0.6, (d, t) => {
      noise(d, { t, f: 4000, f2: 300, dur: 0.5, v: 0.2, q: 1.2, a: 0.05 });
      tone(d, { t, f: 880, f2: 300, dur: 0.45, v: 0.12, type: 'triangle', lp: 2500 });
    }],
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
    const I = clamp(intensity + (fastOn ? 0.25 : 0), 0, 1), pos = s % 16, ch = m.ch[(s >> 4) % 4], sd = 60 / m.bpm / 4;
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
    if (fastOn && pos % 2 === 0) tone(g, { t, f: pos % 4 ? 1000 : 1450, dur: 0.035, v: 0.05, a: 0.002 });
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
    ducked = !!on;
    if (!ctx) return;
    const t = ctx.currentTime;
    duckG.gain.setTargetAtTime(on ? 0.35 : 1, t, 0.1);
    ambDuck.gain.setTargetAtTime(on ? 0.2 : 1, t, 0.15);
    engDuck.gain.setTargetAtTime(on ? 0.2 : 1, t, 0.15);
  }

  // o.run: a shift is running, so speed 0 idles instead of going silent
  function engineSet(v, o) {
    engWant = clamp(+v || 0, 0, 1);
    engRun = !!(o && o.run);
    if (!ctx || (Math.abs(engWant - engCur) < 0.01 && engRun === engRunCur && fastOn === engFastCur)) return;
    const t = ctx.currentTime, s = engWant, k = fastOn ? 1.33 : 1;
    const lvl = (s > 0 ? 0.05 + 0.07 * s : engRun ? 0.03 : 0) * (fastOn ? 1.15 : 1);
    const f0 = (38 + s * 62) * k;
    const shift = engCur >= 0 && Math.abs(s - engCur) > 0.2;
    engCur = s; engRunCur = engRun; engFastCur = fastOn;
    engO1.frequency.setTargetAtTime(f0, t, 0.15);
    engO2.frequency.setTargetAtTime(f0 * 2.02, t, 0.15);
    engO3.frequency.setTargetAtTime(f0 * 3.01, t, 0.15);
    engFilt.frequency.setTargetAtTime((150 + s * 520) * (fastOn ? 1.2 : 1), t, 0.15);
    engNg.gain.setTargetAtTime(s > 0 ? 0.25 + 0.6 * s : 0.15, t, 0.2);
    engLfoG.gain.setTargetAtTime(s < 0.02 && engRun ? lvl * 0.35 : 0, t, 0.2);
    const tc = s > 0 || engRun ? 0.2 : 0.1;
    if (shift && lvl > 0) { // gear shift: short dip, then back
      engGain.gain.setTargetAtTime(lvl * 0.35, t, 0.02);
      engGain.gain.setTargetAtTime(lvl, t + 0.12, 0.07);
    } else engGain.gain.setTargetAtTime(lvl, t, tc);
  }

  // ---------- fast mode ----------
  function setFast(on) {
    on = !!on;
    if (on === fastOn) return;
    fastOn = on; amb.fast = on;
    play(on ? 'speed_up' : 'slow_down');
    engineSet(engWant, { run: engRun });
    ambApply();
  }

  // ---------- ambience ----------
  function ambApply() {
    if (!ctx || !an) return;
    const t = ctx.currentTime, a = amb, d = a.day, n = a.night, dr = a.speed, k = a.fast ? 1.25 : 1;
    const tc = 0.8; // slow crossfade, never a click
    an.rum.gain.setTargetAtTime(4 * (0.4 + 0.6 * dr) * (0.7 + 0.3 * n), t, tc);
    an.hiss.gain.setTargetAtTime(0.16 * a.traffic * (0.3 + 0.7 * dr) * (0.5 + 0.5 * d) * k, t, tc);
    an.tone.frequency.setTargetAtTime(1500 + 5500 * d, t, tc);
    an.rain.gain.setTargetAtTime(0.3 * a.rain, t, tc);
    an.wet.gain.setTargetAtTime(0.25 * a.rain * n, t, tc);
    an.crk.gain.setTargetAtTime(0.03 * n * (1 - a.rain), t, tc);
  }
  function ambBuild() {
    if (an || !ctx) return;
    const c = ctx, N = { srcs: [], oscs: [] };
    N.sum = c.createGain();
    N.tone = c.createBiquadFilter(); N.tone.type = 'lowpass'; N.tone.frequency.value = 5000;
    N.sum.connect(N.tone); N.tone.connect(ambOut);
    N.evt = c.createGain(); N.evt.connect(ambOut); // events bypass the tone filter
    const chain = (off, type, f, q, dest) => {
      const s = loop(off), fl = c.createBiquadFilter(), g = c.createGain();
      fl.type = type; fl.frequency.value = f; fl.Q.value = q; g.gain.value = 0;
      s.connect(fl); fl.connect(g); g.connect(dest); N.srcs.push(s);
      return g;
    };
    N.rum = chain(0.1, 'lowpass', 110, 0.7, N.sum);
    const lfo = c.createOscillator(), lg = c.createGain();
    lfo.frequency.value = 0.11; lg.gain.value = 0.9;
    lfo.connect(lg); lg.connect(N.rum.gain); N.oscs.push(lfo);
    N.hiss = chain(0.9, 'bandpass', 850, 0.4, N.sum);
    N.rain = chain(1.7, 'highpass', 1400, 0.5, N.sum);
    N.wet = chain(2.4, 'bandpass', 2800, 1, N.sum);
    N.crk = c.createGain(); N.crk.gain.value = 0; N.crk.connect(N.evt);
    const pg = c.createGain(), pl = c.createGain(), po = c.createOscillator();
    pg.gain.value = 0.5; pl.gain.value = 0.5; po.frequency.value = 7; // gain swings 0..1: cricket pulses
    po.connect(pl); pl.connect(pg.gain); pg.connect(N.crk); N.oscs.push(po);
    [4300, 4660].forEach((f) => {
      const o = c.createOscillator(); o.frequency.value = f; o.connect(pg); N.oscs.push(o);
    });
    N.oscs.forEach((o) => o.start());
    an = N;
    ambApply();
  }
  function ambTeardown(N) {
    if (!N || amb.on) return;
    if (an === N) an = null;
    N.srcs.forEach((s) => { try { s.stop(); s.disconnect(); } catch (e) { /* gone */ } });
    N.oscs.forEach((o) => { try { o.stop(); o.disconnect(); } catch (e) { /* gone */ } });
    try { N.sum.disconnect(); N.evt.disconnect(); } catch (e) { /* gone */ }
    if (ambTimer) { root.clearInterval(ambTimer); ambTimer = 0; }
  }
  function ambSet(o) {
    o = o || {};
    if (o.night != null) amb.night = clamp(+o.night, 0, 1);
    if (o.day != null) amb.day = clamp(+o.day, 0, 1);
    if (o.night != null && o.day == null) amb.day = 1 - amb.night;
    if (o.day != null && o.night == null) amb.night = 1 - amb.day;
    if (o.rain != null) amb.rain = clamp(+o.rain, 0, 1);
    if (o.traffic != null) amb.traffic = clamp(+o.traffic, 0, 1);
    if (o.speed != null) amb.speed = clamp(+o.speed, 0, 1);
    if (o.hour != null) amb.hour = +o.hour;
    amb.on = true;
    if (!ctx) return;
    ambBuild();
    ambOut.gain.setTargetAtTime(1, ctx.currentTime, 0.8);
    ambApply();
    if (!ambTimer) ambTimer = root.setInterval(() => ambTick(0.3), 100);
  }
  function ambStop() {
    amb.on = false;
    if (!ctx || !an) return;
    const N = an;
    ambOut.gain.setTargetAtTime(0, ctx.currentTime, 0.5);
    root.setTimeout(() => ambTeardown(N), 4000);
  }

  // short random events, scheduled a little ahead; nothing runs while hidden, muted or ducked
  const rnd = (a, b) => a + Math.random() * (b - a);
  function carPass(t) {
    const k = amb.fast ? 1.33 : 1, dur = rnd(1.6, 3.2) / k, dir = Math.random() < 0.5 ? -1 : 1, f0 = rnd(500, 900);
    const s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    const o = ctx.createOscillator(), og = ctx.createGain(), v = rnd(0.25, 0.4);
    s.buffer = noiseBuf; f.type = 'bandpass'; f.Q.value = 1.5;
    f.frequency.setValueAtTime(f0 * 1.3, t); f.frequency.exponentialRampToValueAtTime(f0 * 0.75, t + dur);
    o.type = 'sawtooth'; o.frequency.setValueAtTime(138, t); o.frequency.exponentialRampToValueAtTime(92, t + dur);
    og.gain.value = 0.18;
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(v, t + dur * 0.5); g.gain.linearRampToValueAtTime(0, t + dur);
    s.connect(f); f.connect(g); o.connect(og); og.connect(g);
    let out = g;
    if (ctx.createStereoPanner) {
      const p = ctx.createStereoPanner();
      p.pan.setValueAtTime(-dir * 0.9, t); p.pan.linearRampToValueAtTime(dir * 0.9, t + dur);
      g.connect(p); out = p;
    }
    out.connect(an.evt);
    s.start(t, rnd(0, 2)); s.stop(t + dur + 0.05); o.start(t); o.stop(t + dur + 0.05);
  }
  function chirp(t) {
    const n = 2 + Math.floor(Math.random() * 3), f = rnd(2600, 4200);
    for (let i = 0; i < n; i++) {
      tone(an.evt, { t: t + i * 0.11, f: f * (1 + 0.1 * i), f2: f * rnd(0.8, 1.3), dur: 0.08, v: 0.012, a: 0.01 });
    }
  }
  function farSound(t) { // a distant siren or a lone horn, very quiet
    if (Math.random() < 0.5) {
      for (let i = 0; i < 4; i++) {
        tone(an.evt, { t: t + i * 0.9, f: 620, f2: 830, dur: 0.85, v: 0.02, type: 'triangle', lp: 900, a: 0.4 });
      }
    } else {
      tone(an.evt, { t, f: 311, dur: 0.5, v: 0.03, type: 'sawtooth', lp: 500, a: 0.03 });
      tone(an.evt, { t, f: 392, dur: 0.5, v: 0.03, type: 'sawtooth', lp: 500, a: 0.03 });
    }
  }
  function ambTick(look) {
    if (!ctx || !an || !amb.on || cfg.muted || ducked) return;
    if (root.document && root.document.hidden) return;
    try {
      const now = ctx.currentTime, hz = now + look, a = amb, k = a.fast ? 1.33 : 1;
      const rush = (a.hour >= 8 && a.hour < 10) || (a.hour >= 17 && a.hour < 19);
      if (nx.car < now - 0.5) nx.car = now + rnd(0.5, 3);
      const rate = (3 * a.day + 1 * a.night) * (rush ? 1.7 : 1) * (0.3 + a.traffic) * (0.6 + 0.4 * a.speed) * k; // cars per 10 s
      while (nx.car < hz) { carPass(nx.car); nx.car += (10 / Math.max(rate, 0.2)) * rnd(0.6, 1.4); }
      if (nx.bird < now - 0.5) nx.bird = now + rnd(2, 8);
      while (nx.bird < hz) {
        if (a.day > 0.5 && a.rain < 0.3) chirp(nx.bird);
        nx.bird += rnd(6, 14);
      }
      if (nx.far < now - 0.5) nx.far = now + rnd(10, 30);
      while (nx.far < hz) {
        if (a.night > 0.5) farSound(nx.far);
        nx.far += rnd(25, 60);
      }
      if (a.rain > 0.05) {
        if (nx.drop < now - 0.5) nx.drop = now;
        while (nx.drop < hz) {
          noise(an.evt, { t: nx.drop, f: rnd(3500, 7500), dur: 0.02, v: 0.05 * a.rain, ftype: 'highpass', a: 0.002 });
          nx.drop += 1 / (14 * a.rain) * rnd(0.5, 1.5);
        }
      }
      if (nx.thunder < now - 0.5) nx.thunder = now + rnd(20, 50);
      while (nx.thunder < hz) {
        if (a.rain > 0.6) noise(an.evt, { t: nx.thunder, f: 140, f2: 50, dur: rnd(3, 4.5), v: 0.5, q: 0.7, a: 0.5, ftype: 'lowpass' });
        nx.thunder += rnd(40, 90);
      }
    } catch (e) { /* never break the game over a sound */ }
  }

  function setMuted(m) {
    cfg.muted = !!m; save(); applyGains();
    if (btn) btn.textContent = cfg.muted ? '🔇' : '🔊';
  }
  function setVolume(v) {
    ['master', 'music', 'sfx', 'amb'].forEach((k) => { if (v && typeof v[k] === 'number') cfg[k] = clamp(v[k], 0, 1); });
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
    ambience: { set: ambSet, stop: ambStop, _tick: ambTick },
    fast: { set: setFast },
    setVolume, setMuted,
    getSettings: () => ({ master: cfg.master, music: cfg.music, sfx: cfg.sfx, amb: cfg.amb, muted: cfg.muted }),
    names: Object.keys(S),
    _attach: attach // level tests with an OfflineAudioContext
  };
  load();
})(typeof window !== 'undefined' ? window : globalThis);
