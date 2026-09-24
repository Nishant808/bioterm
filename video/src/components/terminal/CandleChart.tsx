import React, {useMemo} from 'react';
import {C, F} from '../../config/theme';
import {ONE_YEAR} from '../../data/event';

// Recreates the Stock detail "Price & technicals" panel: candles + SMA 20/50/200,
// volume, RSI(14), dated-catalyst marker. Computed from the verified daily bars.
const sma = (xs: number[], n: number) => xs.map((_, i) => (i + 1 < n ? NaN : xs.slice(i + 1 - n, i + 1).reduce((a, b) => a + b, 0) / n));
const rsi = (xs: number[], n = 14) => {
  const out: number[] = xs.map(() => NaN);
  let g = 0;
  let l = 0;
  for (let i = 1; i < xs.length; i++) {
    const d = xs[i] - xs[i - 1];
    const up = Math.max(0, d);
    const dn = Math.max(0, -d);
    if (i <= n) {
      g += up / n;
      l += dn / n;
      if (i === n) out[i] = 100 - 100 / (1 + g / (l || 1e-9));
    } else {
      g = (g * (n - 1) + up) / n;
      l = (l * (n - 1) + dn) / n;
      out[i] = 100 - 100 / (1 + g / (l || 1e-9));
    }
  }
  return out;
};
const day = (iso: string) => Date.parse(`${iso}T00:00:00Z`) / 864e5;

export const CandleChart: React.FC<{x: number; y: number; w: number; reveal: number; markerP: number}> = ({x, y, w, reveal, markerP}) => {
  const d = useMemo(() => {
    const closes = ONE_YEAR.map((b) => b.close);
    return {s20: sma(closes, 20), s50: sma(closes, 50), s200: sma(closes, 200), r: rsi(closes)};
  }, []);
  const d0 = day('2025-09-24');
  const d1 = day('2026-11-23'); // app pads +60 days for upcoming catalysts
  const px = (iso: string) => x + ((day(iso) - d0) / (d1 - d0)) * w;
  const top = y;
  const ph = 285;
  const py = (v: number) => top + ph - (v / 210) * ph;
  const vTop = top + ph + 18;
  const vh = 70;
  const vmax = 200e6;
  const rTop = vTop + vh + 22;
  const rh = 70;
  const ry = (v: number) => rTop + rh - ((v - 20) / 70) * rh;
  const n = Math.floor(ONE_YEAR.length * reveal);
  const cw = Math.max(1.6, (w / ONE_YEAR.length) * 0.55);
  const line = (vals: number[], f: (v: number) => number) =>
    ONE_YEAR.slice(0, n)
      .map((b, i) => (isNaN(vals[i]) ? null : `${px(b.date).toFixed(1)},${f(vals[i]).toFixed(1)}`))
      .filter(Boolean)
      .map((p, i) => `${i ? 'L' : 'M'}${p}`)
      .join(' ');
  const months = [['2025-11-01', 'Nov 2025'], ['2026-01-01', 'Jan 2026'], ['2026-03-01', 'Mar 2026'], ['2026-05-01', 'May 2026'], ['2026-07-01', 'Jul 2026'], ['2026-09-01', 'Sep 2026'], ['2026-11-01', 'Nov 2026']];
  const mk = px('2026-10-24');
  return (
    <svg style={{position: 'absolute', left: 0, top: 0, overflow: 'visible'}} width={1920} height={1600}>
      {[50, 100, 150, 200].map((v) => (
        <g key={v}>
          <line x1={x} x2={x + w} y1={py(v)} y2={py(v)} stroke={C.grid} />
          <text x={x - 10} y={py(v) + 4} fill={C.muted} fontSize={11} textAnchor="end" fontFamily={F.sans}>{v}</text>
        </g>
      ))}
      <text x={x - 44} y={top + ph / 2} fill={C.muted} fontSize={11} transform={`rotate(-90 ${x - 44} ${top + ph / 2})`} textAnchor="middle" fontFamily={F.sans}>Price</text>
      {ONE_YEAR.slice(0, n).map((b, i) => {
        const up = b.close >= b.open;
        const col = up ? C.pos : C.neg;
        const xx = px(b.date);
        return (
          <g key={b.date}>
            <line x1={xx} x2={xx} y1={py(b.high)} y2={py(b.low)} stroke={col} strokeWidth={1} />
            <rect x={xx - cw / 2} y={py(Math.max(b.open, b.close))} width={cw} height={Math.max(1, Math.abs(py(b.open) - py(b.close)))} fill={col} />
            <rect x={xx - cw / 2} y={vTop + vh - (b.volume / vmax) * vh} width={cw} height={(b.volume / vmax) * vh} fill={col} opacity={0.6} />
          </g>
        );
      })}
      <path d={line(d.s200, py)} fill="none" stroke={C.sma200} strokeWidth={1.4} />
      <path d={line(d.s50, py)} fill="none" stroke={C.violet} strokeWidth={1.4} />
      <path d={line(d.s20, py)} fill="none" stroke={C.accent} strokeWidth={1.4} />
      {/* dated catalyst in the next 60 days */}
      <g opacity={markerP}>
        <line x1={mk} x2={mk} y1={top - 6} y2={top + ph} stroke={C.warn} strokeOpacity={0.55} />
        <path d={`M${mk - 5},${top - 10} h10 l-5,7 z`} fill={C.warn} />
      </g>
      <line x1={x} x2={x + w} y1={vTop + vh} y2={vTop + vh} stroke={C.grid} />
      <text x={x - 30} y={vTop + vh / 2} fill={C.muted} fontSize={11} transform={`rotate(-90 ${x - 30} ${vTop + vh / 2})`} textAnchor="middle" fontFamily={F.sans}>Volume</text>
      {[30, 70].map((v) => (
        <g key={v}>
          <line x1={x} x2={x + w} y1={ry(v)} y2={ry(v)} stroke={C.grid} />
          <text x={x - 10} y={ry(v) + 4} fill={C.muted} fontSize={11} textAnchor="end" fontFamily={F.sans}>{v}</text>
        </g>
      ))}
      <path d={line(d.r, ry)} fill="none" stroke={C.accent} strokeWidth={1.3} />
      {months.map(([iso, label]) => (
        <text key={iso} x={px(iso)} y={rTop + rh + 30} fill={C.text2} fontSize={11.5} textAnchor="middle" fontFamily={F.sans}>{label}</text>
      ))}
    </svg>
  );
};
