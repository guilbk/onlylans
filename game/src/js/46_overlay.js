(function (root) {
  const PG = root.PG = root.PG || {};
  // One overlay at a time under the HUD. Priority: order card > coach > hint > toast > missions card > radio banner > combo.
  // The order card hides the whole stack; of the rest only the first one that is «on» stays visible.
  const STACK = ['.coach-card', '.hint-card', '#toast', '.msn-card', '#fx-banner', '#fx-combo'];
  const PHONE_W = 640;

  function visible(el) { return !!el && el.classList.contains('on'); }

  function tick() {
    const d = root.document;
    const oc = d.getElementById('order-card');
    const stage = d.getElementById('stage');
    const orderUp = !!oc && !oc.classList.contains('hidden');
    const phone = !!stage && stage.clientWidth <= PHONE_W;
    let taken = orderUp;
    for (let i = 0; i < STACK.length; i++) {
      const e = d.querySelector(STACK[i]);
      if (!e) continue;
      if (STACK[i] === '#fx-combo' && !phone) { e.classList.remove('ov-off'); continue; }   // wide: right edge, never meets the cards
      const on = visible(e);
      e.classList.toggle('ov-off', on && taken);
      if (on) taken = true;
    }
  }

  // true while the order card or any overlay other than `self` is showing (the hint card waits for it)
  function busy(self) {
    const d = root.document;
    const oc = d.getElementById('order-card');
    if (oc && !oc.classList.contains('hidden')) return true;
    for (let i = 0; i < STACK.length; i++) {
      const e = d.querySelector(STACK[i]);
      if (e && e !== self && visible(e) && STACK[i] !== '.hint-card' && STACK[i] !== '#fx-combo') return true;
    }
    return false;
  }

  PG.overlay = { tick: tick, busy: busy };
  if (PG.bus) PG.bus.on('frame', tick);
})(typeof window !== 'undefined' ? window : globalThis);
