import React from 'react';
import {AbsoluteFill} from 'remotion';
import {C} from '../config/theme';
import {BEAT} from '../config/timing';
import {useLayout} from '../config/layout';
import {E, lerp, prog, useTime} from '../lib/anim';
import {appToScreen} from '../components/TerminalUI';

// Where the converged signals land: the Overview's header, KPI cards and focus rows.
const TARGETS = [
  {vx: 380, vy: 125, at: 0.05},
  ...[462, 791, 1119, 1448].map((vx, i) => ({vx, vy: 250, at: 0.3 + i * 0.08})),
  ...[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((i) => ({vx: 420, vy: 472 + i * 31, at: 0.65 + i * 0.05})),
];
const GOLDEN = 2.39996;

/**
 * SCENE 05 (15-19.6s) the reveal. The graph has collapsed into a tight cluster
 * of nodes; the terminal opens around it (TerminalUI layer), then each node
 * flies to an interface element and becomes it.
 */
export const S05Reveal: React.FC = () => {
  const t = useTime();
  const L = useLayout();
  const {u, cx, cy} = L;
  if (t < BEAT.flash - 0.3 || t > BEAT.appIn + 1.4) return null;
  const flash = Math.max(0, 1 - Math.abs(t - BEAT.flash) / 0.25);
  const clusterIn = E.out(prog(t, BEAT.converge[1] - 0.05, BEAT.converge[1] + 0.15));
  return (
    <AbsoluteFill>
      <svg width={L.w} height={L.h} style={{position: 'absolute'}}>
        <circle cx={cx} cy={cy} r={(10 + 40 * flash) * u} fill={C.accent} opacity={0.3 * flash} />
        {TARGETS.map((g, i) => {
          const a = i * GOLDEN + t * 1.6;
          const r = (9 + (i % 4) * 5) * u;
          const home = {x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r};
          const start = BEAT.appIn - 0.05 + i * 0.012;
          const arrive = BEAT.appIn + g.at;
          const p = E.inOut(prog(t, start, arrive));
          if (p >= 1) return null;
          const to = appToScreen(t, L, g.vx, g.vy);
          const x = lerp(home.x, to.x, p);
          const y = lerp(home.y, to.y, p);
          const q = Math.max(0, p - 0.14);
          return (
            <g key={i} opacity={clusterIn}>
              {p > 0 && <line x1={lerp(home.x, to.x, q)} y1={lerp(home.y, to.y, q)} x2={x} y2={y} stroke={C.accent} strokeOpacity={0.55} strokeWidth={1.6 * u} />}
              <circle cx={x} cy={y} r={7 * u} fill={C.accent} opacity={0.18} />
              <circle cx={x} cy={y} r={3.2 * u} fill={i === 0 ? C.text : C.accentSoft} />
            </g>
          );
        })}
      </svg>
    </AbsoluteFill>
  );
};
