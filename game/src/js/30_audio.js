(function (root) {
  const PG = root.PG = root.PG || {};
  const KEY = 'porto-ghost-audio-v1';
  const MAX_VOICES = 8;
  const cfg = { master: 0.8, music: 0.7, sfx: 0.9, amb: 0.8, muted: false };
  let ctx = null, master, comp, sfxBus, musicBus, duckG, engBus, engGain, engFilt, engO1, engO2, engO3, engNg, engLfoG, engDuck;
  let ambBus, ambDuck, ambOut, an = null, ambTimer = 0, ducked = false, fastOn = false;
  let engRun = false, engRunCur = false, engFastCur = false;
  const amb = { on: false, day: 1, night: 0, rain: 0, traffic: 0.6, speed: 0, hour: -1, fast: false };
  const nx = { car: 0, bird: 0, far: 0, drop: 0, thunder: 0, ind: 0 };
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
    ambBus.gain.setTargetAtTime(cfg.amb * 0.11, t, 0.02);
  }

  function stopTimer() { if (timer) { root.clearInterval(timer); timer = 0; } }

  // Build the whole graph on a context (real, or offline for level tests).
  function attach(c) {
    stopTimer();
    if (ambTimer) { root.clearInterval(ambTimer); ambTimer = 0; }
    ctx = c; voices = []; mood = null; moodGain = null; engCur = -1;
    rb = null; rOut = null; rd.stIn = null; rd.cur = null;
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
    engBus = c.createGain(); engBus.gain.value = 0.3; engBus.connect(engDuck);
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

  // realistic cues: door thunk, taximeter click, coin drop, phone ping, tyre squeal
  const thunk = (d, t, v) => {
    noise(d, { t, f: 220, dur: 0.12, v: v * 1.6, q: 0.7, ftype: 'lowpass', a: 0.002 });
    tone(d, { t, f: 95, f2: 55, dur: 0.12, v, a: 0.002 });
  };
  const meter = (d, t, v) => { // mechanical click-clack
    noise(d, { t, f: 2600, dur: 0.012, v: v * 1.2, q: 2, a: 0.001 });
    noise(d, { t: t + 0.03, f: 1500, dur: 0.015, v, q: 2, a: 0.001 });
  };
  const ping = (d, t, f, v) => { // soft phone notification
    tone(d, { t, f, dur: 0.22, v, lp: 3000, a: 0.008 });
    tone(d, { t, f: f * 2.76, dur: 0.07, v: v * 0.15, a: 0.004 });
  };
  const coindrop = (d, t, v) => [0, 0.09, 0.15, 0.19].forEach((o, i) => {
    tone(d, { t: t + o, f: 3100 + i * 230, dur: 0.12, v: v * (1 - i * 0.2), a: 0.001 });
    tone(d, { t: t + o, f: 5200 + i * 300, dur: 0.07, v: v * 0.4, a: 0.001 });
  });
  const felt = (d, t, f, dur, v) => { // muted piano-like note
    tone(d, { t, f, dur, v, lp: 2200, a: 0.004 });
    tone(d, { t, f: f * 2, dur: dur * 0.4, v: v * 0.25, a: 0.003 });
  };

  // ---------- sounds: [duration s, fn(dest, t, opts)] ----------
  const S = {
    click: [0.08, (d, t) => noise(d, { t, f: 2200, dur: 0.02, v: 0.35, q: 1.5, a: 0.001 })],
    book: [0.45, (d, t) => { ping(d, t, 988, 0.1); ping(d, t + 0.13, 1319, 0.09); }],
    pickup: [0.5, (d, t) => { thunk(d, t, 0.22); meter(d, t + 0.25, 0.12); }],
    dropoff: [0.7, (d, t) => { thunk(d, t, 0.2); meter(d, t + 0.18, 0.1); meter(d, t + 0.3, 0.1); }],
    coin: [0.45, (d, t) => coindrop(d, t, 0.09)],
    lost: [0.4, (d, t) => tone(d, { t, f: 260, f2: 150, dur: 0.3, v: 0.25, lp: 700, a: 0.01 })],
    steal: [0.7, (d, t) => {
      noise(d, { t, f: 1700, f2: 1300, dur: 0.5, v: 0.22, q: 6, a: 0.06 }); // tyre squeal
      tone(d, { t: t + 0.3, f: 392, dur: 0.25, v: 0.12, type: 'sawtooth', lp: 1100, a: 0.02 });
    }],
    combo: [0.5, (d, t, o) => {
      const n = 2 + Math.min(4, o.n || 1);
      for (let i = 0; i < n; i++) meter(d, t + i * (0.09 - Math.min(n, 6) * 0.006), 0.1);
    }],
    combo_break: [0.4, (d, t) => thunk(d, t, 0.12)],
    rank_up: [0.4, (d, t) => { felt(d, t, 659, 0.25, 0.14); felt(d, t + 0.12, 880, 0.3, 0.14); }],
    rank_down: [0.4, (d, t) => { felt(d, t, 440, 0.25, 0.14); felt(d, t + 0.12, 330, 0.3, 0.14); }],
    overtake: [0.6, (d, t) => noise(d, { t, f: 500, f2: 2200, dur: 0.5, v: 0.25, q: 0.8, a: 0.2 })],
    behind: [0.4, (d, t) => noise(d, { t, f: 1800, f2: 400, dur: 0.35, v: 0.18, q: 0.8, a: 0.1 })],
    shift_start: [1.2, (d, t) => {
      thunk(d, t, 0.22);
      tone(d, { t: t + 0.4, f: 38, f2: 62, dur: 0.7, v: 0.2, type: 'sawtooth', lp: 220, a: 0.2 }); // engine turns over
    }],
    countdown: [0.12, (d, t) => noise(d, { t, f: 900, dur: 0.04, v: 0.4, q: 3, a: 0.001 })],
    shift_end: [1.2, (d, t) => { thunk(d, t, 0.2); felt(d, t + 0.35, 523, 0.8, 0.12); felt(d, t + 0.35, 784, 0.8, 0.08); }],
    medal: [1.6, (d, t, o) => { // short, tasteful stinger: 2..4 soft notes
      const L = clamp(Math.round(o.level || 0), 0, 4), sc = [523, 659, 784, 1047];
      for (let i = 0; i < 2 + (L > 1 ? 1 : 0) + (L > 3 ? 1 : 0); i++) felt(d, t + i * 0.16, sc[i], 0.7, 0.1);
    }],
    horn: [0.5, (d, t) => {
      tone(d, { t, f: 400, dur: 0.4, v: 0.14, type: 'sawtooth', lp: 1300, a: 0.015 });
      tone(d, { t, f: 500, dur: 0.4, v: 0.14, type: 'sawtooth', lp: 1300, a: 0.015 });
    }],
    denied: [0.3, (d, t) => { thunk(d, t, 0.1); thunk(d, t + 0.12, 0.1); }],
    whoosh: [0.5, (d, t) => noise(d, { t, f: 400, f2: 1500, dur: 0.45, v: 0.3, q: 0.8, a: 0.15 })],
    indicator: [1.5, (d, t) => { for (let i = 0; i < 4; i++) { noise(d, { t: t + i * 0.34, f: 1800, dur: 0.01, v: 0.25, q: 3, a: 0.001 }); noise(d, { t: t + i * 0.34 + 0.17, f: 1100, dur: 0.01, v: 0.2, q: 3, a: 0.001 }); } }],
    speed_up: [0.6, (d, t) => noise(d, { t, f: 300, f2: 3500, dur: 0.5, v: 0.22, q: 0.8, a: 0.15 })],
    slow_down: [0.6, (d, t) => noise(d, { t, f: 3000, f2: 300, dur: 0.5, v: 0.2, q: 0.8, a: 0.05 })],
    pause: [0.2, (d, t) => noise(d, { t, f: 1600, dur: 0.025, v: 0.3, q: 2, a: 0.001 })]
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

  // ---------- radio (the only music): synthesized car-radio stations ----------
  // each station loops one chord progression and re-arranges it every four bars
  const rnd = (a, b) => a + Math.random() * (b - a);
  function ep(d, t, f, dur, v) { // soft electric piano
    tone(d, { t, f, dur, v, a: 0.004 });
    tone(d, { t, f: f * 2, dur: dur * 0.5, v: v * 0.35, a: 0.003 });
    tone(d, { t, f: f * 4.01, dur: 0.08, v: v * 0.1, a: 0.002 });
  }
  function pluck(d, t, f, dur, v) { // nylon-string pluck
    tone(d, { t, f, dur, v, type: 'triangle', lp: 2200, a: 0.002 });
    tone(d, { t, f: f * 2, dur: dur * 0.4, v: v * 0.4, a: 0.002 });
    noise(d, { t, f: 3000, dur: 0.012, v: v * 0.3, q: 1 });
  }
  const kick = (d, t, v) => tone(d, { t, f: 120, f2: 42, dur: 0.16, v, a: 0.002 });
  const snare = (d, t, v) => { noise(d, { t, f: 1900, dur: 0.14, v, q: 0.7, a: 0.002 }); tone(d, { t, f: 190, f2: 140, dur: 0.08, v: v * 0.4 }); };
  const brush = (d, t, v) => noise(d, { t, f: 5000, dur: 0.18, v, q: 0.5, a: 0.03, ftype: 'highpass' });
  const hat = (d, t, v) => noise(d, { t, f: 8000, dur: 0.03, v, ftype: 'highpass' });
  const bass = (d, t, f, dur, v) => {
    tone(d, { t, f, dur, v, a: 0.01 });
    tone(d, { t, f: f * 2, dur: dur * 0.6, v: v * 0.25, type: 'triangle', lp: 500, a: 0.01 });
  };
  const padn = (d, t, ns, dur, v, lp) => ns.forEach((n, i) =>
    tone(d, { t, f: hz(n), dur, v, type: 'triangle', a: dur * 0.3, lp, det: i % 2 ? 5 : -5 }));
  const chord = (d, t, ns, dur, v, fn) => ns.forEach((n, i) => fn(d, t + i * 0.012, hz(n), dur, v));
  const melody = (ns, bar, k) => ns[(bar * 7 + k * 3) % ns.length] + 12 * (1 + ((bar + k) % 2));

  // step functions: (dest, t, pos 0..15, bar, variation 0..3, chord, step length s, intensity, drop-out)
  const ST = {
    lofi: { name: 'Lo-Fi FM', bpm: 88, ch: [[57, 60, 64, 67], [50, 53, 57, 60], [55, 59, 62, 65], [48, 52, 55, 59]],
      fn(d, t, p, bar, v, ch, sd, I, dr) {
        const sw = p % 2 ? sd * 0.35 : 0;
        if (p === 0) chord(d, t, ch, sd * 7, 0.045, ep);
        if (p === 10 && v !== 1) chord(d, t, ch, sd * 3, 0.03, ep);
        if (p === 6 && v === 2) chord(d, t, ch, sd * 2, 0.025, ep);
        if (p === 0) bass(d, t, hz(ch[0] - 12), sd * 5, 0.16);
        if (p === 8 && v > 0) bass(d, t, hz(ch[2] - 24), sd * 4, 0.12);
        if (!dr) {
          if (p === 0 || (p === 10 && v % 2 === 0)) kick(d, t, 0.18);
          if (p === 4 || p === 12) snare(d, t, 0.1);
          if (p % 2 === 0 || I > 0.5) hat(d, t + sw, p % 2 ? 0.012 : 0.02);
        }
        if (v === 2 && (p === 2 || p === 7)) ep(d, t, hz(melody(ch, bar, p)), sd * 3, 0.03);
        if (Math.random() < 0.12) noise(d, { t, f: 5000, dur: 0.004, v: 0.02, ftype: 'highpass' }); // vinyl crackle
      } },
    jazz: { name: 'Smooth FM', bpm: 104, ch: [[50, 53, 57, 60], [43, 47, 50, 53], [48, 52, 55, 59], [45, 49, 52, 55]],
      fn(d, t, p, bar, v, ch, sd, I, dr) {
        const nxt = ST.jazz.ch[(bar + 1) % 4];
        if (p % 4 === 0) { // walking bass
          const n = [ch[0], ch[2], ch[1], nxt[0] + (bar % 2 ? 1 : -1)][p >> 2];
          bass(d, t, hz(n - 12), sd * 3.5, 0.15);
        }
        if (!dr) {
          if ([0, 4, 7, 8, 12, 15].indexOf(p) >= 0) hat(d, t, 0.028);
          if (p === 4 || p === 12) brush(d, t, 0.035);
        }
        if (p === (v ? 6 : 0)) chord(d, t, ch, sd * 3, 0.04, ep);
        if (v > 0 && (p === 0 || p === 10)) tone(d, { t, f: hz(melody(ch, bar, p)), dur: sd * 3, v: 0.05, type: 'triangle', lp: 1800, a: 0.025 });
      } },
    chill: { name: 'Chill 100', bpm: 100, ch: [[53, 57, 60, 64], [55, 59, 62, 66], [52, 55, 59, 62], [57, 60, 64, 67]],
      fn(d, t, p, bar, v, ch, sd, I, dr) {
        if (p === 0) padn(d, t, ch, sd * 16, 0.03, 1100);
        if (p % 2 === 0) tone(d, { t, f: hz(ch[(p >> 1) % 4] + 12), dur: sd * 2, v: 0.04, type: 'triangle', lp: 2500, a: 0.004 });
        if (p === 0 || p === 6 || p === 10) bass(d, t, hz(ch[0] - 24), sd * 3, 0.15);
        if (!dr) {
          if (p % 8 === 0 || (v > 0 && p % 4 === 0)) kick(d, t, 0.16);
          if (p === 4 || p === 12) snare(d, t, 0.08);
          if (p % 4 === 2) hat(d, t, 0.025);
        }
      } },
    bossa: { name: 'Rádio Bossa', bpm: 92, ch: [[50, 57, 60, 64], [43, 53, 59, 62], [48, 55, 59, 62], [45, 52, 55, 61]],
      fn(d, t, p, bar, v, ch, sd, I, dr) {
        if (p === 0 || p === 8) bass(d, t, hz(ch[0] - 12), sd * 5, 0.14);
        if (p === 6 || p === 14) bass(d, t, hz(ch[0] - 5), sd * 2, 0.1);
        if (p === 0 || p === 3 || p === 6 || p === 10 || (p === 13 && v !== 1)) chord(d, t, ch, sd * 2.5, 0.035, pluck);
        if (!dr) {
          if (p === 3 || p === 6 || p === 10 || p === 13) noise(d, { t, f: 1500, dur: 0.03, v: 0.03, q: 1.5 });
          hat(d, t, 0.01 + 0.004 * (p % 4 === 0));
        }
        if (v === 2 && (p === 2 || p === 8 || p === 11)) pluck(d, t, hz(melody(ch, bar, p)), sd * 3, 0.04);
      } },
    night: { name: 'Noite FM', bpm: 85, night: 1, ch: [[50, 57, 60, 64], [46, 53, 57, 62], [43, 50, 55, 58], [45, 52, 57, 60]],
      fn(d, t, p, bar, v, ch, sd, I, dr) {
        if (p === 0) padn(d, t, ch, sd * 16, 0.035, 600);
        if (p === 0 || p === 8) bass(d, t, hz(ch[0] - 12), sd * 7, 0.13);
        if (p === 0 && v > 0) ep(d, t, hz(ch[2] + 12), sd * 6, 0.04);
        if (p === 10 && Math.random() < 0.5) ep(d, t, hz(ch[1] + 24), sd * 4, 0.03);
        if (!dr && (p === 4 || p === 12)) brush(d, t, 0.02);
      } }
  };
  const rd = { seed: 1, mood: 'day', order: [], idx: 0, lvl: 0, tuneAt: 0, stIn: null, stFilt: null, cur: null };
  let rb = null, rOut = null, stat = null, statF = null;

  function rdOrder() { // seeded shuffle; day favours the lively ones, night the slow ones
    const night = rd.mood === 'night';
    const ids = night ? ['night', 'lofi', 'bossa', 'jazz', 'chill'] : ['chill', 'lofi', 'bossa', 'jazz'];
    let x = (rd.seed >>> 0) || 1;
    const r = () => { x = (x + 0x6d2b79f5) >>> 0; let y = Math.imul(x ^ (x >>> 15), 1 | x); y = (y + Math.imul(y ^ (y >>> 7), 61 | y)) ^ y; return ((y ^ (y >>> 14)) >>> 0) / 4294967296; };
    const body = night ? ids.slice(1) : ids;
    for (let i = body.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); const q = body[i]; body[i] = body[j]; body[j] = q; }
    rd.order = night ? ['night'].concat(body) : body;
    rd.idx = 0;
  }
  function rdBuild() {
    if (rb || !ctx) return;
    const c = ctx;
    rb = c.createGain();
    const hp = c.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 220;
    const lp = c.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 4800;
    const cm = c.createDynamicsCompressor(); cm.threshold.value = -26; cm.ratio.value = 3; cm.knee.value = 10;
    rOut = c.createGain(); rOut.gain.value = 0;
    rb.connect(hp); hp.connect(lp); lp.connect(cm); cm.connect(rOut); rOut.connect(duckG);
    const s = loop(1.1); statF = c.createBiquadFilter(); statF.type = 'bandpass'; statF.frequency.value = 3000; statF.Q.value = 0.5;
    stat = c.createGain(); stat.gain.value = 0;
    s.connect(statF); statF.connect(stat); stat.connect(rb);
  }
  function tune(instant) {
    if (!ctx || !rb) return;
    const id = rd.order[rd.idx % rd.order.length], now = ctx.currentTime;
    if (rd.cur === id && rd.stIn) return;
    const st = ST[id], tc = instant ? 0.05 : 0.12;
    if (rd.stIn) fadeOut(rd.stGain, tc);
    const g = ctx.createGain(), f = ctx.createBiquadFilter();
    f.type = 'lowpass'; f.frequency.value = 3500; g.gain.value = 0;
    f.connect(g); g.connect(rb);
    const t0 = instant ? now : now + 0.35;
    g.gain.setTargetAtTime(1, t0, 0.08);
    rd.stIn = f; rd.stFilt = f; rd.stGain = g; rd.cur = id; mood = id; moodGain = f;
    step = 0; nextT = t0 + 0.05;
    if (!instant) { // tuning sweep with static between the stations
      statF.frequency.cancelScheduledValues(now);
      statF.frequency.setValueAtTime(500, now); statF.frequency.exponentialRampToValueAtTime(4500, now + 0.7);
      stat.gain.cancelScheduledValues(now);
      stat.gain.setTargetAtTime(0.12, now, 0.05); stat.gain.setTargetAtTime(0.012, now + 0.45, 0.1);
      if (Math.random() < 0.35) { // news pips or a short station id
        const k = 880 * Math.pow(2, Math.floor(Math.random() * 4) / 12);
        [0, 0.16, 0.32].forEach((o) => tone(rb, { t: now + 1.4 + o, f: k, dur: 0.07, v: 0.04, a: 0.004 }));
      }
    }
    rd.tuneAt = now + (instant ? 0 : 0.5) + rnd(60, 120) / (fastOn ? 1.6 : 1);
    if (!timer) timer = root.setInterval(() => rdTick(0.25), 50);
  }
  function rdTick(look) {
    if (!ctx || !mood || rd.lvl < 0.01 || cfg.muted) return;
    if (root.document && root.document.hidden) return;
    const now = ctx.currentTime, st = ST[mood], k = fastOn ? 1.12 : 1;
    if (now > rd.tuneAt) { rd.idx++; tune(false); return; }
    if (nextT < now - 0.1) nextT = now + 0.05; // tab was throttled: resync, no burst
    const sd = 60 / st.bpm / 4 / k, I = clamp(intensity, 0, 1);
    while (nextT < now + look) {
      const p = step % 16, bar = step >> 4, v = (bar >> 2) % 4, dr = v === 3 && bar % 4 === 3;
      if (p === 0) { // filter sweep and brightness per section
        const f = ([3200, 4800, 2600, 5500][v]) * (fastOn ? 1.3 : 1) * (bar % 4 === 3 && v % 2 ? 0.3 : 1);
        rd.stFilt.frequency.setTargetAtTime(f, nextT, 0.4);
      }
      try { st.fn(moodGain, nextT, p, bar, v, st.ch[bar % 4], sd, I, dr); } catch (e) { /* ignore */ }
      nextT += sd;
      step = (step + 1) % 256;
    }
  }
  function fadeOut(g, tc) {
    g.gain.setTargetAtTime(0, ctx.currentTime, tc);
    root.setTimeout(() => { try { g.disconnect(); } catch (e) { /* gone */ } }, tc * 8000 + 500);
  }
  function rdLevel(l) {
    rd.lvl = clamp(+l || 0, 0, 1);
    if (!ctx || !rb) return;
    if (rd.lvl > 0 && !mood) tune(true);
    rOut.gain.setTargetAtTime(rd.lvl, ctx.currentTime, 0.5);
    if (rd.lvl > 0) stat.gain.setTargetAtTime(0.012, ctx.currentTime, 0.3);
  }
  function rdMood(name) {
    const m = name === 'night' ? 'night' : 'day';
    if (m === rd.mood && rd.order.length) return;
    rd.mood = m; rdOrder();
    if (ctx && rb && mood) { rd.cur = null; tune(false); }
  }

  function startMusic(name) {
    wantMood = name;
    if (name === 'menu') { rdLevel(0); return; } // no tune in the menu
    rdMood(name);
    if (!ctx) { rd.lvl = rd.lvl || 1; return; }
    try { rdBuild(); rdLevel(rd.lvl || 1); } catch (e) { /* ignore */ }
  }
  function stopMusic() {
    wantMood = null; rd.lvl = 0;
    if (ctx && rOut) rOut.gain.setTargetAtTime(0, ctx.currentTime, 0.4);
  }
  function setIntensity(v) { intensity = clamp(+v || 0, 0, 1); }
  const radio = {
    on: (l) => { rdMood(rd.mood); if (ctx) rdBuild(); rdLevel(l == null ? 1 : l); },
    off: () => rdLevel(0),
    level: rdLevel,
    next: () => { rd.idx++; tune(false); },
    station: () => (rd.cur ? { id: rd.cur, name: ST[rd.cur].name } : null),
    stations: () => Object.keys(ST).map((k) => ({ id: k, name: ST[k].name, night: !!ST[k].night })),
    seed: (n) => { rd.seed = (+n >>> 0) || 1; rd.order = []; rdOrder(); },
    _tick: rdTick
  };
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
    an.rain.gain.setTargetAtTime(0.22 * a.rain, t, tc);
    an.rbody.gain.setTargetAtTime(0.25 * a.rain, t, tc);
    an.wind.gain.setTargetAtTime(0.5 * dr * dr * k, t, tc);
    an.wash.gain.setTargetAtTime(0.9 * a.traffic * (0.5 + 0.5 * d), t, tc);
    an.wet.gain.setTargetAtTime(0.25 * a.rain * n, t, tc);
    an.crk.gain.setTargetAtTime(0.012 * n * (1 - a.rain), t, tc);
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
    N.hiss = chain(0.9, 'bandpass', 600, 0.6, N.sum); // tyre and road
    N.wind = chain(2.9, 'bandpass', 450, 0.3, N.sum);
    N.wash = chain(0.5, 'lowpass', 1500, 0.3, N.sum); // distant city
    N.rbody = chain(2.1, 'bandpass', 1100, 0.5, N.sum);
    N.rain = chain(1.7, 'bandpass', 4500, 0.35, N.sum);
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
  function carPass(t) {
    const k = amb.fast ? 1.33 : 1, dur = rnd(1.6, 3.2) / k, dir = Math.random() < 0.5 ? -1 : 1, f0 = rnd(500, 900);
    const s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    const o = ctx.createOscillator(), og = ctx.createGain(), v = rnd(0.25, 0.4);
    s.buffer = noiseBuf; f.type = 'bandpass'; f.Q.value = 0.8;
    f.frequency.setValueAtTime(f0 * 1.3, t); f.frequency.exponentialRampToValueAtTime(f0 * 0.75, t + dur);
    o.type = 'sawtooth'; o.frequency.setValueAtTime(138, t); o.frequency.exponentialRampToValueAtTime(92, t + dur);
    og.gain.value = 0.03;
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
    const n = 1 + Math.floor(Math.random() * 3), f = rnd(2600, 4200);
    for (let i = 0; i < n; i++) {
      tone(an.evt, { t: t + i * 0.11, f: f * (1 + 0.1 * i), f2: f * rnd(0.8, 1.3), dur: 0.08, v: 0.006, a: 0.012 });
    }
  }
  function farSound(t) { // a distant siren or a lone horn, very quiet
    if (Math.random() < 0.5) {
      for (let i = 0; i < 4; i++) {
        tone(an.evt, { t: t + i * 0.9, f: 620, f2: 830, dur: 0.85, v: 0.01, type: 'triangle', lp: 700, a: 0.4 });
      }
    } else {
      tone(an.evt, { t, f: 311, dur: 0.5, v: 0.015, type: 'sawtooth', lp: 500, a: 0.03 });
      tone(an.evt, { t, f: 392, dur: 0.5, v: 0.015, type: 'sawtooth', lp: 500, a: 0.03 });
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
        nx.bird += rnd(14, 34);
      }
      if (nx.ind < now - 0.5) nx.ind = now + rnd(8, 25);
      if (nx.ind < hz) { if (a.speed > 0.1) play('indicator', { delay: Math.max(0, nx.ind - now) }); nx.ind += rnd(20, 50); }
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
    radio,
    fast: { set: setFast },
    setVolume, setMuted,
    getSettings: () => ({ master: cfg.master, music: cfg.music, sfx: cfg.sfx, amb: cfg.amb, muted: cfg.muted }),
    names: Object.keys(S),
    _attach: attach // level tests with an OfflineAudioContext
  };
  load();
})(typeof window !== 'undefined' ? window : globalThis);
