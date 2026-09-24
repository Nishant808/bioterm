import React from 'react';
import {C, F} from '../config/theme';
import type {Shape} from '../data/network';

type Props = {
  x: number;
  y: number;
  u: number;
  shape: Shape;
  color: string;
  opacity: number;
  scale?: number;
  title?: string; // main line (entity name, or TYPE in scene 03)
  titleMono?: boolean;
  tag?: string; // tertiary line above the title
  side?: 'left' | 'right';
  labelOpacity?: number;
  glow?: number;
};

/** One entity in the information graph: a typed glyph plus a two-line label. */
export const ScientificNode: React.FC<Props> = ({
  x, y, u, shape, color, opacity, scale = 1, title, titleMono, tag, side = 'right', labelOpacity = 1, glow = 0,
}) => {
  if (opacity <= 0.001) return null;
  const s = u * scale;
  const glyph = (() => {
    switch (shape) {
      case 'core':
        return (
          <>
            <circle r={24 * s} fill={color} opacity={0.08 + 0.1 * glow} />
            <circle r={15 * s} fill="none" stroke={color} strokeWidth={1.4 * u} opacity={0.7} />
            <circle r={8 * s} fill={color} />
          </>
        );
      case 'chip':
        return <rect x={-9 * s} y={-6 * s} width={18 * s} height={12 * s} rx={3 * s} fill={C.void} stroke={color} strokeWidth={1.6 * u} />;
      case 'ring':
        return (
          <>
            <circle r={8 * s} fill={C.void} stroke={color} strokeWidth={1.6 * u} />
            <circle r={2.6 * s} fill={color} />
          </>
        );
      case 'square':
        return <rect x={-6.5 * s} y={-6.5 * s} width={13 * s} height={13 * s} fill={C.void} stroke={color} strokeWidth={1.6 * u} />;
      case 'doc':
        return (
          <>
            <path d={`M${-6 * s},${-8 * s} h${8 * s} l${4 * s},${4 * s} v${12 * s} h${-12 * s} Z`} fill={C.void} stroke={color} strokeWidth={1.5 * u} />
            <path d={`M${-3 * s},${0} h${6 * s} M${-3 * s},${3.5 * s} h${6 * s}`} stroke={color} strokeWidth={1 * u} />
          </>
        );
      default:
        return <circle r={5.5 * s} fill={color} />;
    }
  })();
  const dx = (side === 'right' ? 22 : -22) * s;
  const anchor = side === 'right' ? 'start' : 'end';
  return (
    <g transform={`translate(${x} ${y})`} opacity={opacity}>
      {glow > 0 && <circle r={30 * s} fill={color} opacity={0.12 * glow} />}
      {glyph}
      {(title || tag) && labelOpacity > 0.001 && (
        <g opacity={labelOpacity}>
          {tag && (
            <text x={dx} y={-10 * s} textAnchor={anchor} fill={C.muted} fontFamily={F.mono} fontSize={12.5 * u} letterSpacing={1.4 * u}>
              {tag}
            </text>
          )}
          {title && (
            <text
              x={dx} y={tag ? 15 * s : 5.5 * s} textAnchor={anchor} fill={titleMono ? C.text2 : C.text}
              fontFamily={titleMono ? F.mono : F.sans} fontWeight={titleMono ? 500 : 600}
              fontSize={(titleMono ? 15.5 : 23) * u} letterSpacing={(titleMono ? 2.2 : -0.2) * u}
            >
              {title}
            </text>
          )}
        </g>
      )}
    </g>
  );
};
