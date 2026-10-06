import React from 'react';
import {C, F} from '../../config/theme';
import {E, H, S, W, clamp, k, lerp} from '../core';
import {rng} from '../../lib/anim';
import {RGB} from '../fx';

// 16-21 s: the signal engine. 39 detectors in six evidence families bloom as a
// radial chart, the combination formula typesets itself, the needle swings,
// and the call stamps in.
const A = S.engine;
const CX = W / 2 + 360;
const CY = H / 2 + 30;
const FAM = [
  {name: 'TECHNICAL', n: 11}, {name: 'EVENT', n: 8}, {name: 'CAPITAL', n: 5},
  {name: 'PEOPLE', n: 6}, {name: 'NEWS', n: 5}, {name: 'FLOW', n: 4},
];
const BARS = (() => {
  const r = rng(39);
  const out: {a0: number; a1: number; s: number; buy: boolean; fam: number; i: number}[] = [];
  const gap = 0.07;
  const total = Math.PI * 2 - gap * FAM.length;
  const per = total / 39;
  let a = -Math.PI / 2;
  let idx = 0;
  FAM.forEach((f, fi) => {
    for (let j = 0; j < f.n; j++) {
      const buy = r() > 0.28;
      out.push({a0: a + per * 0.12, a1: a + per * 0.88, s: 0.25 + r() * 0.75, buy, fam: fi, i: idx++});
      a += per;
    }
    a += gap;
  });
  return out;
})();
const famArc = FAM.map((_, fi) => {
  const bs = BARS.filter((b) => b.fam === fi);
  return {a0: bs[0].a0, a1: bs[bs.length - 1].a1};
});

const arc = (r0: number, r1: number, a0: number, a1: number) => {
  const p = (r: number, a: number) => `${CX + Math.cos(a) * r} ${CY + Math.sin(a) * r}`;
  const large = a1 - a0 > Math.PI ? 1 : 0;
  return `M${p(r0, a0)} L${p(r1, a0)} A${r1} ${r1} 0 ${large} 1 ${p(r1, a1)} L${p(r0, a1)} A${r0} ${r0} 0 ${large} 0 ${p(r0, a0)}Z`;
};

const FORMULA = ['bull', ' = ', '1 − ', 'Π', '(1 − s', 'ᵢ', ')'];

