import React from 'react';
import {C, F} from '../../config/theme';
import {E, H, S, W, clamp, k, lerp} from '../core';
import {rng} from '../../lib/anim';

// 11-16 s: 660 names as a rotating 3D sphere (core blue, extended violet),
// which morphs into a live sector heatmap, ripples, and we zoom into one tile.
const A = S.universe;
const N = 660;
const COLS = 33;
const ROWS = 20;
const CELL = 46;
const GAP = 4;
const GX = (W - COLS * (CELL + GAP)) / 2;
const GY = (H - ROWS * (CELL + GAP)) / 2 + 20;
const TARGET = 13 * COLS + 21; // the tile we dive into

const PTS = (() => {
  const r = rng(660);
  const golden = Math.PI * (3 - Math.sqrt(5));
  const order = Array.from({length: N}, (_, i) => i).sort(() => r() - 0.5);
  return Array.from({length: N}, (_, i) => {
    const y = 1 - (i / (N - 1)) * 2;
    const rad = Math.sqrt(1 - y * y);
    const th = golden * i;
    const g = order[i];
    const chg = (r() - 0.46) * 0.16 + (r() > 0.95 ? (r() - 0.3) * 0.6 : 0);
    return {x: Math.cos(th) * rad, y, z: Math.sin(th) * rad, core: r() < 175 / N, g, chg, col: g % COLS, row: Math.floor(g / COLS)};
  });
})();
PTS.forEach((p) => {
  if (p.g === TARGET) {
    p.chg = 0.042;
    p.core = true;
  }
});

const heat = (c: number) => {
  const m = clamp(Math.abs(c) / 0.08);
  const base = c >= 0 ? [63, 185, 107] : [229, 72, 77];
  const dark = [22, 28, 38];
  const rgb = dark.map((d, i) => Math.round(lerp(d, base[i], 0.25 + 0.75 * m)));
  return `rgb(${rgb.join(',')})`;
};

