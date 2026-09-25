import React from 'react';
import {C, F} from '../../config/theme';
import {E, H, S, W, k, lerp} from '../core';
import {rng} from '../../lib/anim';
import {Mark} from '../Mark';

// 35-40 s: implosion to a point, the mark detonates back in with a shockwave,
// the wordmark and line land, a light sweep, and out.
const A = S.finale;
const HIT = 35.5;
const SPARKS = (() => {
  const r = rng(35);
  return Array.from({length: 90}, () => ({a: r() * Math.PI * 2, v: 300 + r() * 900, s: 1 + r() * 3, c: r() > 0.6 ? C.violet : r() > 0.3 ? C.accent : '#FFFFFF'}));
})();

export const Finale: React.FC<{t: number}> = ({t}) => {
  if (t < A - 0.05) return null;
  const lt = t - HIT;
  const pre = k(t, A, HIT, E.in);
  const pop = k(lt, 0, 0.45, E.overshoot);
  const size = 190;
  const cx = W / 2;
  const cy = H / 2 - 90;
  const tag = ['Signal', 'before', 'the', 'move.'];
  const sweep = k(lt, 1.5, 2.4, E.inOut);
  const out = k(t, 39.3, 40, E.inOut);
  const url = 'bioterm.streamlit.app';
  const un = Math.floor(url.length * k(lt, 2.2, 2.9, (x) => x));
  return (
    <div style={{position: 'absolute', inset: 0, opacity: 1 - out}}>
      <svg width={W} height={H} style={{position: 'absolute', overflow: 'visible'}}>
        {/* the singularity */}
        {lt < 0 && <circle cx={W / 2} cy={H / 2} r={3 + 10 * pre} fill="#FFFFFF" filter="url(#glow-lg)" />}
        {lt >= 0 && (
          <>
            {[0, 0.1, 0.22].map((d, i) => {
              const p = k(lt, d, d + 1.1);
              return <circle key={i} cx={cx} cy={cy + size / 2} r={size * 0.4 + p * 1100} fill="none" stroke={i === 1 ? C.violet : C.accent} strokeWidth={4 - i} opacity={(1 - p) * 0.8} />;
            })}
            {SPARKS.map((s, i) => {
              const p = k(lt, 0, 1.3, E.out);
              const d = s.v * p;
              return <circle key={i} cx={cx + Math.cos(s.a) * d} cy={cy + size / 2 + Math.sin(s.a) * d} r={s.s * (1 - p)} fill={s.c} opacity={1 - p} />;
            })}
          </>
        )}
      </svg>
      {lt >= 0 && (
        <>
          <div style={{position: 'absolute', left: cx - size / 2, top: cy, transform: `scale(${pop}) rotate(${(1 - pop) * -30}deg)`}}>
            <Mark size={size} id="fin" glow={1 - k(lt, 0.3, 1.5) * 0.6} pulse={k(lt, 0.15, 0.7, E.inOut)} dot={k(lt, 0.6, 0.85, E.overshoot)} />
          </div>
          <div style={{position: 'absolute', left: 0, right: 0, top: cy + size + 40, display: 'flex', justifyContent: 'center', overflow: 'hidden', paddingBottom: 6}}>
            <div style={{position: 'relative', display: 'flex'}}>
              {['B', 'i', 'o', 'T', 'e', 'r', 'm'].map((ch, i) => {
                const p = k(lt, 0.35 + i * 0.04, 0.8 + i * 0.04, E.out);
                return <span key={i} style={{display: 'inline-block', fontFamily: F.sans, fontSize: 120, lineHeight: 1, letterSpacing: -4,
                  fontWeight: i < 3 ? 700 : 500, color: i < 3 ? C.text : C.accentSoft, transform: `translateY(${(1 - p) * 110}%)`}}>{ch}</span>;
              })}
<div style={{position: 'absolute', left: 0, top: 0, display: 'flex', opacity: sweep > 0 && sweep < 1 ? 1 : 0}}>
                {['B', 'i', 'o', 'T', 'e', 'r', 'm'].map((ch, i) => (
                  <span key={i} style={{display: 'inline-block', fontFamily: F.sans, fontSize: 120, lineHeight: 1, letterSpacing: -4, fontWeight: i < 3 ? 700 : 500,
                    color: 'transparent', backgroundImage: 'linear-gradient(100deg, transparent 40%, rgba(255,255,255,0.95) 50%, transparent 60%)',
                    backgroundSize: '900px 100%', backgroundPosition: `${lerp(-900, 600, sweep) - i * 64}px 0`, backgroundRepeat: 'no-repeat',
                    WebkitBackgroundClip: 'text', backgroundClip: 'text'}}>{ch}</span>
                ))}
              </div>
            </div>
          </div>
          <div style={{position: 'absolute', left: 0, right: 0, top: cy + size + 190, display: 'flex', justifyContent: 'center', gap: 16}}>
            {tag.map((w, i) => {
              const p = k(lt, 1.0 + i * 0.12, 1.4 + i * 0.12, E.out);
              return <span key={i} style={{fontFamily: F.sans, fontSize: 46, fontWeight: 500, color: i === 3 ? C.accent : C.text2, opacity: p,
                transform: `translateY(${(1 - p) * 24}px)`, filter: p < 1 ? `blur(${(1 - p) * 8}px)` : undefined}}>{w}</span>;
            })}
          </div>
          <div style={{position: 'absolute', left: 0, right: 0, top: cy + size + 280, textAlign: 'center', fontFamily: F.mono, fontSize: 26, letterSpacing: 4, color: C.text}}>
            {url.slice(0, un)}<span style={{opacity: un && un < url.length ? 1 : 0, color: C.accent}}>▍</span>
          </div>
          <div style={{position: 'absolute', left: 0, right: 0, bottom: 70, textAlign: 'center', fontFamily: F.mono, fontSize: 14, letterSpacing: 4, color: C.faint,
            opacity: k(lt, 2.7, 3.1)}}>
            MONITORING &amp; SCREENING ONLY — NOT INVESTMENT ADVICE
          </div>
        </>
      )}
    </div>
  );
};
