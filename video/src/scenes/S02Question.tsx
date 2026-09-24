import React, {useMemo} from 'react';
import {AbsoluteFill} from 'remotion';
import {C, F, TYPE} from '../config/theme';
import {BEAT} from '../config/timing';
import {useLayout} from '../config/layout';
import {E, lerp, prog, useTime} from '../lib/anim';
import {KineticText} from '../components/KineticText';
import {buildNetwork, netFrame} from '../components/DataNetwork';
import {PRIMARY} from '../data/network';
import {marketState} from './marketState';

const N = 24;
// BioTerm's actual source types ride the stream.
const TOKENS = ['8-K', 'NCT05933577', 'RSS', 'FORM 4', 'ClinicalTrials.gov', '10-Q', 'openFDA', 'EDGAR', 'ESMO', 'PRESS RELEASE'];
const TOKEN_STRANDS = [2, 5, 7, 9, 12, 14, 16, 19, 21, 23];

/**
 * SCENE 02 (4-7s) the question. The camera falls into the spike; the price line
 * splits into a stream of information, which then folds into the first edges
 * of the network (match cut into scene 03).
 */
export const S02Question: React.FC = () => {
  const t = useTime();
  const L = useLayout();
  const {u, w, h, cx, cy, vertical} = L;
  const net = useMemo(() => buildNetwork(L), [w, h]);
  if (t < BEAT.streamStart - 0.05 || t > BEAT.streamToEdges[1] + 0.05) {
    return t >= 4.3 && t < 6.7 ? <Question t={t} /> : null;
  }
  const m = marketState(t, L);
  const M = m.toScreen(m.mid);
  const dir = m.dir;
  const nrm = {x: -dir.y, y: dir.x};
  const reach = 1.4 * Math.max(w, h);
  const grow = E.out(prog(t, BEAT.streamStart, 5.9));
  const gap = (18 + 10 * prog(t, 5.9, 6.5)) * u * grow;
  const morph = E.inOut(prog(t, BEAT.streamToEdges[0], BEAT.streamToEdges[1]));

  // hand-off: strands land on the primary nodes in projection order (no crossings)
  const target = netFrame(net, BEAT.streamToEdges[1], L);
  const ranked = PRIMARY.map((_, i) => ({i, q: (target.primary[i].x - cx) * nrm.x + (target.primary[i].y - cy) * nrm.y})).sort((a, b) => a.q - b.q);
  const landing = new Map<number, number>();
  ranked.forEach(({i}, r) => landing.set(Math.round((r * (N - 1)) / (ranked.length - 1)), i));

  const strands = Array.from({length: N}, (_, i) => {
    const off = (i - (N - 1) / 2) * gap;
    const base = {x: M.x + nrm.x * off, y: M.y + nrm.y * off};
    const A0 = {x: base.x - dir.x * reach, y: base.y - dir.y * reach};
    const B0 = {x: base.x + dir.x * reach, y: base.y + dir.y * reach};
    const node = landing.get(i);
    const tgtB = node === undefined ? {x: cx, y: cy} : target.primary[node];
    const A = {x: lerp(A0.x, cx, morph), y: lerp(A0.y, cy, morph)};
    const B = {x: lerp(B0.x, tgtB.x, morph), y: lerp(B0.y, tgtB.y, morph)};
    const centrality = 1 - Math.abs(i - (N - 1) / 2) / (N / 2);
    const op = grow * (0.18 + 0.5 * centrality) * (node === undefined ? 1 - morph : lerp(1, 0.9, morph));
    return {A, B, op, i, base, lit: node !== undefined && morph > 0.5};
  });

  return (
    <AbsoluteFill>
      <svg width={w} height={h} style={{position: 'absolute'}}>
        {strands.map(({A, B, op, i, lit}) => (
          <g key={i}>
            <line x1={A.x} y1={A.y} x2={B.x} y2={B.y} stroke={lit ? C.borderStrong : C.accent} strokeOpacity={op * (lit ? 1.4 : 0.55)} strokeWidth={1.1 * u} />
            {i % 2 === 0 && (
              <line
                x1={A.x} y1={A.y} x2={B.x} y2={B.y} stroke={C.accent} strokeOpacity={op * (1 - morph)} strokeWidth={1.6 * u}
                strokeDasharray={`${(10 + (i % 5) * 6) * u} ${(26 + (i % 3) * 14) * u}`}
                strokeDashoffset={t * -(420 + (i % 4) * 90) * u}
              />
            )}
          </g>
        ))}
        {TOKEN_STRANDS.map((si, k) => {
          const st = strands[si];
          const q = (((t - BEAT.streamStart) * 0.16 + k * 0.137) % 1) * 2 - 1; // along the strand
          const x = st.base.x + dir.x * q * 0.62 * Math.max(w, h);
          const y = st.base.y + dir.y * q * 0.62 * Math.max(w, h);
          const nearText = Math.min(1, Math.max(Math.abs(x - cx) / (vertical ? 420 : 560), Math.abs(y - cy) / (vertical ? 240 : 120)) / u);
          const op = grow * (1 - morph) * 0.75 * nearText;
          return (
            <g key={k} opacity={op}>
              <circle cx={x} cy={y} r={2.4 * u} fill={C.accent} />
              <text x={x + 9 * u} y={y + 4 * u} fill={C.accentSoft} fontFamily={F.mono} fontSize={13 * u} letterSpacing={1.2 * u}>{TOKENS[k]}</text>
            </g>
          );
        })}
      </svg>
      <Question t={t} />
    </AbsoluteFill>
  );
};

const Question: React.FC<{t: number}> = ({t}) => {
  const L = useLayout();
  const {u, vertical} = L;
  const show = prog(t, BEAT.question - 0.2, BEAT.question + 0.3) * (1 - prog(t, BEAT.questionOut - 0.3, BEAT.questionOut));
  const size = (vertical ? 104 : TYPE.display) * u;
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
      <div
        style={{
          position: 'absolute', width: (vertical ? 1000 : 1400) * u, height: (vertical ? 520 : 300) * u, borderRadius: '50%',
          background: `radial-gradient(closest-side, ${C.void}F2 0%, ${C.void}CC 55%, ${C.void}00 100%)`, opacity: show,
        }}
      />
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 * u}}>
        {vertical ? (
          <>
            <KineticText t={t} text="BUT WHY" start={BEAT.question} end={BEAT.questionOut} size={size} accentWords={['WHY']} />
            <KineticText t={t} text="DID IT MOVE?" start={BEAT.question + 0.2} end={BEAT.questionOut} size={size} />
          </>
        ) : (
          <KineticText t={t} text="BUT WHY DID IT MOVE?" start={BEAT.question} end={BEAT.questionOut} size={size} accentWords={['WHY']} stagger={0.09} />
        )}
      </div>
    </AbsoluteFill>
  );
};
