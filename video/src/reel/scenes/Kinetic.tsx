import React from 'react';
import {C, F} from '../../config/theme';
import {E, H, S, W, WORDS, k, lerp, noise1} from '../core';
import {rng} from '../../lib/anim';
import {RGB} from '../fx';

// 7-11 s: four word slams, one per bar-half, each with its own transition
// grammar, over a perspective grid rushing toward camera.
const A = S.kinetic;
const B = S.universe;

const Floor: React.FC<{t: number}> = ({t}) => {
  const speed = (t - A) * 620;
  const G = 140;
  return (
    <div style={{position: 'absolute', left: 0, width: W, top: H * 0.52, height: H * 0.48, perspective: 700, perspectiveOrigin: '50% 0%', overflow: 'hidden'}}>
      <div style={{position: 'absolute', left: -W, width: W * 3, bottom: 0, height: H * 4, transform: 'rotateX(78deg)', transformOrigin: '50% 100%'}}>
        <svg width={W * 3} height={H * 4} style={{position: 'absolute'}}>
          {Array.from({length: 40}, (_, i) => (
            <line key={`v${i}`} x1={W * 1.5 + (i - 20) * G} y1={0} x2={W * 1.5 + (i - 20) * G} y2={H * 4} stroke={C.primary} strokeWidth={3} opacity={0.55} />
          ))}
          {Array.from({length: Math.ceil((H * 4) / G) + 1}, (_, j) => {
            const y = (j * G + (speed % G));
            return <line key={`h${j}`} x1={0} x2={W * 3} y1={y} y2={y} stroke={C.primary} strokeWidth={3} opacity={0.55} />;
          })}
        </svg>
      </div>
      <div style={{position: 'absolute', inset: 0, background: `linear-gradient(180deg, ${C.void} 0%, ${C.void}00 55%)`}} />
    </div>
  );
};

const Sub: React.FC<{text: string; p: number; color?: string}> = ({text, p, color = C.text2}) => {
  const n = Math.floor(text.length * p);
  return (
    <div style={{fontFamily: F.mono, fontSize: 26, letterSpacing: 6, color, whiteSpace: 'nowrap', height: 34}}>
      {text.slice(0, n)}
      <span style={{opacity: p < 1 ? 1 : 0, color: C.accent}}>▍</span>
    </div>
  );
};

const big: React.CSSProperties = {fontFamily: F.sans, fontWeight: 800, fontSize: 300, lineHeight: 0.9, letterSpacing: -14, color: C.text, whiteSpace: 'nowrap'};

const Halts: React.FC<{lt: number}> = ({lt}) => {
  const p = k(lt, 0, 0.28, E.out);
  const out = k(lt, 0.86, 1.0, E.in);
  const bar = k(lt, 0.18, 0.5, E.inOut);
  return (
    <div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      transform: `scale(${1 + out * 0.6})`, opacity: 1 - out, filter: out > 0 ? `blur(${out * 16}px)` : undefined}}>
      <div style={{position: 'relative'}}>
        <div style={{...big, clipPath: 'inset(0 0 50% 0)', transform: `translateX(${(1 - p) * -1400}px)`}}>HALTS</div>
        <div style={{...big, position: 'absolute', top: 0, clipPath: 'inset(50% 0 0 0)', transform: `translateX(${(1 - p) * 1400}px)`}}>HALTS</div>
        <div style={{position: 'absolute', left: 0, right: 0, top: '48%', height: 10, background: C.neg, transform: `scaleX(${bar})`, boxShadow: `0 0 30px ${C.neg}`}} />
      </div>
      <div style={{marginTop: 40}}><Sub text={WORDS[0].sub} p={k(lt, 0.3, 0.75, (x) => x)} color={C.neg} /></div>
    </div>
  );
};

const DOCS = ['8-K', '424B5', 'SC 13D', 'S-3', '6-K'];
const Filings: React.FC<{lt: number}> = ({lt}) => {
  const out = k(lt, 0.86, 1.0, E.in);
  const letters = WORDS[1].word.split('');
  return (
    <div style={{position: 'absolute', inset: 0, transform: `translateY(${out * -900}px)`}}>
      {DOCS.map((d, i) => {
        const p = k(lt, 0.05 + i * 0.05, 0.55 + i * 0.05, E.overshoot);
        const a = (i - 2) * 11 * p;
        return (
          <div key={d} style={{position: 'absolute', left: W / 2 - 150, top: H / 2 - 230, width: 300, height: 390, borderRadius: 18,
            background: C.surface, border: `1.5px solid ${C.borderStrong}`, transformOrigin: '50% 140%',
            transform: `rotate(${a}deg) translateY(${(1 - p) * 500}px)`, opacity: 0.9 * p, boxShadow: '0 30px 80px rgba(0,0,0,0.6)'}}>
            <div style={{margin: 26, fontFamily: F.mono, fontSize: 30, color: i === 2 ? C.warn : C.accent, letterSpacing: 2}}>{d}</div>
            {Array.from({length: 7}, (_, j) => (
              <div key={j} style={{margin: '14px 26px', height: 10, borderRadius: 5, background: C.border, width: `${[88, 70, 94, 60, 82, 76, 50][j]}%`}} />
            ))}
          </div>
        );
      })}
      <div style={{position: 'absolute', left: 0, right: 0, top: H / 2 - 150, display: 'flex', justifyContent: 'center'}}>
        {letters.map((ch, i) => {
          const p = k(lt, 0.02 + i * 0.035, 0.34 + i * 0.035, E.overshoot);
          return <span key={i} style={{...big, display: 'inline-block', transform: `translateY(${(1 - p) * -900}px) rotate(${(1 - p) * (i % 2 ? 20 : -20)}deg)`,
            textShadow: '0 20px 60px rgba(0,0,0,0.7)'}}>{ch}</span>;
        })}
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, top: H / 2 + 170, display: 'flex', justifyContent: 'center'}}>
        <Sub text={WORDS[1].sub} p={k(lt, 0.35, 0.8, (x) => x)} color={C.warn} />
      </div>
    </div>
  );
};

