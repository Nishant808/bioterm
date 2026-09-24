import {Easing, useCurrentFrame, useVideoConfig} from 'remotion';

export const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const prog = (t: number, a: number, b: number) => clamp((t - a) / (b - a));

// Motion language: precise cubic-bezier curves, one gentle overshoot.
export const E = {
  out: Easing.bezier(0.16, 1, 0.3, 1), // expo-like settle
  inOut: Easing.bezier(0.65, 0, 0.35, 1),
  in: Easing.bezier(0.55, 0, 1, 0.45),
  soft: Easing.bezier(0.33, 0, 0.2, 1),
  overshoot: Easing.bezier(0.34, 1.32, 0.64, 1), // slight, never elastic
};

/** Seconds since the start of the film. */
export const useTime = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return frame / fps;
};

/** Opacity for an element living in [a,b] with fade-in/out durations. */
export const windowed = (t: number, a: number, b: number, fin = 0.35, fout = 0.35) =>
  Math.min(E.out(prog(t, a, a + fin)), 1 - E.inOut(prog(t, b - fout, b)));

/** Deterministic PRNG (mulberry32) - every render is identical. */
export const rng = (seed: number) => {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};

export const fmtUsd = (x: number) => `$${x.toFixed(2)}`;
