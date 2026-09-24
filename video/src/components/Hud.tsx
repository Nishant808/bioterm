import React from 'react';
import {C, F} from '../config/theme';
import {BEAT, CHAPTERS} from '../config/timing';
import type {Layout} from '../config/layout';
import {E, prog, windowed} from '../lib/anim';

/**
 * Journey rail + corner metadata: MARKET -> COMPANY -> BIOLOGY -> SCIENCE ->
 * INTELLIGENCE. The one element on screen from 0.4s to the product flow, it
 * keeps the story legible at a glance.
 */
export const Hud: React.FC<{t: number; L: Layout}> = ({t, L}) => {
  const {u, w, h, vertical} = L;
  const rail = windowed(t, 0.4, BEAT.steps[0] - 0.25, 0.5, 0.3);
  const corners = windowed(t, 0.5, BEAT.windowW[0], 0.5, 0.3);
  const idx = CHAPTERS.findIndex((c) => t >= c.from && t < c.to);
  const pad = (vertical ? 56 : 64) * u;
  const meta: React.CSSProperties = {position: 'absolute', fontFamily: F.mono, fontSize: 13 * u, letterSpacing: 2 * u, color: C.faint};
  return (
    <>
      <div style={{...meta, left: pad, top: pad * 0.75, opacity: corners}}>
        NASDAQ: MRNA <span style={{color: C.border}}>/</span> 2026-08-19
      </div>
      <div style={{...meta, right: pad, top: pad * 0.75, opacity: corners, color: C.muted}}>
        {String(Math.max(1, idx + 1)).padStart(2, '0')} <span style={{color: C.border}}>—</span> {CHAPTERS[Math.max(0, idx)].key}
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, top: h - (vertical ? 120 : 64) * u, display: 'flex', justifyContent: 'center', gap: (vertical ? 16 : 26) * u, opacity: rail, fontFamily: F.mono, fontSize: (vertical ? 15 : 14) * u, letterSpacing: 2.2 * u}}>
        {CHAPTERS.map((c, i) => {
          const on = i === idx;
          const p = E.out(prog(t, c.from, c.from + 0.4));
          return (
            <span key={c.key} style={{display: 'flex', alignItems: 'center', gap: 10 * u, color: on ? C.text : i < idx ? C.muted : C.faint}}>
              <span style={{position: 'relative'}}>
                {c.key}
                <span style={{position: 'absolute', left: 0, bottom: -9 * u, height: 2 * u, width: on ? `${p * 100}%` : i < idx ? '100%' : 0, background: on ? C.accent : C.border}} />
              </span>
              {i < CHAPTERS.length - 1 && !vertical && <span style={{color: C.border}}>→</span>}
            </span>
          );
        })}
      </div>
    </>
  );
};

/** Near-black plane, one soft lift, a faint terminal grid and a static dither against banding. */
export const Background: React.FC<{t: number; L: Layout}> = ({t, L}) => {
  const {w, h, u} = L;
  const grid = 0.55 * windowed(t, 0.1, 15.2, 1.0, 0.6);
  const gs = 48 * u;
  const drift = (t * 6 * u) % gs;
  return (
    <>
      <div style={{position: 'absolute', inset: 0, background: `radial-gradient(ellipse 70% 60% at 50% 45%, #0A0E15 0%, ${C.void} 70%)`}} />
      <svg width={w} height={h} style={{position: 'absolute', opacity: grid}}>
        <defs>
          <pattern id="grid" width={gs} height={gs} patternUnits="userSpaceOnUse" patternTransform={`translate(${-drift} 0)`}>
            <path d={`M ${gs} 0 L 0 0 0 ${gs}`} fill="none" stroke="#0F141C" strokeWidth={1} />
          </pattern>
          <radialGradient id="gridfade" cx="50%" cy="50%" r="60%">
            <stop offset="0" stopColor="#fff" stopOpacity={1} />
            <stop offset="1" stopColor="#fff" stopOpacity={0} />
          </radialGradient>
          <mask id="gridmask">
            <rect width={w} height={h} fill="url(#gridfade)" />
          </mask>
        </defs>
        <rect width={w} height={h} fill="url(#grid)" mask="url(#gridmask)" />
      </svg>
      <svg width={w} height={h} style={{position: 'absolute', opacity: 0.05, mixBlendMode: 'screen'}}>
        <filter id="dither">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={1} seed={7} />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width={w} height={h} filter="url(#dither)" />
      </svg>
    </>
  );
};
