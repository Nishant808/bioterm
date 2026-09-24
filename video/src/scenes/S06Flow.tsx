import React from 'react';
import {AbsoluteFill} from 'remotion';
import {C, F} from '../config/theme';
import {BEAT} from '../config/timing';
import {useLayout} from '../config/layout';
import {E, prog, useTime, windowed} from '../lib/anim';
import {appToScreen, CLICKS, windowRect} from '../components/TerminalUI';

const STEPS = ['SEARCH', 'ENTITY', 'RELATED INFORMATION', 'SCIENTIFIC CONTEXT', 'INTELLIGENCE'];

/**
 * SCENE 06 (19.6-24s) an investigation inside BioTerm, using only real screens:
 * Focus list search -> Stock detail -> News & sentiment -> the watchlist thesis
 * -> the Focus Score. This layer adds the step rail and click feedback; the
 * app states live in TerminalUI.
 */
export const S06Flow: React.FC = () => {
  const t = useTime();
  const L = useLayout();
  const {u, w, h, vertical} = L;
  const S = BEAT.steps;
  if (t < S[0] - 0.4 || t > S[5] + 0.3) return null;
  const railOp = windowed(t, S[0] - 0.2, S[5] + 0.1, 0.3, 0.35);
  const active = S.findIndex((s, i) => t >= s && t < S[i + 1]);
  return (
    <AbsoluteFill>
      <svg width={w} height={h} style={{position: 'absolute'}}>
        {CLICKS.map((c, i) => {
          const p = prog(t, c.t, c.t + 0.45);
          if (p <= 0 || p >= 1) return null;
          const s = appToScreen(c.t, L, c.vx, c.vy); // pinned where the click happened
          const wr = windowRect(t, L);
          if (s.x < wr.x || s.x > wr.x + wr.w || s.y < wr.y || s.y > wr.y + wr.h) return null;
          return (
            <g key={i}>
              <circle cx={s.x} cy={s.y} r={(8 + 30 * E.out(p)) * u} fill="none" stroke={C.accent} strokeWidth={1.6 * u} opacity={1 - p} />
              <circle cx={s.x} cy={s.y} r={5 * u} fill={C.accent} opacity={0.8 * (1 - p)} />
            </g>
          );
        })}
      </svg>
      <div
        style={{
          position: 'absolute', left: 0, right: 0, top: vertical ? 0.845 * h : h - 46 * u, display: 'flex', justifyContent: 'center', flexWrap: 'wrap',
          gap: `${10 * u}px ${18 * u}px`, padding: `0 ${60 * u}px`, opacity: railOp, fontFamily: F.mono, fontSize: 13.5 * u, letterSpacing: 1.8 * u,
        }}
      >
        {STEPS.map((s, i) => {
          const on = i === active;
          const done = i < active;
          const p = E.out(prog(t, S[i], S[i] + 0.25));
          return (
            <span key={s} style={{display: 'flex', alignItems: 'center', gap: 10 * u, color: on ? C.text : done ? C.muted : C.faint}}>
              <span style={{width: 6 * u, height: 6 * u, borderRadius: 3 * u, background: on ? C.accent : done ? C.muted : C.border, transform: `scale(${on ? 1 + 0.4 * (1 - p) : 1})`}} />
              {s}
              {i < STEPS.length - 1 && <span style={{color: C.border, marginLeft: 8 * u}}>—</span>}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
