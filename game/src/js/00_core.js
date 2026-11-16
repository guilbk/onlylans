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
    LEAD: [310, 310, 310],
    RADIUS: [5000, 3500, 2500],
    DIFF_K: { easy: 1.0, normal: 1, hard: 0.9 },
    BOARD_S: 30,
    HOME: { x: 9110, y: 12443 },
    MAP: { w: 15000, h: 19000 },
    FARE: { base: 3.25, perKm: 0.5, nightFactor: 1.2, nightFrom: 22, nightTo: 5 },
  };

  // ---- helpers ---------------------------------------------------------
  function pad2(n) { return n < 10 ? '0' + n : '' + n; }

  PG.util = {
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
