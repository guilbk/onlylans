(function (root) {
  'use strict';
  const PG = root.PG = root.PG || {};

  // ---- event bus -------------------------------------------------------
  const listeners = Object.create(null);
  PG.bus = {
    on(ev, fn) {
      (listeners[ev] || (listeners[ev] = [])).push(fn);
    },
    off(ev, fn) {
      const a = listeners[ev];
      if (!a) return;
      const i = a.indexOf(fn);
      if (i >= 0) a.splice(i, 1);
    },
    emit(ev, payload) {
      const a = listeners[ev];
      if (!a || a.length === 0) return;
      // iterate a copy only when needed: listeners may unsubscribe while running
      const list = a.length === 1 ? a : a.slice();
      for (let i = 0; i < list.length; i++) {
        try {
          list[i](payload);
        } catch (err) {
          console.error('[bus] listener for "' + ev + '" failed:', err);
        }
      }
    },
  };

  // ---- constants (CONTRACT section 9) ---------------------------------
  PG.C = {
    BASE_SCALE: 40,
    FAST: 3,
    SHIFT: 7200,
    SLOTS: {
      am: { h: 8, label: '08–10' },
      lunch: { h: 12, label: '12–14' },
      pm: { h: 17, label: '17–19' },
      night: { h: 22, label: '22–24' },
    },
    DAYS: {
      mon: 'понеділок',
      tue: 'вівторок',
      wed: 'середа',
      thu: 'четвер',
      fri: 'п’ятниця',
      sat: 'субота',
      sun: 'неділя',
    },
    CALL: { A: 0, B: 1, C: 2 },
    CALL_NAMES: ['Виклик', 'Стоянка', 'З вулиці'],
    LEAD: [1200, 1200, 900],
    RADIUS: [6000, 4500, 3000],
    DIFF_K: { easy: 1.3, normal: 1, hard: 0.8 },
    BOARD_S: 30,
    HOME: { x: 9110, y: 12443 },
    MAP: { w: 15000, h: 19000 },
    FARE: { base: 3.25, perKm: 0.5, nightFactor: 1.2, nightFrom: 22, nightTo: 5 },
  };

  // ---- theme palettes for the canvas (docs/design/README.md); the CSS tokens live in 00_base.css ----
  // night = shift hour 21..04 (same window as the audio); 08, 12 and 17 are day.
  PG.C.NIGHT_FROM = 21;
  PG.C.NIGHT_TO = 5;
  PG.C.THEMES = {
    day: {
      name: 'day', bg: '#e6d4b4', ground: '#e6d5b2', blocks: ['#e1cfaa', '#e9dabb', '#dcc8a2', '#e3d0ac'],
      roofs: ['#d9895f', '#e3a679', '#cfae8e', '#c97a52'], park: '#b9d79a', tree: '#9cc47a', azulejo: '#2456c4',
      street: '255,250,240', streetMinor: 0.08, streetMain: 1, additive: false, widen: true,
      ink: '#12234a', card: 'rgba(255,250,240,0.94)', muted: '#55627f', dot: '#8d8a86', faint: 'rgba(18,35,74,0.16)',
      acc: '#0fb98a', ghost: '#6b45d3', ghostRgb: '107,69,211', bad: '#c4263c', blue: '#2456c4', track: 'rgba(36,86,196,0.22)',
      pins: ['#f5b82e', '#3fb8ea', '#f26b82'], pinInk: '#12234a', casing: 'rgba(255,250,240,0.95)',
      route: 'rgba(15,185,138,1)', trail: 'rgba(15,185,138,0.3)', next: 'rgba(196,120,20,0.85)', flag: '#12234a',
    },
    night: {
      name: 'night', bg: '#0b1430', ground: '#0b1430', blocks: ['#15234b', '#182857', '#131f46', '#172552'],
      roofs: ['#1f3269', '#26397a', '#1b2c60', '#2c4690'], park: '#0f3340', tree: '#14495a', azulejo: '#5f8cff',
      street: '90,169,255', streetMinor: 0.03, streetMain: 0.55, additive: true, widen: false,
      ink: '#eaf0ff', card: 'rgba(13,23,52,0.92)', muted: '#93a3cc', dot: '#6b7488', faint: 'rgba(138,150,179,0.16)',
      acc: '#3df5b0', ghost: '#b48cff', ghostRgb: '180,140,255', bad: '#ff6b6b', blue: '#8fb8ff', track: 'rgba(143,184,255,0.25)',
      pins: ['#ffc857', '#5ee6ff', '#ff7a90'], pinInk: '#0b1430', casing: 'rgba(8,15,36,0.75)',
      route: 'rgba(61,245,176,0.95)', trail: 'rgba(61,245,176,0.28)', next: 'rgba(255,200,87,0.6)', flag: '#eaf0ff',
    },
  };

  // ---- helpers ---------------------------------------------------------
  function pad2(n) { return n < 10 ? '0' + n : '' + n; }

  const NAME_KEY = 'porto.name';
  const HERO = 'Ріїн Гіслінг';

  PG.util = {
    /** The player's name: the saved one, else the hero's. */
    playerName() {
      try { const n = (root.localStorage.getItem(NAME_KEY) || '').trim(); if (n) return n.slice(0, 20); } catch (e) { /* ignore */ }
      return HERO;
    },
    setPlayerName(v) {
      const n = String(v || '').trim().slice(0, 20);
      try { if (n && n !== HERO) root.localStorage.setItem(NAME_KEY, n); else root.localStorage.removeItem(NAME_KEY); } catch (e) { /* ignore */ }
    },
    /** 12.4 -> "€12,40" */
    eur(x) {
      const neg = x < 0;
      const cents = Math.round(Math.abs(x) * 100);
      const s = Math.floor(cents / 100) + ',' + pad2(cents % 100);
      return (neg ? '-' : '') + '€' + s;
    },
    /** Ukrainian plural: 1 / 2-4 / 5-20 rules (21 -> one, 12 -> many). */
    plural(n, one, few, many) {
      const a = Math.abs(Math.trunc(n));
      const m10 = a % 10;
      const m100 = a % 100;
      if (m10 === 1 && m100 !== 11) return one;
      if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
      return many;
    },
    /** seconds -> "12 хв" (rounded to whole minutes). */
    mins(sec) {
      return Math.round(sec / 60) + ' хв';
    },
    /** Local clock of a shift: startHour*3600 + tGame seconds -> "08:42". */
    clock(startHour, tGame) {
      const total = Math.floor(startHour * 3600 + tGame);
      const h = Math.floor(total / 3600) % 24;
      const m = Math.floor((total % 3600) / 60);
      return pad2(h) + ':' + pad2(m);
    },
  };

  PG.REDUCED = (typeof root.matchMedia === 'function') &&
    !!root.matchMedia('(prefers-reduced-motion: reduce)').matches;
})(typeof window !== 'undefined' ? window : globalThis);
