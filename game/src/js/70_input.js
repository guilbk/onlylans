/* 70_input.js: pointer, wheel, pinch and keys (CONTRACT §8, §14). */
(function (root) {
  const PG = root.PG = root.PG || {};

  const DRAG_PX = 6;            // movement beyond this is a pan, not a tap
  const WHEEL_K = 0.0015;
  const INTERACTIVE = 'button, a, input, select, textarea, label, #order-card, .screen, [data-no-map]';

  let mapEl = null;
  let unlocked = false;
  let hoverO = null;

  // active pointers of the current gesture (events only, so small allocations are fine)
  const ptrs = [];
  let gesture = null;           // {x0, y0, moved, multi, pinchD, pinchS}

  function findPtr(id) {
    for (let i = 0; i < ptrs.length; i++) if (ptrs[i].id === id) return i;
    return -1;
  }

  function engine() {
    return PG.engine || null;
  }

  function liveGame() {
    const e = engine();
    return e && e.G && !e.G.over ? e : null;
  }

  function localXY(ev, out) {
    const r = mapEl.getBoundingClientRect();
    out.x = ev.clientX - r.left;
    out.y = ev.clientY - r.top;
    out.inside = out.x >= 0 && out.y >= 0 && out.x <= r.width && out.y <= r.height;
    return out;
  }

  function isMapTarget(ev) {
    if (PG.screen !== 'play' || !mapEl) return false;
    const t = ev.target;
    if (t && t.closest && t.closest(INTERACTIVE)) return false;
    return true;
  }

  function unlockAudio() {
    if (unlocked) return;
    if (PG.audio && PG.audio.unlock) {
      unlocked = true;
      PG.audio.unlock();
    }
  }

  // ---- tap ----
  function tapPin(pin) {
    const e = liveGame();
    if (!e) return;
    const o = pin.o;
    if (PG.orders && PG.orders.tap) {
      PG.orders.tap(o);
    } else if (e.G.mode === 'ride') {
      e.bookNext(o);
    } else {
      e.startPickup(o);
    }
  }

  const tapPt = { x: 0, y: 0, inside: false };

  function handleTap(ev) {
    if (!localXY(ev, tapPt).inside) return;
    const pin = PG.render.nearestPin(tapPt.x, tapPt.y);
    if (pin) { tapPin(pin); return; }
    const e = liveGame();
    if (!e) return;
    if (PG.orders && PG.orders.selected && PG.orders.tap) {
      PG.orders.tap(null);   // a tap elsewhere clears the selection
      return;
    }
    const w = PG.render.screenToWorld(tapPt.x, tapPt.y);
    e.cruiseTo(w.x, w.y);
  }

  // ---- pointer events ----
  function onDown(ev) {
    unlockAudio();
    if (!isMapTarget(ev)) return;
    if (ev.pointerType === 'mouse' && ev.button !== 0) return;
    const p = {};
    if (!localXY(ev, p).inside) return;
    p.id = ev.pointerId;
    p.px = p.x;
    p.py = p.y;
    ptrs.push(p);
    if (ptrs.length === 1) {
      gesture = { x0: p.x, y0: p.y, moved: false, multi: false, pinchD: 0, pinchS: 0 };
    } else if (gesture) {
      gesture.multi = true;
      gesture.moved = true;
      const a = ptrs[0];
      const b = ptrs[1];
      gesture.pinchD = Math.hypot(a.x - b.x, a.y - b.y) || 1;
    }
  }

  const movePt = { x: 0, y: 0, inside: false };

  function onMove(ev) {
    const i = findPtr(ev.pointerId);
    if (i < 0) {
      hover(ev);
      return;
    }
    localXY(ev, movePt);
    const p = ptrs[i];
    const dx = movePt.x - p.x;
    const dy = movePt.y - p.y;
    p.x = movePt.x;
    p.y = movePt.y;
    if (!gesture) return;
    if (ptrs.length >= 2) {
      const a = ptrs[0];
      const b = ptrs[1];
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const f = d / gesture.pinchD;
      if (f > 0.5 && f < 2) {
        PG.render.zoomAt((a.x + b.x) * 0.5, (a.y + b.y) * 0.5, f);
        gesture.pinchD = d;
      }
      PG.render.panBy(dx * 0.5, dy * 0.5);
      return;
    }
    if (!gesture.moved && Math.hypot(p.x - gesture.x0, p.y - gesture.y0) > DRAG_PX) {
      gesture.moved = true;
    }
    if (gesture.moved) PG.render.panBy(dx, dy);
  }

  function onUp(ev) {
    const i = findPtr(ev.pointerId);
    if (i < 0) return;
    ptrs.splice(i, 1);
    const g = gesture;
    if (ptrs.length === 0) {
      gesture = null;
      if (g && !g.moved && !g.multi && ev.type === 'pointerup') handleTap(ev);
    }
  }

  function hover(ev) {
    if (ev.pointerType !== 'mouse' || PG.screen !== 'play') return;
    if (!PG.render) return;
    const t = ev.target;
    const blocked = t && t.closest && t.closest(INTERACTIVE);
    let pin = null;
    if (!blocked && localXY(ev, movePt).inside) pin = PG.render.nearestPin(movePt.x, movePt.y);
    mapEl.classList.toggle('over-pin', !!pin);
    const o = pin ? pin.o : null;
    if (o === hoverO) return;
    hoverO = o;
    if (PG.orders && PG.orders.hover) PG.orders.hover(o);
  }

  function onWheel(ev) {
    if (!isMapTarget(ev)) return;
    if (!localXY(ev, movePt).inside) return;
    ev.preventDefault();
    let dy = ev.deltaY;
    if (ev.deltaMode === 1) dy *= 16;
    else if (ev.deltaMode === 2) dy *= 400;
    PG.render.zoomAt(movePt.x, movePt.y, Math.exp(-dy * WHEEL_K));
  }

  // ---- keys ----
  function typing(ev) {
    const t = ev.target;
    return !!(t && t.tagName && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  }

  function onKey(ev) {
    unlockAudio();
    if (typing(ev) || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const k = ev.key;
    const e = engine();
    if (k === 'Escape') {
      if (PG.screen !== 'menu' && PG.screens && PG.screens.showMenu) {
        ev.preventDefault();
        PG.screens.showMenu();
      }
      return;
    }
    if (PG.screen !== 'play' || !e || !e.G || e.G.over) return;
    if (k === ' ' || k === 'Spacebar') {
      ev.preventDefault();
      e.G.paused = !e.G.paused;
      PG.bus.emit('pause', { paused: e.G.paused });
    } else if (k === 'f' || k === 'F' || k === 'а' || k === 'А') {
      e.G.fast = !e.G.fast;
    }
  }

  function onKeyUp(ev) {
    // stop a focused button from being clicked by the space bar while playing
    if (ev.key === ' ' && PG.screen === 'play' && !typing(ev)) ev.preventDefault();
  }

  function onClickCapture(ev) {
    const t = ev.target;
    const b = t && t.closest ? t.closest('button') : null;
    if (b) PG.bus.emit('ui:click', { el: b });
  }

  function init() {
    mapEl = document.getElementById('map');
    document.addEventListener('pointerdown', onDown, true);
    document.addEventListener('pointermove', onMove, true);
    document.addEventListener('pointerup', onUp, true);
    document.addEventListener('pointercancel', onUp, true);
    document.addEventListener('wheel', onWheel, { passive: false });
    document.addEventListener('keydown', onKey);
    document.addEventListener('keyup', onKeyUp);
    document.addEventListener('click', onClickCapture, true);
    if (mapEl) {
      mapEl.addEventListener('pointerleave', function () {
        if (hoverO && PG.orders && PG.orders.hover) PG.orders.hover(null);
        hoverO = null;
        mapEl.classList.remove('over-pin');
      });
    }
  }

  PG.input = { init: init };
})(typeof window !== 'undefined' ? window : globalThis);