export const Universe: React.FC<{t: number}> = ({t}) => {
  if (t < A - 0.3 || t > S.engine + 0.05) return null;
  const lt = t - A;
  const burst = k(lt, 0, 0.7, E.out);
  const rotY = lt * 0.9 + 0.6;
  const rotX = 0.35 + Math.sin(lt * 0.6) * 0.15;
  const R = 400 * burst;
  const morph = k(lt, 2.1, 3.1, E.inOut);
  const ripple = lt - 3.3;
  const dive = k(lt, 4.3, 5.0, E.in);
  const tcx = GX + (TARGET % COLS) * (CELL + GAP) + CELL / 2;
  const tcy = GY + Math.floor(TARGET / COLS) * (CELL + GAP) + CELL / 2;
  const scale = lerp(1, 34, dive);
  const cy = Math.cos(rotY), sy = Math.sin(rotY), cx = Math.cos(rotX), sx = Math.sin(rotX);
  const proj = PTS.map((p) => {
    const x1 = p.x * cy + p.z * sy;
    const z1 = -p.x * sy + p.z * cy;
    const y1 = p.y * cx - z1 * sx;
    const z2 = p.y * sx + z1 * cx;
    const f = 1400 / (1400 + z2 * R);
    return {sx: W / 2 + x1 * R * f, sy: H / 2 + y1 * R * f, z: z2, f};
  });
  const labels = 1 - k(lt, 2.0, 2.4);
  const count = Math.round(N * k(lt, 0.1, 1.2, E.out));
  const draw = [...PTS.keys()].sort((a, b) => proj[a].z - proj[b].z);
  return (
    <div style={{position: 'absolute', inset: 0, transformOrigin: `${tcx}px ${tcy}px`, transform: `scale(${scale})`,
      opacity: k(lt, -0.3, 0.05)}}>
      <svg width={W} height={H} style={{position: 'absolute', overflow: 'visible'}}>
        {/* orbit rings */}
        <g opacity={0.5 * labels * burst}>
          <ellipse cx={W / 2} cy={H / 2} rx={R * 1.28} ry={R * 0.34} fill="none" stroke={C.borderStrong} strokeDasharray="4 10" transform={`rotate(-14 ${W / 2} ${H / 2})`} />
          <ellipse cx={W / 2} cy={H / 2} rx={R * 1.5} ry={R * 0.46} fill="none" stroke={C.border} transform={`rotate(10 ${W / 2} ${H / 2})`} />
        </g>
        {draw.map((i) => {
          const p = PTS[i];
          const q = proj[i];
          const gx = GX + p.col * (CELL + GAP);
          const gy = GY + p.row * (CELL + GAP);
          const dl = (p.col + p.row) / (COLS + ROWS);
          const m = clamp(morph * 1.6 - dl * 0.6);
          const em = E.inOut(m);
          const size = lerp((p.core ? 8 : 5.5) * q.f, CELL, em);
          const x = lerp(q.sx - size / 2, gx, em);
          const y = lerp(q.sy - size / 2, gy, em);
          const depth = clamp((q.z + 1) / 2);
          const sphereCol = p.core ? C.accent : C.violet;
          const d = Math.hypot(p.col - 16, p.row - 9.5);
          const wave = ripple > 0 ? Math.exp(-(((ripple * 26 - d) / 2.2) ** 2)) : 0;
          const fill = m < 0.5 ? sphereCol : heat(p.chg);
          const op = m < 0.5 ? 0.35 + 0.65 * depth : 1;
          return (
            <rect key={i} x={x} y={y - wave * 10} width={size} height={size} rx={lerp(size / 2, 5, em)} fill={fill} opacity={op}
              stroke={wave > 0.3 ? '#FFFFFF' : 'none'} strokeOpacity={wave * 0.6} strokeWidth={1.5} />
          );
        })}
        {/* target highlight */}
        <g opacity={k(lt, 3.8, 4.1)}>
          <rect x={tcx - CELL / 2 - 5} y={tcy - CELL / 2 - 5} width={CELL + 10} height={CELL + 10} rx={8} fill="none" stroke="#FFFFFF" strokeWidth={2.5} filter="url(#glow)" />
        </g>
      </svg>
      {/* tile label */}
      <div style={{position: 'absolute', left: tcx - CELL / 2 + 3, top: tcy - 14, width: CELL - 6, textAlign: 'center', fontFamily: F.mono, fontSize: 9, lineHeight: 1.2,
        fontWeight: 600, color: '#FFFFFF', opacity: k(lt, 3.9, 4.2)}}>VRTX<br />+4.2%</div>
      {/* headline counters */}
      <div style={{position: 'absolute', left: 150, top: 330, opacity: labels}}>
        <div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 170, letterSpacing: -8, color: C.text, lineHeight: 1, fontVariantNumeric: 'tabular-nums'}}>{count}</div>
        <div style={{fontFamily: F.mono, fontSize: 22, letterSpacing: 8, color: C.muted, marginTop: 10}}>NAMES COVERED</div>
      </div>
      <div style={{position: 'absolute', right: 150, top: 380, textAlign: 'right', opacity: labels * k(lt, 0.5, 0.9), fontFamily: F.mono, fontSize: 22, letterSpacing: 5, lineHeight: 2}}>
        <div><span style={{color: C.accent}}>●</span> <span style={{color: C.text}}>175</span> <span style={{color: C.muted}}>CORE</span></div>
        <div><span style={{color: C.violet}}>●</span> <span style={{color: C.text}}>485</span> <span style={{color: C.muted}}>EXTENDED</span></div>
        <div style={{color: C.faint}}>SIC 2834 · 2835 · 2836 · 8731</div>
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, top: GY - 64, textAlign: 'center', fontFamily: F.mono, fontSize: 20, letterSpacing: 8, color: C.text2,
        opacity: k(lt, 2.8, 3.1) * (1 - dive)}}>
        THE WHOLE SECTOR · LIVE · SIZE = CAP · COLOUR = TODAY
      </div>
    </div>
  );
};
