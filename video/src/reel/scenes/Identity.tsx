import React from 'react';
import {C, F} from '../../config/theme';
import {E, H, S, W, k, lerp} from '../core';
import {rng} from '../../lib/anim';
import {Mark} from '../Mark';
import {RGB} from '../fx';

// 3-7 s: shockwave, particles converge, the mark draws itself, the wordmark
// rises letter by letter, a light sweep, then we fly through the tile.
const A = S.mark;
const CX = W / 2;
const CY = H / 2;
const P = (() => {
  const r = rng(3);
  return Array.from({length: 140}, () => {
    const a = r() * Math.PI * 2;
    const d = 700 + r() * 900;
    return {x: Math.cos(a) * d, y: Math.sin(a) * d, s: 1 + r() * 2.5, dl: r() * 0.25, c: r() > 0.7 ? C.violet : C.accent};
  });
})();

export const Identity: React.FC<{t: number}> = ({t}) => {
  if (t < A || t > S.kinetic + 0.1) return null;
  const lt = t - A;
  const size = 300;
  // tile slides left to make room for the wordmark
  const slide = k(lt, 1.05, 1.6, E.inOut);
  const tileX = CX - lerp(0, 420, slide);
  // fly-through at the end
  const fly = k(lt, 3.45, 4.0, E.in);
  const flyS = lerp(1, 42, fly);
  const letters = ['B', 'i', 'o', 'T', 'e', 'r', 'm'];
  const tag = 'BIOTECH INTELLIGENCE TERMINAL';
  const tagP = k(lt, 1.75, 2.6);
  const sweep = k(lt, 2.2, 3.1, E.inOut);
  return (
    <div style={{position: 'absolute', inset: 0, transformOrigin: `${tileX}px ${CY}px`, transform: `scale(${flyS}) rotate(${fly * 12}deg)`,
      opacity: 1 - k(lt, 3.85, 4.0)}}>
      <svg width={W} height={H} style={{position: 'absolute', overflow: 'visible'}}>
        {/* burst lines */}
        {Array.from({length: 48}, (_, i) => {
          const a = (i / 48) * Math.PI * 2;
          const p = k(lt, 0, 0.7);
          const r0 = 60 + p * 500;
          const r1 = r0 + 40 + 220 * (1 - p);
          return (
            <line key={i} x1={CX + Math.cos(a) * r0} y1={CY + Math.sin(a) * r0} x2={CX + Math.cos(a) * r1} y2={CY + Math.sin(a) * r1}
              stroke={i % 3 ? C.accent : '#FFFFFF'} strokeWidth={2} opacity={(1 - p) * 0.9} />
          );
        })}
        {/* shockwaves */}
        {[0, 0.12, 0.24].map((d, i) => {
          const p = k(lt, d, d + 0.9);
          return <circle key={i} cx={CX} cy={CY} r={40 + p * 900} fill="none" stroke={C.accent} strokeWidth={3 - i} opacity={(1 - p) * 0.7} />;
        })}
        {/* converging particles */}
        {P.map((p, i) => {
          const q = k(lt, 0.05 + p.dl, 0.75 + p.dl, E.in);
          if (q >= 1) return null;
          const x = CX + p.x * (1 - q);
          const y = CY + p.y * (1 - q);
          return <circle key={i} cx={x} cy={y} r={p.s} fill={p.c} opacity={0.3 + 0.7 * q} />;
        })}
      </svg>
      <div style={{position: 'absolute', left: tileX - size / 2, top: CY - size / 2, transform: `scale(${lerp(0.6, 1, k(lt, 0.2, 0.9, E.overshoot))})`}}>
        <Mark size={size} id="id" frame={k(lt, 0.15, 0.7, E.inOut)} fill={k(lt, 0.55, 0.95, E.out)} hex={k(lt, 0.75, 1.25, E.inOut)}
          pulse={k(lt, 0.95, 1.45, E.inOut)} dot={k(lt, 1.35, 1.6, E.overshoot)} glow={k(lt, 0.6, 1.2)} />
      </div>
      {/* wordmark */}
      <RGB amt={0} style={{position: 'absolute', left: CX - 230, top: CY - 118, display: 'flex', overflow: 'hidden', paddingBottom: 8}}>
        {letters.map((ch, i) => {
          const p = k(lt, 1.25 + i * 0.05, 1.75 + i * 0.05, E.out);
          return (
            <span key={i} style={{display: 'inline-block', fontFamily: F.sans, fontSize: 196, lineHeight: 1, letterSpacing: -6,
              fontWeight: i < 3 ? 700 : 500, color: i < 3 ? C.text : C.accentSoft, transform: `translateY(${(1 - p) * 110}%)`}}>
              {ch}
            </span>
          );
        })}
        {/* light sweep, clipped to the glyphs */}
        <div style={{position: 'absolute', left: 0, top: 0, display: 'flex', pointerEvents: 'none', opacity: sweep > 0 && sweep < 1 ? 1 : 0}}>
          {letters.map((ch, i) => (
            <span key={i} style={{display: 'inline-block', fontFamily: F.sans, fontSize: 196, lineHeight: 1, letterSpacing: -6, fontWeight: i < 3 ? 700 : 500,
              color: 'transparent', backgroundImage: 'linear-gradient(100deg, transparent 40%, rgba(255,255,255,0.95) 50%, transparent 60%)',
              backgroundSize: '1400px 100%', backgroundPosition: `${lerp(-1400, 900, sweep) - i * 105}px 0`, backgroundRepeat: 'no-repeat',
              WebkitBackgroundClip: 'text', backgroundClip: 'text'}}>{ch}</span>
          ))}
        </div>
      </RGB>
      <div style={{position: 'absolute', left: CX - 222, top: CY + 104, fontFamily: F.mono, fontSize: 24, color: C.muted,
        letterSpacing: lerp(28, 9.2, tagP), opacity: tagP, whiteSpace: 'nowrap'}}>
        {tag}
      </div>
      <div style={{position: 'absolute', left: CX - 222, top: CY + 90, height: 2, width: 710 * k(lt, 1.6, 2.3, E.inOut), background: `linear-gradient(90deg, ${C.primary}, ${C.violet})`}} />
    </div>
  );
};
