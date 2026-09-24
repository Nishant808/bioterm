import {BEAT} from '../config/timing';
import type {Layout} from '../config/layout';
import {OPENING_WINDOW} from '../data/event';
import {E, lerp, prog} from '../lib/anim';
import {chartGeom, closeAt, Rect} from '../components/MarketChart';

const N = OPENING_WINDOW.length; // Jul 13 .. Aug 19 2026
export const SPIKE_I = N - 1; // Aug 19
const PRE_I = N - 2; // Aug 18

export const chartRects = (L: Layout): {rect: Rect; vol: Rect} => {
  const {w, h, vertical} = L;
  if (vertical)
    return {
      rect: {x0: 0.09 * w, x1: 0.83 * w, y0: 0.4 * h, y1: 0.68 * h},
      vol: {x0: 0.09 * w, x1: 0.83 * w, y0: 0.7 * h, y1: 0.745 * h},
    };
  return {
    rect: {x0: 0.1 * w, x1: 0.84 * w, y0: 0.26 * h, y1: 0.72 * h},
    vol: {x0: 0.1 * w, x1: 0.84 * w, y0: 0.745 * h, y1: 0.82 * h},
  };
};

/** Bars drawn so far. Speed climbs from ~2s (4x by the spike), then the event day. */
export const drawK = (t: number) => {
  if (t < BEAT.spikeStart) {
    const p = prog(t, BEAT.drawStart, BEAT.spikeStart);
    return PRE_I * (0.5 * p + 0.5 * p * p * p);
  }
  return PRE_I + E.in(prog(t, BEAT.spikeStart, BEAT.spikeEnd));
};

const FINAL_DOMAIN: [number, number] = [30, 186];

export const marketState = (t: number, L: Layout) => {
  const {rect, vol} = chartRects(L);
  const k = drawK(t);
  const head = closeAt(OPENING_WINDOW, k);
  const r = E.inOut(prog(t, BEAT.spikeStart - 0.1, BEAT.rescaleEnd));
  const hi = Math.max(lerp(72, FINAL_DOMAIN[1], r), head * 1.05);
  const lo = lerp(48, FINAL_DOMAIN[0], r);
  const domain: [number, number] = [lo, hi];
  const volMax = lerp(12e6, 215e6, r);

  // Camera: world point Wc sits at screen centre, scaled by s.
  const gF = chartGeom(N, rect, FINAL_DOMAIN);
  const peak = {x: gF.x(SPIKE_I), y: gF.y(OPENING_WINDOW[SPIKE_I].close)};
  const pre = {x: gF.x(PRE_I), y: gF.y(OPENING_WINDOW[PRE_I].close)};
  const mid = {x: (peak.x + pre.x) / 2, y: (peak.y + pre.y) / 2};
  const zoom = E.inOut(prog(t, BEAT.zoomStart, 4.3));
  const toMid = E.inOut(prog(t, 4.3, 5.6));
  const dive = E.in(prog(t, BEAT.diveStart, BEAT.diveEnd));
  const s = (1 + 0.07 * zoom) * Math.pow(12, dive);
  const c = {x: L.cx, y: L.cy};
  const wz = {x: lerp(c.x, peak.x, 0.1 * zoom), y: lerp(c.y, peak.y, 0.12 * zoom)};
  const Wc = {x: lerp(wz.x, mid.x, toMid), y: lerp(wz.y, mid.y, toMid)};
  const toScreen = (p: {x: number; y: number}) => ({x: c.x + s * (p.x - Wc.x), y: c.y + s * (p.y - Wc.y)});
  const transform = `translate(${c.x} ${c.y}) scale(${s}) translate(${-Wc.x} ${-Wc.y})`;

  const len = Math.hypot(peak.x - pre.x, peak.y - pre.y);
  const dir = {x: (peak.x - pre.x) / len, y: (peak.y - pre.y) / len};

  return {rect, vol, k, head, domain, volMax, s, transform, toScreen, peak, pre, mid, dir, bars: OPENING_WINDOW};
};
