import React from 'react';

// Geometry from dashboard/assets/mark.svg (the live product logo).
export const HEX = 'M16 6.6 24.1 11.3V20.7L16 25.4 7.9 20.7V11.3Z';
export const PULSE = 'M5.2 19.4H10.4L12.9 14.9 16.2 21.2 19.1 13.6 22.2 10.9';

/**
 * The BioTerm mark with every part independently animatable (0..1):
 * frame = tile outline draw, fill = gradient tile, hex / pulse = stroke draw, dot = pop.
 */
export const Mark: React.FC<{
  size: number; frame?: number; fill?: number; hex?: number; pulse?: number; dot?: number; id?: string; glow?: number;
}> = ({size, frame = 1, fill = 1, hex = 1, pulse = 1, dot = 1, id = 'm', glow = 0}) => (
  <svg width={size} height={size} viewBox="0 0 32 32" style={{overflow: 'visible'}}>
    <defs>
      <linearGradient id={`${id}-g`} x1="4" y1="2" x2="28" y2="30" gradientUnits="userSpaceOnUse">
        <stop offset="0" stopColor="#3D84FA" /><stop offset="1" stopColor="#5B4CE6" />
      </linearGradient>
      <clipPath id={`${id}-c`}><rect width="32" height="32" rx="8" /></clipPath>
    </defs>
    {glow > 0 && <rect x="-4" y="-4" width="40" height="40" rx="12" fill="#4C6CF6" opacity={glow * 0.35} filter="url(#glow-lg)" />}
    <g clipPath={`url(#${id}-c)`}>
      <circle cx="16" cy="16" r={24 * fill} fill={`url(#${id}-g)`} />
    </g>
    <rect x=".5" y=".5" width="31" height="31" rx="7.5" fill="none" stroke="#FFFFFF" strokeOpacity={0.14 + 0.6 * (1 - fill)}
      pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - frame} />
    <path d={HEX} fill="none" stroke="#FFFFFF" strokeOpacity=".5" strokeWidth="1.7" strokeLinejoin="round"
      pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - hex} />
    <path d={PULSE} fill="none" stroke="#FFFFFF" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
      pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - pulse} />
    <circle cx="24.6" cy="8.8" r={2.1 * dot} fill="#FFFFFF" />
  </svg>
);
