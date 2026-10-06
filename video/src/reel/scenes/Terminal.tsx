import React from 'react';
import {C, F} from '../../config/theme';
import {E, H, S, W, clamp, k, lerp} from '../core';
import {rng} from '../../lib/anim';
import {Mark} from '../Mark';

// 21-26 s: the terminal assembles in 3D - panels fly in from depth, the
// command bar types a mnemonic, candles print one by one, then the camera
// settles frontal and whips out.
const A = S.terminal;
const PW = 1560;
const PH = 880;

const CANDLES = (() => {
  const r = rng(4);
  let c = 410;
  return Array.from({length: 64}, (_, i) => {
    const o = c;
    c = c * (1 + (r() - 0.44) * 0.028 + (i === 44 ? 0.05 : 0));
    const hi = Math.max(o, c) * (1 + r() * 0.01);
    const lo = Math.min(o, c) * (1 - r() * 0.01);
    return {o, c, hi, lo, v: 0.3 + r() * 0.7 + (i === 44 ? 1.2 : 0)};
  });
})();
const lo = Math.min(...CANDLES.map((d) => d.lo));
const hi = Math.max(...CANDLES.map((d) => d.hi));

const Panel: React.FC<{t: number; at: number; x: number; y: number; w: number; h: number; title?: string; children?: React.ReactNode; z?: number}> = ({
  t, at, x, y, w, h, title, children, z = 700,
}) => {
  const p = k(t, at, at + 0.55, E.out);
  return (
    <div style={{position: 'absolute', left: x, top: y, width: w, height: h, borderRadius: 16, background: C.surface, border: `1px solid ${C.border}`,
      transform: `translateZ(${(1 - p) * -z}px) translateY(${(1 - p) * 60}px)`, opacity: p, overflow: 'hidden',
      boxShadow: '0 40px 100px rgba(0,0,0,0.55)'}}>
      {title && <div style={{fontFamily: F.mono, fontSize: 13, letterSpacing: 3, color: C.muted, padding: '16px 20px 0'}}>{title}</div>}
      {children}
    </div>
  );
};

