import React from 'react';
import {AbsoluteFill, interpolateColors} from 'remotion';
import {C, F, TYPE} from '../config/theme';
import {BEAT} from '../config/timing';
import {useLayout} from '../config/layout';
import {EVENT} from '../data/event';
import {E, prog, useTime} from '../lib/anim';
import {KineticText} from '../components/KineticText';
import {chartGeom, MarketChart} from '../components/MarketChart';
import {marketState, SPIKE_I} from './marketState';

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const dLabel = (iso: string) => `${MONTHS[+iso.slice(5, 7) - 1]} ${iso.slice(8)}`;
const niceStep = (span: number) => [5, 10, 20, 40, 50].find((s) => span / s <= 6) ?? 50;

/**
 * SCENE 01 (0-4s) the market move, and the chart layer SCENE 02 dives into.
 * Everything below is a pure function of time, so the layer is continuous
 * across the 4s scene boundary.
 */
export const S01Market: React.FC = () => {
  const t = useTime();
  const L = useLayout();
  const {u, vertical} = L;
  if (t > 7.4) return null;
  const m = marketState(t, L);
  const {rect, vol, bars} = m;

  const termIn = E.out(prog(t, BEAT.terminalIn, 1.2));
  const chrome = termIn * (1 - E.inOut(prog(t, BEAT.chromeOut[0], BEAT.chromeOut[1])));
  const spiking = prog(t, BEAT.spikeStart, BEAT.spikeEnd);
  const lineColor = interpolateColors(prog(t, 4.8, 5.7), [0, 1], [C.pos, C.accent]);
  const lineOut = 1 - E.inOut(prog(t, 6.55, 7.05));

  const step = niceStep(m.domain[1] - m.domain[0]);
  const yTicks: number[] = [];
  for (let v = Math.ceil(m.domain[0] / step) * step; v <= m.domain[1]; v += step) yTicks.push(v);
  const xLabels = [0, 5, 10, 15, 20].map((i) => ({i, text: dLabel(bars[i].date)}));

  const g = chartGeom(bars.length, rect, m.domain);
  const peakShown = E.out(prog(t, BEAT.spikeEnd - 0.02, BEAT.spikeEnd + 0.45));
  const pct = Math.max(0, (m.head / EVENT.prevClose - 1) * 100);
  const dayVol = bars[Math.min(bars.length - 1, Math.round(m.k))].volume;

  // header rows (world space: they ride the camera)
  const hx = rect.x0;
  const hy = rect.y0 - (vertical ? 150 : 118) * u;
  const field = (label: string, value: string, x: number, color: string = C.text, key?: string) => (
    <g key={key ?? label}>
      <text x={x} y={hy + 2 * u} fill={C.faint} fontFamily={F.mono} fontSize={12.5 * u} letterSpacing={2 * u}>{label}</text>
      <text x={x} y={hy + 32 * u} fill={color} fontFamily={F.mono} fontSize={21 * u} fontWeight={500}>{value}</text>
    </g>
  );
  const fx = vertical ? [hx, hx + 250 * u, hx + 520 * u, hx + 760 * u] : [rect.x1 - 700 * u, rect.x1 - 520 * u, rect.x1 - 330 * u, rect.x1 - 120 * u];

  return (
    <AbsoluteFill>
      <svg width={L.w} height={L.h} style={{position: 'absolute'}}>
        <g transform={m.transform} opacity={termIn}>
          {/* terminal header */}
          <g opacity={chrome}>
            <text x={hx} y={hy + (vertical ? -70 : 30) * u} fill={C.text} fontFamily={F.sans} fontWeight={600} fontSize={40 * u} letterSpacing={-0.5 * u}>MRNA</text>
            <text x={hx + 128 * u} y={hy + (vertical ? -70 : 30) * u} fill={C.muted} fontFamily={F.sans} fontSize={21 * u}>Moderna, Inc.</text>
            {field('MARKET', 'NASDAQ', fx[0])}
            {field('SECTOR', 'BIOTECH', fx[1])}
            {field('PRICE', `$${m.head.toFixed(2)}`, fx[2], spiking > 0 ? C.pos : C.text)}
            {field('VOLUME', `${(dayVol / 1e6).toFixed(1)}M`, fx[3])}
            <line x1={rect.x0} x2={rect.x1 + 60 * u} y1={hy + 58 * u} y2={hy + 58 * u} stroke={C.border} strokeWidth={1} vectorEffect="non-scaling-stroke" />
          </g>
          <g opacity={lineOut}>
          <MarketChart
            bars={bars} rect={rect} domain={m.domain} k={m.k} u={u} chrome={chrome} volRect={vol} volMax={m.volMax}
            volume={chrome} lineColor={lineColor} lineWidth={3.2 * u} area={0.14 * chrome} xLabels={xLabels}
            yTicks={yTicks} headGlow={1 - prog(t, 4.2, 4.6)}
          />
          </g>
          {/* event-day marker on the time axis */}
          <g opacity={chrome * peakShown}>
            <line x1={g.x(SPIKE_I)} x2={g.x(SPIKE_I)} y1={rect.y0} y2={vol.y1} stroke={C.pos} strokeOpacity={0.35} strokeDasharray="4 6" vectorEffect="non-scaling-stroke" />
            <text x={g.x(SPIKE_I)} y={vol.y1 + 34 * u} fill={C.pos} fontFamily={F.mono} fontSize={13 * u} textAnchor="middle" letterSpacing={1.5 * u}>AUG 19</text>
          </g>
          {/* peak annotation */}
          <g opacity={peakShown * (1 - E.inOut(prog(t, 4.1, 4.6)))} transform={`translate(${g.x(SPIKE_I) - 26 * u} ${g.y(EVENT.close) + 6 * u})`}>
            <text x={0} y={0} textAnchor="end" fill={C.faint} fontFamily={F.mono} fontSize={13 * u} letterSpacing={1.6 * u}>{`${EVENT.dateLabel} · CLOSE`}</text>
            <text x={0} y={46 * u} textAnchor="end" fill={C.pos} fontFamily={F.sans} fontWeight={600} fontSize={46 * u} letterSpacing={-1 * u}>{`+${pct.toFixed(2)}%`}</text>
            <text x={0} y={76 * u} textAnchor="end" fill={C.muted} fontFamily={F.mono} fontSize={13.5 * u} letterSpacing={0.6 * u}>{`$${EVENT.prevClose.toFixed(2)} → $${EVENT.close.toFixed(2)} · VOL ${(EVENT.volume / 1e6).toFixed(1)}M`}</text>
          </g>
          {/* peak ping */}
          {peakShown > 0 && t < 4.6 && (
            <circle cx={g.x(SPIKE_I)} cy={g.y(EVENT.close)} r={(6 + 38 * prog(t, BEAT.spikeEnd, BEAT.spikeEnd + 0.9)) * u} fill="none" stroke={C.pos} strokeOpacity={0.6 * (1 - prog(t, BEAT.spikeEnd, BEAT.spikeEnd + 0.9))} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          )}
        </g>
      </svg>
      <div style={{position: 'absolute', left: rect.x0 + 6 * u, top: vertical ? 0.13 * L.h : 0.335 * L.h}}>
        <KineticText t={t} text="ONE DAY." start={BEAT.oneDay} end={4.35} size={(vertical ? 104 : TYPE.display) * u} />
        <div style={{height: 10 * u}} />
        <KineticText t={t} text="ONE SIGNAL." start={BEAT.oneSignal} end={4.45} size={(vertical ? 104 : TYPE.display) * u} accentWords={['SIGNAL']} />
      </div>
    </AbsoluteFill>
  );
};
