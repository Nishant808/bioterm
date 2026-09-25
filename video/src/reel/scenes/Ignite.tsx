import React from 'react';
import {C, F} from '../../config/theme';
import {E, H, W, beatPulse, clamp, k, lerp, prog, win} from '../core';
import {rng} from '../../lib/anim';

// 0-3 s: a point of light pulses on the beat, stretches into a line, and the
// line becomes a signal trace whose spike we dive into.
const X0 = 210;
const X1 = W - 210;
const CY = H / 2;
const SPIKE = 0.74; // spike position along the trace

const trace = (() => {
  const r = rng(11);
  const pts: [number, number][] = [];
  const n = 240;
  let y = 0;
  for (let i = 0; i <= n; i++) {
    const u = i / n;
    y = y * 0.82 + (r() - 0.5) * 9;
    const spike = Math.exp(-(((u - SPIKE) / 0.012) ** 2)) * -330 + Math.exp(-(((u - SPIKE - 0.018) / 0.01) ** 2)) * 90;
    const bump = Math.exp(-(((u - 0.34) / 0.02) ** 2)) * -40;
    pts.push([lerp(X0, X1, u), CY + y + spike + bump + Math.sin(u * 40) * 3]);
  }
  return pts;
})();
const PATH = trace.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join('');
const peak = trace.reduce((a, p) => (p[1] < a[1] ? p : a), trace[0]);

export const Ignite: React.FC<{t: number}> = ({t}) => {
  if (t > 3.25) return null;
  const dot = 1 - k(t, 0.9, 1.15);
  const r = 5 + 14 * beatPulse(t, 0) * (t < 1.0 ? 1 : 0);
  const line = k(t, 0.95, 1.45, E.inOut);
  const draw = k(t, 1.35, 2.55, E.inOut);
  const head = Math.round(draw * (trace.length - 1));
  const [hx, hy] = trace[head];
  // dive into the spike: scale around the peak
  const dive = k(t, 2.55, 3.05, E.in);
  const s = lerp(1, 9, dive);
  const blur = dive * 10;
  const labels = win(t, 1.2, 2.9, 0.3, 0.2);
  const count = Math.floor(draw * 1_000_000);
  const ms = Math.floor(clamp(prog(t, 1.2, 3)) * 7123);
  return (
    <div style={{position: 'absolute', inset: 0, transformOrigin: `${peak[0]}px ${peak[1]}px`, transform: `scale(${s})`, filter: blur > 0.3 ? `blur(${blur}px)` : undefined}}>
      {/* dotted field */}
      <svg width={W} height={H} style={{position: 'absolute', opacity: 0.5 * k(t, 1.0, 1.8)}}>
        {Array.from({length: 17}, (_, j) =>
          Array.from({length: 31}, (_, i) => (
            <circle key={`${i}-${j}`} cx={60 + i * 60} cy={60 + j * 60} r={1.1} fill={C.borderStrong}
              opacity={0.35 + 0.65 * Math.exp(-(((i - 15) ** 2 + (j - 8) ** 2) / 90))} />
          )),
        )}
      </svg>
      <svg width={W} height={H} style={{position: 'absolute', overflow: 'visible'}}>
        {/* the point */}
        <circle cx={W / 2} cy={CY} r={r * dot} fill="#FFFFFF" filter="url(#glow-lg)" opacity={dot} />
        {/* the line */}
        <line x1={W / 2 - (W / 2 - X0) * line} x2={W / 2 + (X1 - W / 2) * line} y1={CY} y2={CY}
          stroke={C.borderStrong} strokeWidth={1.5} opacity={1 - draw * 0.6} />
        {/* the trace */}
        <path d={PATH} fill="none" stroke={C.accent} strokeWidth={3} pathLength={1} strokeDasharray="1 1"
          strokeDashoffset={1 - draw} filter="url(#glow)" strokeLinejoin="round" />
        <path d={PATH} fill="none" stroke="#FFFFFF" strokeWidth={1.2} pathLength={1} strokeDasharray="1 1"
          strokeDashoffset={1 - draw} opacity={0.8} />
        {draw > 0 && draw < 1 && <circle cx={hx} cy={hy} r={7} fill="#FFFFFF" filter="url(#glow-lg)" />}
        {/* peak marker */}
        {draw > SPIKE + 0.02 && (
          <g opacity={k(t, 2.2, 2.35)}>
            <circle cx={peak[0]} cy={peak[1]} r={10 + 40 * k(t, 2.25, 2.9)} fill="none" stroke={C.pos} strokeWidth={2}
              opacity={1 - k(t, 2.25, 2.9)} />
            <circle cx={peak[0]} cy={peak[1]} r={6} fill={C.pos} filter="url(#glow)" />
          </g>
        )}
      </svg>
      <div style={{position: 'absolute', left: X0, top: CY + 120, fontFamily: F.mono, fontSize: 18, letterSpacing: 4, color: C.muted, opacity: labels}}>
        SIGNAL <span style={{color: C.text}}>{String(count).padStart(7, '0')}</span>
      </div>
      <div style={{position: 'absolute', right: W - X1, top: CY + 120, fontFamily: F.mono, fontSize: 18, letterSpacing: 4, color: C.muted, opacity: labels}}>
        09:30:0{Math.floor(ms / 1000)}.<span style={{color: C.text}}>{String(ms % 1000).padStart(3, '0')}</span> ET
      </div>
      <div style={{position: 'absolute', left: peak[0] + 26, top: peak[1] - 16, fontFamily: F.mono, fontSize: 16, letterSpacing: 3, color: C.pos,
        opacity: k(t, 2.3, 2.45), whiteSpace: 'nowrap'}}>
        ▲ ANOMALY
      </div>
    </div>
  );
};
