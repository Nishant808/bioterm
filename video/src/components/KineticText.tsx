import React from 'react';
import {C, F} from '../config/theme';
import {E, prog} from '../lib/anim';

type Props = {
  t: number;
  text: string;
  start: number; // first word begins
  end?: number; // whole line fades out
  size: number;
  weight?: number;
  color?: string;
  accentWords?: string[]; // words drawn in the accent colour
  accentColor?: string;
  stagger?: number;
  tracking?: number; // em
  font?: string;
  style?: React.CSSProperties;
  align?: 'left' | 'center';
};

/** Word-by-word kinetic line: each word rises 0.18em, sharpens and settles. */
export const KineticText: React.FC<Props> = ({
  t, text, start, end, size, weight = 600, color = C.text, accentWords = [], accentColor = C.accent,
  stagger = 0.075, tracking = -0.02, font = F.sans, style, align = 'left',
}) => {
  const words = text.split(' ');
  const out = end === undefined ? 0 : E.inOut(prog(t, end - 0.35, end));
  if (t < start - 0.01 || out >= 1) return null;
  return (
    <div
      style={{
        fontFamily: font, fontSize: size, fontWeight: weight, letterSpacing: `${tracking}em`, lineHeight: 1.02,
        color, whiteSpace: 'nowrap', textAlign: align, opacity: 1 - out,
        transform: `translateY(${-out * size * 0.12}px)`, ...style,
      }}
    >
      {words.map((w, i) => {
        const p = E.out(prog(t, start + i * stagger, start + i * stagger + 0.55));
        const clean = w.replace(/[.,?!]/g, '');
        return (
          <span
            key={i}
            style={{
              display: 'inline-block', opacity: p, marginRight: i < words.length - 1 ? '0.26em' : 0,
              transform: `translateY(${(1 - p) * 0.22 * size}px)`, filter: `blur(${(1 - p) * 6}px)`,
              color: accentWords.includes(clean) ? accentColor : undefined,
            }}
          >
            {w}
          </span>
        );
      })}
    </div>
  );
};

/** Small tracked monospace terminal label. */
export const Label: React.FC<{children: React.ReactNode; size: number; color?: string; style?: React.CSSProperties; weight?: number}> = ({children, size, color = C.muted, style, weight = 500}) => (
  <div style={{fontFamily: F.mono, fontSize: size, fontWeight: weight, letterSpacing: '0.14em', textTransform: 'uppercase', color, whiteSpace: 'nowrap', ...style}}>
    {children}
  </div>
);

/** Characters appear left to right (terminal typing), deterministic. */
export const typed = (s: string, p: number) => s.slice(0, Math.round(s.length * Math.max(0, Math.min(1, p))));
