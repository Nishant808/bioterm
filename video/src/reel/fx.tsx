import React from 'react';
import {staticFile, useCurrentFrame} from 'remotion';
import {C, F} from '../config/theme';
import {DUR, FPS, H, S, W, hitEnergy, noise1, win} from './core';

/** Film grain: a pre-baked noise tile, re-positioned every frame. */
export const Grain: React.FC<{opacity?: number}> = ({opacity = 0.07}) => {
  const frame = useCurrentFrame();
  const x = (frame * 197) % 256;
  const y = (frame * 131) % 256;
  return (
    <div
      style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', opacity, mixBlendMode: 'overlay',
        backgroundImage: `url(${staticFile('reel/grain.png')})`, backgroundPosition: `${x}px ${y}px`,
      }}
    />
  );
};

export const Vignette: React.FC<{strength?: number}> = ({strength = 0.75}) => (
  <div style={{position: 'absolute', inset: 0, pointerEvents: 'none',
    background: `radial-gradient(ellipse 75% 70% at 50% 50%, transparent 55%, rgba(0,0,0,${strength}) 100%)`}} />
);

/** White flash on every hit, a touch of blue in the tail. */
export const Flash: React.FC<{t: number}> = ({t}) => {
  const e = Math.min(1, hitEnergy(t, 0.07));
  const tail = Math.min(1, hitEnergy(t, 0.35));
  return (
    <>
      <div style={{position: 'absolute', inset: 0, background: '#FFFFFF', opacity: e * 0.55, mixBlendMode: 'screen'}} />
      <div style={{position: 'absolute', inset: 0, background: `radial-gradient(circle at 50% 50%, ${C.primary}55, transparent 60%)`, opacity: tail * 0.6}} />
    </>
  );
};

/** Camera: shake on hits plus a slow handheld drift. */
export const Camera: React.FC<{t: number; children: React.ReactNode; drift?: number}> = ({t, children, drift = 1}) => {
  const e = Math.min(1.2, hitEnergy(t, 0.14));
  const sx = noise1(t * 22, 1) * 16 * e + noise1(t * 0.35, 7) * 5 * drift;
  const sy = noise1(t * 22, 2) * 12 * e + noise1(t * 0.3, 9) * 4 * drift;
  const rot = noise1(t * 18, 3) * 0.35 * e;
  const zoom = 1 + e * 0.018;
  return (
    <div style={{position: 'absolute', inset: 0, transform: `translate(${sx}px, ${sy}px) rotate(${rot}deg) scale(${zoom})`}}>
      {children}
    </div>
  );
};

/** Chromatic split for type: red/cyan copies offset by `amt` px. */
export const RGB: React.FC<{amt: number; children: React.ReactNode; style?: React.CSSProperties}> = ({amt, children, style}) => {
  if (amt < 0.4) return <div style={style}>{children}</div>;
  return (
    <div style={{...style, position: style?.position ?? 'relative'}}>
      <div style={{position: 'absolute', inset: 0, transform: `translate(${-amt}px, 0)`, filter: 'url(#tint-r)', opacity: 0.85, mixBlendMode: 'screen'}}>{children}</div>
      <div style={{position: 'absolute', inset: 0, transform: `translate(${amt}px, 0)`, filter: 'url(#tint-c)', opacity: 0.85, mixBlendMode: 'screen'}}>{children}</div>
      <div style={{position: 'relative'}}>{children}</div>
    </div>
  );
};

/** SVG filters used across the reel (declared once). */
export const Defs: React.FC = () => (
  <svg width={0} height={0} style={{position: 'absolute'}}>
    <defs>
      <filter id="tint-r"><feColorMatrix type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" /></filter>
      <filter id="tint-c"><feColorMatrix type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 1 0" /></filter>
      <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="6" result="b" />
        <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
      <filter id="glow-lg" x="-100%" y="-100%" width="300%" height="300%">
        <feGaussianBlur stdDeviation="18" result="b" />
        <feMerge><feMergeNode in="b" /><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
      <linearGradient id="brand" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#4C8DFF" /><stop offset="1" stopColor="#6A5CF6" />
      </linearGradient>
    </defs>
  </svg>
);

const CHAPTERS: [number, string][] = [
  [S.ignite, 'SIGNAL'], [S.mark, 'IDENTITY'], [S.kinetic, 'REAL-TIME'], [S.universe, 'UNIVERSE'],
  [S.engine, 'SIGNAL ENGINE'], [S.terminal, 'TERMINAL'], [S.copilot, 'COPILOT'], [S.numbers, 'BY THE NUMBERS'],
  [S.finale, 'BIOTERM'],
];

/** Showreel HUD: title, chapter, running timecode, format. */
export const Hud: React.FC<{t: number}> = ({t}) => {
  const frame = Math.round(t * FPS);
  const tc = (n: number) => String(n).padStart(2, '0');
  const code = `00:${tc(Math.floor(t / 60))}:${tc(Math.floor(t) % 60)}:${tc(frame % FPS)}`;
  const ci = CHAPTERS.reduce((a, c, i) => (t >= c[0] ? i : a), 0);
  const o = win(t, 0.9, S.finale + 0.2, 0.4, 0.3) * 0.75;
  const meta: React.CSSProperties = {position: 'absolute', fontFamily: F.mono, fontSize: 14, letterSpacing: 3, color: C.muted};
  const chapterIn = Math.min(1, (t - CHAPTERS[ci][0]) / 0.25);
  return (
    <div style={{position: 'absolute', inset: 0, opacity: o, pointerEvents: 'none'}}>
      <div style={{...meta, left: 56, top: 44}}>
        <span style={{color: C.text}}>BIOTERM</span> <span style={{color: C.border}}>/</span> MOTION REEL 2026
      </div>
      <div style={{...meta, right: 56, top: 44, display: 'flex', gap: 14, alignItems: 'center'}}>
        <span style={{color: C.accent}}>{tc(ci + 1)}</span>
        <span style={{width: 40 * chapterIn, height: 1, background: C.accent, display: 'inline-block'}} />
        <span style={{color: C.text, opacity: chapterIn}}>{CHAPTERS[ci][1]}</span>
      </div>
      <div style={{...meta, left: 56, bottom: 40, color: C.text2}}>
        <span style={{display: 'inline-block', width: 8, height: 8, borderRadius: 4, background: C.neg, marginRight: 10, opacity: frame % 60 < 36 ? 1 : 0.25}} />
        {code}
      </div>
      <div style={{...meta, right: 56, bottom: 40}}>{W}×{H} · {FPS}P · {DUR.toFixed(0)}S</div>
      {/* frame marks */}
      {[[40, 30, 1, 1], [W - 40, 30, -1, 1], [40, H - 30, 1, -1], [W - 40, H - 30, -1, -1]].map(([x, y, dx, dy], i) => (
        <svg key={i} width={24} height={24} style={{position: 'absolute', left: dx > 0 ? x - 1 : x - 23, top: dy > 0 ? y - 1 : y - 23}}>
          <path d={dx > 0 ? (dy > 0 ? 'M1 23V1H23' : 'M1 1V23H23') : dy > 0 ? 'M23 23V1H1' : 'M23 1V23H1'} stroke={C.borderStrong} fill="none" strokeWidth={1.5} />
        </svg>
      ))}
    </div>
  );
};
