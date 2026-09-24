import React from 'react';

/** BioTerm mark - geometry copied from dashboard/assets/mark.svg. */
export const LogoMark: React.FC<{size: number; id?: string}> = ({size, id = 'bt'}) => (
  <svg width={size} height={size} viewBox="0 0 32 32">
    <defs>
      <linearGradient id={`${id}-g`} x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
        <stop offset="0" stopColor="#4C8DFF" />
        <stop offset="1" stopColor="#6A5CF6" />
      </linearGradient>
    </defs>
    <rect width="32" height="32" rx="8" fill={`url(#${id}-g)`} />
    <g fill="none" stroke="#FFFFFF" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 6C19.5 7.5 21 9.3 21 11S19.5 14.5 16 16 11 19.3 11 21s1.5 3.5 5 5" />
      <path d="M16 6C12.5 7.5 11 9.3 11 11s1.5 3.5 5 5 5 3.3 5 5-1.5 3.5-5 5" strokeOpacity=".5" />
      <path d="M13.3 11h5.4M13.3 21h5.4" strokeWidth="1.6" strokeOpacity=".7" />
    </g>
  </svg>
);

/** The mark's helix strands as separate paths, for a draw-on reveal. */
export const HELIX = [
  'M16 6C19.5 7.5 21 9.3 21 11S19.5 14.5 16 16 11 19.3 11 21s1.5 3.5 5 5',
  'M16 6C12.5 7.5 11 9.3 11 11s1.5 3.5 5 5 5 3.3 5 5-1.5 3.5-5 5',
];
