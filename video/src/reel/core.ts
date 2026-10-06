// Showreel timing + motion helpers. 120 BPM: one beat = 0.5 s, one bar = 2 s.
// Every cut and every hit sits on the grid; audio/showreel.py reads the same
// numbers from reel.json so picture and sound stay locked.
import R from './reel.json';
import {E, clamp, lerp, prog} from '../lib/anim';

export const FPS = 60;
export const W = 1920;
export const H = 1080;
export const DUR = R.duration;
export const S = R.scenes; // scene starts (s)
export const HITS: number[] = R.hits; // impacts: flash + shake + sub drop
export const WORDS = R.words; // kinetic word slams

export {E, clamp, lerp, prog};

/** Ease helpers that read like a keyframe: k(t, a, b, ease) in 0..1 */
export const k = (t: number, a: number, b: number, ease: (x: number) => number = E.out) => ease(prog(t, a, b));

/** Fast exponential decay after an event (for flashes, shakes). */
export const decay = (t: number, at: number, tau = 0.12) => (t < at ? 0 : Math.exp(-(t - at) / tau));

/** Sum of decays across all hit times. */
export const hitEnergy = (t: number, tau = 0.12) =>
  HITS.reduce((s, h) => s + decay(t, h, tau), 0) + WORDS.slice(1).reduce((s, w) => s + 0.45 * decay(t, w.at, tau), 0);

/** Beat phase 0..1 within the current beat, and a kick envelope. */
export const beatPulse = (t: number, from = 0) => (t < from ? 0 : Math.exp(-((t - from) % 0.5) / 0.09));

/** Smooth value-noise for camera drift (deterministic). */
export const noise1 = (x: number, seed = 1) => {
  const i = Math.floor(x);
  const f = x - i;
  const h = (n: number) => {
    const s = Math.sin((n + seed * 101.3) * 127.1) * 43758.5453;
    return s - Math.floor(s);
  };
  const u = f * f * (3 - 2 * f);
  return lerp(h(i), h(i + 1), u) * 2 - 1;
};

/** Window visibility with fade in/out. */
export const win = (t: number, a: number, b: number, fin = 0.2, fout = 0.2) =>
  clamp(Math.min(prog(t, a, a + fin), 1 - prog(t, b - fout, b)));

export const inScene = (t: number, a: number, b: number, pad = 0.6) => t >= a - pad && t < b + pad;
