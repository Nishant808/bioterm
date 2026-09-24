import React from 'react';
import {C, F} from '../../config/theme';

// Primitives mirroring BioTerm's Streamlit theme (config.toml): 14px Inter base,
// 8px radius, hairline #232C3A borders, metric value 1.7rem/600.

export const enter = (p: number, dy = 14): React.CSSProperties => ({
  opacity: p,
  transform: `translateY(${(1 - p) * dy}px)`,
});

export const Card: React.FC<{x: number; y: number; w: number; h: number; p?: number; style?: React.CSSProperties; children?: React.ReactNode}> = ({x, y, w, h, p = 1, style, children}) => (
  <div style={{position: 'absolute', left: x, top: y, width: w, height: h, border: `1px solid ${C.border}`, borderRadius: 8, background: C.bg, ...enter(p), ...style}}>
    {children}
  </div>
);

export const Chip: React.FC<{children: React.ReactNode; tone?: 'gray' | 'blue' | 'red' | 'green'; style?: React.CSSProperties}> = ({children, tone = 'gray', style}) => {
  const tones = {
    gray: {bg: '#1F2733', fg: C.text2},
    blue: {bg: 'rgba(61,132,250,0.18)', fg: '#8FB8FF'},
    red: {bg: 'rgba(229,72,77,0.18)', fg: '#FF8B8E'},
    green: {bg: 'rgba(63,185,107,0.16)', fg: '#6FD394'},
  }[tone];
  return (
    <span style={{display: 'inline-block', padding: '1px 6px', borderRadius: 5, background: tones.bg, color: tones.fg, fontSize: 12.5, lineHeight: '18px', whiteSpace: 'nowrap', ...style}}>
      {children}
    </span>
  );
};

export const Help: React.FC = () => (
  <span style={{display: 'inline-flex', width: 12, height: 12, borderRadius: 6, border: `1.2px solid ${C.muted}`, fontSize: 8, color: C.muted, alignItems: 'center', justifyContent: 'center', marginLeft: 6, transform: 'translateY(1px)'}}>?</span>
);

export const Metric: React.FC<{label: string; value: string; chip?: React.ReactNode; note?: string; help?: boolean; valueColor?: string; valueSize?: number}> = ({label, value, chip, note, help, valueColor = C.text, valueSize = 26}) => (
  <div style={{padding: '14px 14px'}}>
    <div style={{fontSize: 13, color: C.text2, display: 'flex', alignItems: 'center'}}>
      {label}
      {help && <Help />}
    </div>
    <div style={{fontSize: valueSize, fontWeight: 600, color: valueColor, marginTop: 3, letterSpacing: -0.2, whiteSpace: 'nowrap'}}>{value}</div>
    {(chip || note) && (
      <div style={{marginTop: 4, fontSize: 13, color: C.muted, display: 'flex', gap: 6, alignItems: 'center'}}>
        {chip}
        {note}
      </div>
    )}
  </div>
);

export const PageHeader: React.FC<{title: string; subtitle: string; p: number; updated?: string}> = ({title, subtitle, p, updated}) => (
  <>
    <div style={{position: 'absolute', left: 305, top: 110, ...enter(p)}}>
      <div style={{fontSize: 27, fontWeight: 700, color: C.text, letterSpacing: -0.3}}>{title}</div>
      <div style={{fontSize: 13, color: C.muted, marginTop: 8}}>{subtitle}</div>
    </div>
    {updated && (
      <div style={{position: 'absolute', right: 1920 - 1605, top: 126, padding: '6px 11px', borderRadius: 14, border: `1px solid ${C.border}`, fontSize: 12, color: C.text2, display: 'flex', alignItems: 'center', gap: 8, ...enter(p)}}>
        <span style={{width: 7, height: 7, borderRadius: 4, background: C.pos}} />
        {updated}
      </div>
    )}
  </>
);

/** Tiny line icons standing in for the Material Symbols the app uses. */
export const Icon: React.FC<{kind: string; color?: string; size?: number}> = ({kind, color = C.text2, size = 13}) => {
  const s = {fill: 'none', stroke: color, strokeWidth: 1.4, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const};
  const paths: Record<string, React.ReactNode> = {
    grid: <><rect x="2" y="2" width="10" height="10" rx="1.5" {...s} /><path d="M2 6h10M6 6v6" {...s} /></>,
    bars: <path d="M2.5 12V7M6 12V3M9.5 12V5.5M1.5 12h11" {...s} />,
    trend: <path d="M1.5 11l3.5-4 2.5 2.5L12.5 3M9.5 3h3v3" {...s} />,
    cal: <><rect x="2" y="3" width="10" height="9" rx="1.5" {...s} /><path d="M2 6h10M5 1.8v2.4M9 1.8v2.4" {...s} /></>,
    news: <><rect x="1.8" y="2.5" width="10.4" height="9" rx="1.2" {...s} /><path d="M4 5.5h6M4 8h6" {...s} /></>,
    bookmark: <path d="M3.5 2h7v10L7 9.5 3.5 12z" {...s} />,
    compare: <path d="M2 9l3-3 2 2 5-5M2 12h10" {...s} />,
    bell: <path d="M4 10V6.5a3 3 0 016 0V10l1 1H3zM6 12.3h2" {...s} />,
    wallet: <><rect x="2" y="3.5" width="10" height="8" rx="1.5" {...s} /><path d="M9 7.5h3" {...s} /></>,
    search: <><circle cx="6" cy="6" r="3.8" {...s} /><path d="M9 9l3 3" {...s} /></>,
    bolt: <path d="M7.5 1.5L3 8h4l-1 4.5L11 6H7z" {...s} />,
    chev: <path d="M3.5 5.5L7 9l3.5-3.5" {...s} />,
    psych: <><circle cx="7" cy="6" r="4" {...s} /><path d="M5.5 12.5h3" {...s} /></>,
    note: <path d="M2 4h7M2 7h7M2 10h4M10 9l2.5-2.5" {...s} />,
  };
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" style={{flex: 'none'}}>
      {paths[kind] ?? null}
    </svg>
  );
};

export const mono: React.CSSProperties = {fontFamily: F.mono};
