import React from 'react';
import type {Bar} from '../data/mrna.generated';
import {C, F} from '../config/theme';

export type Rect = {x0: number; x1: number; y0: number; y1: number};

/** Pure geometry so scenes and the camera can locate any bar. */
export const chartGeom = (n: number, rect: Rect, domain: [number, number]) => {
  const [lo, hi] = domain;
  return {
    x: (i: number) => rect.x0 + ((rect.x1 - rect.x0) * i) / (n - 1),
    y: (v: number) => rect.y1 - ((v - lo) / (hi - lo)) * (rect.y1 - rect.y0),
  };
};

/** Close at a fractional bar index (linear between closes). */
export const closeAt = (bars: Bar[], k: number) => {
  const i = Math.max(0, Math.min(bars.length - 1, Math.floor(k)));
  const j = Math.min(bars.length - 1, i + 1);
  return bars[i].close + (bars[j].close - bars[i].close) * (k - i);
};

type Props = {
  bars: Bar[];
  rect: Rect;
  domain: [number, number];
  k: number; // how far the line has drawn, in bars (fractional)
  u: number;
  chrome: number; // opacity of grid/axes/labels
  volRect?: Rect;
  volMax?: number;
  volume?: number; // opacity of volume bars
  lineColor?: string;
  lineWidth?: number;
  area?: number; // opacity of the area wash under the line
  xLabels?: {i: number; text: string}[];
  yTicks?: number[];
  headGlow?: number;
};

/**
 * Reusable price chart: grid, price line with animated draw, area wash, volume
 * bars, time axis, price axis. Strokes use non-scaling-stroke so a camera zoom
 * keeps hairlines crisp.
 */
export const MarketChart: React.FC<Props> = ({
  bars, rect, domain, k, u, chrome, volRect, volMax = 1, volume = 1, lineColor = C.pos, lineWidth = 3,
  area = 0.12, xLabels = [], yTicks = [], headGlow = 1,
}) => {
  const g = chartGeom(bars.length, rect, domain);
  const last = Math.floor(k);
  const pts: [number, number][] = [];
  for (let i = 0; i <= Math.min(last, bars.length - 1); i++) pts.push([g.x(i), g.y(bars[i].close)]);
  if (k > last && last + 1 < bars.length) pts.push([g.x(k), g.y(closeAt(bars, k))]);
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  const head = pts[pts.length - 1];
  const areaD = pts.length > 1 ? `${d} L${head[0]},${rect.y1} L${pts[0][0]},${rect.y1} Z` : '';
  const ns = {vectorEffect: 'non-scaling-stroke' as const};
  return (
    <g>
      <defs>
        <linearGradient id="mc-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={lineColor} stopOpacity={area} />
          <stop offset="1" stopColor={lineColor} stopOpacity={0} />
        </linearGradient>
      </defs>
      {/* grid + price axis */}
      <g opacity={chrome}>
        {yTicks.map((v) => {
          const y = g.y(v);
          if (y < rect.y0 - 2 || y > rect.y1 + 2) return null;
          return (
            <g key={v}>
              <line x1={rect.x0} x2={rect.x1} y1={y} y2={y} stroke={C.grid} strokeWidth={1} {...ns} />
              <text x={rect.x1 + 18 * u} y={y + 5 * u} fill={C.faint} fontFamily={F.mono} fontSize={14 * u}>
                {v.toFixed(0)}
              </text>
            </g>
          );
        })}
        <line x1={rect.x0} x2={rect.x1} y1={rect.y1} y2={rect.y1} stroke={C.borderStrong} strokeWidth={1} {...ns} />
        {xLabels.map(({i, text}) => (
          <text key={i} x={g.x(i)} y={(volRect ? volRect.y1 : rect.y1) + 34 * u} fill={C.faint} fontFamily={F.mono} fontSize={13 * u} textAnchor="middle" letterSpacing={1.5 * u}>
            {text}
          </text>
        ))}
      </g>
      {/* volume */}
      {volRect && (
        <g opacity={volume}>
          {bars.map((b, i) => {
            if (i > k) return null;
            const grow = Math.min(1, k - i + 1);
            const bw = Math.max(2, ((volRect.x1 - volRect.x0) / bars.length) * 0.55);
            const hh = Math.min(1, b.volume / volMax) * (volRect.y1 - volRect.y0) * grow;
            const up = i === 0 || b.close >= bars[i - 1].close;
            return <rect key={b.date} x={g.x(i) - bw / 2} y={volRect.y1 - hh} width={bw} height={Math.max(0.5, hh)} fill={up ? C.pos : C.neg} opacity={0.55} />;
          })}
        </g>
      )}
      {areaD && <path d={areaD} fill="url(#mc-area)" />}
      <path d={d} fill="none" stroke={lineColor} strokeWidth={lineWidth} strokeLinejoin="round" strokeLinecap="round" {...ns} />
      {head && headGlow > 0 && (
        <g opacity={headGlow}>
          <circle cx={head[0]} cy={head[1]} r={9 * u} fill={lineColor} opacity={0.18} />
          <circle cx={head[0]} cy={head[1]} r={4 * u} fill={lineColor} />
        </g>
      )}
    </g>
  );
};