export const Terminal: React.FC<{t: number}> = ({t}) => {
  if (t < A - 0.05 || t > S.copilot + 0.05) return null;
  const lt = t - A;
  const settle = k(lt, 0, 3.2, E.inOut);
  const rx = lerp(26, 4, settle);
  const ry = lerp(-24, -3, settle);
  const s = lerp(0.82, 1.0, settle);
  const whip = k(lt, 4.55, 5.0, E.in);
  const cmd = 'VRTX CAT';
  const typed = cmd.slice(0, Math.floor(cmd.length * k(lt, 0.7, 1.15, (x) => x)));
  const enter = k(lt, 1.2, 1.35);
  const ch = {x: 40, y: 250, w: 1000, h: 590};
  const n = Math.floor(CANDLES.length * k(lt, 1.3, 3.0, (x) => x));
  const cw = (ch.w - 80) / CANDLES.length;
  const py = (v: number) => ch.h - 70 - ((v - lo) / (hi - lo)) * (ch.h - 150);
  const sma = CANDLES.map((_, i) => {
    const a = CANDLES.slice(Math.max(0, i - 9), i + 1);
    return a.reduce((q, d) => q + d.c, 0) / a.length;
  });
  const smaPath = sma.slice(0, n).map((v, i) => `${i ? 'L' : 'M'}${40 + i * cw + cw / 2} ${py(v)}`).join('');
  const last = CANDLES[Math.max(0, n - 1)].c;
  const tape = ['XBI 163.32 +0.34%', 'VRTX 458.20 +2.41%', 'REGN 812.05 -0.62%', 'ALNY 301.44 +1.18%', 'BIIB 188.90 +0.95%', 'INSM 96.12 -1.40%', 'MRNA 41.07 +3.02%', 'ARGX 612.30 +0.44%'];
  const tapeX = -((lt * 180) % 1600);
  const r = rng(8);
  return (
    <div style={{position: 'absolute', inset: 0, perspective: 1800, transform: `translateX(${-whip * W * 1.3}px)`, filter: whip > 0.02 ? `blur(${whip * 28}px)` : undefined}}>
      <div style={{position: 'absolute', left: (W - PW) / 2, top: (H - PH) / 2 + 20, width: PW, height: PH, transformStyle: 'preserve-3d',
        transform: `rotateX(${rx}deg) rotateY(${ry}deg) scale(${s})`}}>
        {/* nav */}
        <Panel t={lt} at={0.0} x={0} y={0} w={PW} h={70}>
          <div style={{display: 'flex', alignItems: 'center', gap: 16, padding: '15px 24px'}}>
            <Mark size={40} id="nav" />
            <span style={{fontFamily: F.sans, fontWeight: 700, fontSize: 26, color: C.text}}>Bio<span style={{fontWeight: 500, color: C.accentSoft}}>Term</span></span>
            {['Overview', 'Signals', 'Stock detail', 'Copilot', 'Intelligence', 'Markets', 'Workspace'].map((x, i) => (
              <span key={x} style={{fontFamily: F.sans, fontSize: 17, color: i === 2 ? C.text : C.muted, padding: '6px 12px', borderRadius: 8, background: i === 2 ? C.surface2 : undefined, marginLeft: i ? 0 : 30}}>{x}</span>
            ))}
          </div>
        </Panel>
        {/* command bar */}
        <Panel t={lt} at={0.15} x={0} y={88} w={PW} h={58}>
          <div style={{fontFamily: F.mono, fontSize: 22, padding: '15px 24px', color: typed ? C.text : C.faint}}>
            <span style={{color: C.accent}}>›</span> {typed || 'Ticker or command · VRTX CAT · SCR · MKT · CMP A B'}
            <span style={{opacity: Math.floor(lt * 4) % 2 ? 0 : 1, color: C.accent}}>▍</span>
            <span style={{float: 'right', color: C.pos, opacity: enter, fontSize: 16, letterSpacing: 3}}>↵ STOCK DETAIL · CATALYSTS</span>
          </div>
        </Panel>
        {/* KPI cards */}
        {[
          ['LAST', `$${last.toFixed(2)}`, C.text, '+2.41%'],
          ['FOCUS SCORE', '0.937', C.text, 'RANK #1'],
          ['SIGNAL', 'STRONG BUY', C.pos, 'NET +0.62'],
          ['CASH RUNWAY', '9.4 q', C.text, 'FUNDED'],
        ].map(([lab, val, col, sub], i) => (
          <Panel key={lab} t={lt} at={0.3 + i * 0.07} x={1060 + (i % 2) * 255} y={164 + Math.floor(i / 2) * 150} w={240} h={134}>
            <div style={{padding: '14px 20px', fontFamily: F.mono, fontSize: 13, letterSpacing: 2.5, color: C.muted}}>{lab}</div>
            <div style={{padding: '0 20px', fontFamily: F.sans, fontWeight: 700, fontSize: i === 2 ? 30 : 38, color: col}}>{val}</div>
            <div style={{padding: '6px 20px', fontFamily: F.mono, fontSize: 13, color: i === 0 ? C.pos : C.faint}}>{sub}</div>
          </Panel>
        ))}
        {/* chart */}
        <Panel t={lt} at={0.45} x={0} y={164} w={1040} h={ch.h + 86} title="VRTX · 1Y · CANDLES · SMA 10 · SIGNALS" z={900}>
          <svg width={ch.w} height={ch.h} style={{position: 'absolute', left: 0, top: 50}}>
            {[0.25, 0.5, 0.75].map((g) => <line key={g} x1={40} x2={ch.w - 40} y1={ch.h * g} y2={ch.h * g} stroke={C.grid} />)}
            {CANDLES.slice(0, n).map((d, i) => {
              const x = 40 + i * cw + cw / 2;
              const up = d.c >= d.o;
              const pop = clamp((n - i) / 3);
              return (
                <g key={i} opacity={pop}>
                  <line x1={x} x2={x} y1={py(d.hi)} y2={py(d.lo)} stroke={up ? C.pos : C.neg} strokeWidth={1.5} />
                  <rect x={x - cw * 0.34} y={py(Math.max(d.o, d.c))} width={cw * 0.68} height={Math.max(2, Math.abs(py(d.o) - py(d.c)))} fill={up ? C.pos : C.neg} rx={1} />
                  <rect x={x - cw * 0.34} y={ch.h - 60 * d.v * 0.5} width={cw * 0.68} height={60 * d.v * 0.5} fill={up ? C.pos : C.neg} opacity={0.25} />
                </g>
              );
            })}
            <path d={smaPath} fill="none" stroke={C.accent} strokeWidth={2.5} />
            {n > 45 && (
              <g opacity={k(lt, 2.55, 2.75)}>
                <path d={`M${40 + 44 * cw + cw / 2} ${py(CANDLES[44].lo) + 38} l-12 18 h24 z`} fill={C.pos} />
                <text x={40 + 44 * cw + cw / 2} y={py(CANDLES[44].lo) + 80} textAnchor="middle" fontFamily={F.mono} fontSize={14} fill={C.pos}>BUY</text>
              </g>
            )}
            {n > 20 && <circle cx={40 + 20 * cw + cw / 2} cy={py(CANDLES[20].hi) - 26} r={7} fill={C.warn} opacity={k(lt, 1.9, 2.1)} />}
          </svg>
        </Panel>
        {/* heatmap mini */}
        <Panel t={lt} at={0.6} x={1060} y={478} w={495} h={362} title="SECTOR · TODAY" z={900}>
          <svg width={495} height={320} style={{position: 'absolute', top: 44}}>
            {Array.from({length: 48}, (_, i) => {
              const c = r() - 0.45;
              const p = k(lt, 0.9 + (i % 12) * 0.03 + Math.floor(i / 12) * 0.05, 1.2 + (i % 12) * 0.03 + Math.floor(i / 12) * 0.05, E.overshoot);
              const x = 20 + (i % 8) * 58;
              const y = 10 + Math.floor(i / 8) * 50;
              return <rect key={i} x={x + 25 * (1 - p)} y={y + 22 * (1 - p)} width={52 * p} height={44 * p} rx={5} fill={c > 0 ? C.pos : C.neg} opacity={0.25 + Math.min(0.75, Math.abs(c) * 1.6)} />;
            })}
          </svg>
        </Panel>
      </div>
      {/* ticker tape (screen space) */}
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 96, height: 44, overflow: 'hidden', opacity: k(lt, 0.8, 1.2) * (1 - whip),
        borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}`, background: `${C.bg}CC`}}>
        <div style={{position: 'absolute', left: tapeX, top: 10, whiteSpace: 'nowrap', fontFamily: F.mono, fontSize: 18, letterSpacing: 1}}>
          {[...tape, ...tape, ...tape].map((x, i) => {
            const [tk, px, ch2] = x.split(' ');
            return <span key={i} style={{marginRight: 44}}><span style={{color: C.text}}>{tk}</span> <span style={{color: C.text2}}>{px}</span> <span style={{color: ch2.startsWith('-') ? C.neg : C.pos}}>{ch2}</span></span>;
          })}
        </div>
      </div>
    </div>
  );
};