const streaks = (() => {
  const r = rng(21);
  return Array.from({length: 38}, () => ({y: r() * H, v: 1500 + r() * 3600, w: 80 + r() * 520, o: r(), c: r() > 0.8 ? C.violet : C.accent}));
})();
const Wires: React.FC<{lt: number}> = ({lt}) => {
  const p = k(lt, 0, 0.3, E.out);
  const out = k(lt, 0.86, 1.0, E.in);
  const x = lerp(1600, 0, p) + lerp(0, -1800, out);
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <svg width={W} height={H} style={{position: 'absolute'}}>
        {streaks.map((s, i) => {
          const sx = W - ((lt * s.v + s.o * 3000) % (W + s.w + 400));
          return <rect key={i} x={sx} y={s.y} width={s.w} height={2 + (i % 3)} rx={1.5} fill={s.c} opacity={0.25 + 0.5 * s.o} />;
        })}
      </svg>
      {[0.24, 0.12].map((ghost, gi) => (
        <div key={gi} style={{...big, position: 'absolute', left: 0, right: 0, top: H / 2 - 150, textAlign: 'center',
          transform: `translateX(${x + (1 - p) * (gi + 1) * 260}px)`, opacity: ghost * (1 - p) * 3, color: C.accent}}>WIRES</div>
      ))}
      <div style={{...big, position: 'absolute', left: 0, right: 0, top: H / 2 - 150, textAlign: 'center', transform: `translateX(${x}px) skewX(${(1 - p) * -18}deg)`}}>WIRES</div>
      <div style={{position: 'absolute', left: 0, right: 0, top: H / 2 + 170, display: 'flex', justifyContent: 'center'}}>
        <Sub text={WORDS[2].sub} p={k(lt, 0.3, 0.8, (x2) => x2)} />
      </div>
    </div>
  );
};

const Movers: React.FC<{lt: number}> = ({lt}) => {
  const p = k(lt, 0.05, 0.6, E.out);
  const pct = 176.97 * p;
  const r = rng(99);
  const bars = Array.from({length: 48}, (_, i) => 0.2 + 0.8 * r() * Math.abs(Math.sin(i * 0.7 + lt * 6)));
  const zoom = k(lt, 0, 0.3, E.overshoot);
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <svg width={W} height={H} style={{position: 'absolute', opacity: 0.55}}>
        {bars.map((b, i) => {
          const h = b * 520 * k(lt, 0.02 * (i % 12), 0.4 + 0.02 * (i % 12));
          return <rect key={i} x={i * 40 + 4} y={H - h} width={30} height={h} rx={3} fill={i % 7 === 3 ? C.neg : C.pos} opacity={0.18 + 0.4 * b} />;
        })}
      </svg>
      <div style={{position: 'absolute', left: 0, right: 0, top: H / 2 - 260, textAlign: 'center', fontFamily: F.mono, fontSize: 40, letterSpacing: 26, color: C.text2,
        opacity: k(lt, 0, 0.2)}}>MOVERS</div>
      <div style={{...big, position: 'absolute', left: 0, right: 0, top: H / 2 - 170, textAlign: 'center', color: C.pos, fontSize: 280,
        transform: `scale(${lerp(2.4, 1, zoom)})`, textShadow: `0 0 80px ${C.pos}66`, fontVariantNumeric: 'tabular-nums'}}>
        +{pct.toFixed(2)}%
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, top: H / 2 + 140, display: 'flex', justifyContent: 'center'}}>
        <Sub text={WORDS[3].sub} p={k(lt, 0.4, 0.7, (x) => x)} color={C.pos} />
      </div>
    </div>
  );
};

export const Kinetic: React.FC<{t: number}> = ({t}) => {
  if (t < A - 0.05 || t > B + 0.05) return null;
  const idx = Math.min(3, Math.floor(t - A));
  const lt = t - WORDS[idx].at;
  // whip out at the end of the section
  const whip = k(t, B - 0.3, B, E.in);
  const rgb = Math.max(0, 1 - lt / 0.18) * 14;
  const shakeX = noise1(t * 30, 5) * 6 * Math.max(0, 1 - lt / 0.25);
  return (
    <div style={{position: 'absolute', inset: 0, transform: `translateX(${-whip * W * 1.2}px)`, filter: whip > 0.02 ? `blur(${whip * 30}px)` : undefined,
      opacity: k(t, A, A + 0.08)}}>
      <Floor t={t} />
      <div style={{position: 'absolute', inset: 0, background: `radial-gradient(ellipse 45% 35% at 50% 45%, ${C.void}CC 10%, transparent 75%)`}} />
      <RGB amt={rgb} style={{position: 'absolute', inset: 0, transform: `translateX(${shakeX}px)`}}>
        <div style={{position: 'absolute', inset: 0, width: W, height: H}}>
          {idx === 0 && <Halts lt={lt} />}
          {idx === 1 && <Filings lt={lt} />}
          {idx === 2 && <Wires lt={lt} />}
          {idx === 3 && <Movers lt={lt} />}
        </div>
      </RGB>
    </div>
  );
};