export const Engine: React.FC<{t: number}> = ({t}) => {
  if (t < A - 0.05 || t > S.terminal + 0.05) return null;
  const lt = t - A;
  const rot = lt * 6;
  const inner = 150;
  const collapse = k(lt, 4.45, 5.0, E.in);
  const net = 0.62 * k(lt, 1.6, 2.9, E.overshoot);
  const stamp = k(lt, 3.0, 3.25, E.out);
  const stampS = lerp(1.9, 1, stamp);
  const needle = lerp(-90, 90, (net + 1) / 2);
  const g0 = k(lt, 0.0, 0.4, E.out);
  return (
    <div style={{position: 'absolute', inset: 0, opacity: 1 - k(lt, 4.8, 5.0)}}>
      <svg width={W} height={H} style={{position: 'absolute', overflow: 'visible'}}>
        <g transform={`rotate(${rot} ${CX} ${CY})`} opacity={1 - collapse}>
          {/* guide rings */}
          {[inner, inner + 100, inner + 200, inner + 270].map((r, i) => (
            <circle key={i} cx={CX} cy={CY} r={r * g0 * (1 - collapse)} fill="none" stroke={C.border} strokeDasharray={i === 3 ? '2 8' : undefined} />
          ))}
          {BARS.map((b) => {
            const p = k(lt, 0.25 + b.i * 0.02, 0.85 + b.i * 0.02, E.overshoot);
            const len = b.s * 250 * p * (1 - collapse);
            const pulse = 1 + 0.06 * Math.sin(lt * 7 + b.i);
            return <path key={b.i} d={arc(inner, inner + 6 + len * pulse, b.a0, b.a1)} fill={b.buy ? C.pos : C.neg} opacity={0.35 + 0.65 * b.s} />;
          })}
          {famArc.map((f, fi) => {
            const p = k(lt, 0.6 + fi * 0.08, 1.1 + fi * 0.08);
            return (
              <path key={fi} d={arc(inner - 16, inner - 10, f.a0, lerp(f.a0, f.a1, p))} fill={[C.accent, C.warn, C.violet, '#39C5CF', C.accentSoft, C.pos][fi]} />
            );
          })}
        </g>
        {/* family labels (not rotating, placed at arc centres) */}
        {famArc.map((f, fi) => {
          const a = (f.a0 + f.a1) / 2 + (rot * Math.PI) / 180;
          const r = inner + 300;
          return (
            <text key={fi} x={CX + Math.cos(a) * r} y={CY + Math.sin(a) * r} textAnchor="middle" dominantBaseline="middle" fontFamily={F.mono} fontSize={17}
              letterSpacing={4} fill={C.text2} opacity={k(lt, 0.8 + fi * 0.08, 1.2 + fi * 0.08) * (1 - collapse)}>{FAM[fi].name}</text>
          );
        })}
        {/* centre disc + gauge */}
        <circle cx={CX} cy={CY} r={lerp(inner - 24, 2400, collapse) * g0} fill={C.bg} stroke={C.borderStrong} strokeWidth={1.5} />
        <g opacity={1 - collapse}>
          <path d={`M${CX - 110} ${CY + 20} A110 110 0 0 1 ${CX + 110} ${CY + 20}`} fill="none" stroke={C.border} strokeWidth={12} strokeLinecap="round" />
          <path d={`M${CX - 110} ${CY + 20} A110 110 0 0 1 ${CX + 110} ${CY + 20}`} fill="none" stroke={C.pos} strokeWidth={12} strokeLinecap="round"
            pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - (net + 1) / 2} filter="url(#glow)" />
          <line x1={CX} y1={CY + 20} x2={CX + Math.sin((needle * Math.PI) / 180) * 92} y2={CY + 20 - Math.cos((needle * Math.PI) / 180) * 92}
            stroke="#FFFFFF" strokeWidth={4} strokeLinecap="round" />
          <circle cx={CX} cy={CY + 20} r={8} fill="#FFFFFF" />
          <text x={CX} y={CY + 78} textAnchor="middle" fontFamily={F.sans} fontWeight={700} fontSize={46} fill={C.text}>{net >= 0 ? '+' : ''}{net.toFixed(2)}</text>
          <text x={CX} y={CY + 108} textAnchor="middle" fontFamily={F.mono} fontSize={14} letterSpacing={4} fill={C.muted}>NET SIGNAL</text>
        </g>
      </svg>
      {/* left column: formula + stamp */}
      <div style={{position: 'absolute', left: 150, top: 250, opacity: 1 - collapse}}>
        <div style={{fontFamily: F.mono, fontSize: 20, letterSpacing: 8, color: C.muted, opacity: k(lt, 0.2, 0.5)}}>39 DETECTORS · 6 FAMILIES</div>
        <div style={{display: 'flex', alignItems: 'baseline', marginTop: 30, fontFamily: F.sans, fontSize: 76, fontWeight: 600, color: C.text, letterSpacing: -2}}>
          {FORMULA.map((g, i) => {
            const p = k(lt, 1.0 + i * 0.08, 1.35 + i * 0.08, E.out);
            return (
              <span key={i} style={{display: 'inline-block', whiteSpace: 'pre', opacity: p, transform: `translateY(${(1 - p) * 40}px)`,
                color: g === 'Π' ? C.accent : g === 'bull' ? C.pos : undefined, fontSize: g === 'ᵢ' ? 60 : undefined}}>{g}</span>
            );
          })}
        </div>
        <div style={{fontFamily: F.sans, fontSize: 44, fontWeight: 500, color: C.text2, marginTop: 18, opacity: k(lt, 1.8, 2.2)}}>
          net = <span style={{color: C.pos}}>bull</span> − <span style={{color: C.neg}}>bear</span>
        </div>
        <RGB amt={Math.max(0, 1 - (lt - 3.0) / 0.2) * (lt > 3 ? 12 : 0)} style={{marginTop: 60, display: 'inline-block'}}>
          <div style={{display: 'inline-block', padding: '18px 38px', borderRadius: 14, background: `${C.pos}22`, border: `3px solid ${C.pos}`,
            fontFamily: F.sans, fontWeight: 800, fontSize: 64, letterSpacing: 2, color: C.pos, opacity: stamp,
            transform: `scale(${stampS}) rotate(${lerp(-8, -3, stamp)}deg)`, boxShadow: `0 0 ${60 * stamp}px ${C.pos}55`}}>
            STRONG BUY
          </div>
        </RGB>
        <div style={{fontFamily: F.mono, fontSize: 18, letterSpacing: 5, color: C.muted, marginTop: 30, opacity: k(lt, 3.3, 3.6)}}>
          ≥ 2 FAMILIES AGREE · CALIBRATED BY BACKTEST
        </div>
        <div style={{fontFamily: F.mono, fontSize: 14, letterSpacing: 3, color: C.faint, marginTop: 10, opacity: k(lt, 3.5, 3.8)}}>
          A SCREENING STATE, NOT A RECOMMENDATION
        </div>
      </div>
    </div>
  );
};
