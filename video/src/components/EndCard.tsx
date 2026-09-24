import React from 'react';
import {C, F, TYPE} from '../config/theme';
import {BEAT} from '../config/timing';
import type {Layout} from '../config/layout';
import {E, lerp, prog} from '../lib/anim';
import {HELIX} from './Logo';
import {KineticText} from './KineticText';

/**
 * Scenes 07-08 share one brand element: BIOTERM lands as the focal word of the
 * core message, then settles into the end-card lockup (no cut between them).
 */
export const BrandSequence: React.FC<{t: number; L: Layout}> = ({t, L}) => {
  const {u, cx, cy, vertical} = L;
  if (t < BEAT.signal - 0.1) return null;
  const msgSize = (vertical ? 62 : 76) * u;
  const linesOut = BEAT.brand - 0.1;

  // BIOTERM: arrives large, then eases up into the lockup
  const bIn = E.out(prog(t, BEAT.brand, BEAT.brand + 0.7));
  const settle = E.inOut(prog(t, BEAT.lockup - 0.1, BEAT.lockup + 0.8));
  const heroSize = (vertical ? 150 : TYPE.hero) * u;
  const scale = lerp(1.0, vertical ? 0.78 : 0.72, settle) * lerp(1.06, 1, bIn);
  const y = lerp(cy, cy - (vertical ? 120 : 92) * u, settle);
  const mark = 0.62 * heroSize;
  const draw = E.out(prog(t, BEAT.brand + 0.05, BEAT.brand + 1.0));
  const tagP = E.out(prog(t, BEAT.lockup + 0.35, BEAT.lockup + 1.0));

  return (
    <>
      {/* 07: the two lines of the core message */}
      <div style={{position: 'absolute', left: 0, right: 0, top: cy - msgSize * 1.25, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 22 * u}}>
        <KineticText t={t} text="UNDERSTAND THE SIGNAL." start={BEAT.signal} end={linesOut} size={msgSize} accentWords={['SIGNAL']} />
        <KineticText t={t} text="UNDERSTAND THE BIOLOGY." start={BEAT.biology2} end={linesOut} size={msgSize} accentWords={['BIOLOGY']} />
      </div>
      {/* 07 -> 08: the wordmark */}
      {t >= BEAT.brand - 0.05 && (
        <div style={{position: 'absolute', left: 0, right: 0, top: y, height: 0, display: 'flex', justifyContent: 'center', alignItems: 'center'}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 0.26 * heroSize, transform: `scale(${scale})`, opacity: bIn, filter: `blur(${(1 - bIn) * 10}px)`}}>
            <svg width={mark} height={mark} viewBox="0 0 32 32" style={{overflow: 'visible'}}>
              <defs>
                <linearGradient id="end-g" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
                  <stop offset="0" stopColor="#4C8DFF" />
                  <stop offset="1" stopColor="#6A5CF6" />
                </linearGradient>
              </defs>
              <rect width="32" height="32" rx="8" fill="url(#end-g)" opacity={E.out(prog(t, BEAT.brand, BEAT.brand + 0.5))} />
              <g fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round">
                <path d={HELIX[0]} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
                <path d={HELIX[1]} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} strokeOpacity={0.5} />
                <path d="M13.3 11h5.4M13.3 21h5.4" strokeWidth="1.6" strokeOpacity={0.7 * draw} />
              </g>
            </svg>
            <div style={{fontFamily: F.sans, fontSize: heroSize, fontWeight: 700, letterSpacing: '-0.035em', color: C.text, lineHeight: 1}}>
              BIO<span style={{fontWeight: 500, color: C.accentSoft}}>TERM</span>
            </div>
          </div>
        </div>
      )}
      {/* 08: lockup copy */}
      {t >= BEAT.lockup && (
        <div style={{position: 'absolute', left: 0, right: 0, top: y + (vertical ? 70 : 62) * u, display: 'flex', flexDirection: 'column', alignItems: 'center'}}>
          <div style={{fontFamily: F.mono, fontSize: (vertical ? 26 : 25) * u, fontWeight: 500, letterSpacing: `${0.42}em`, color: C.text2, opacity: tagP, transform: `translateY(${(1 - tagP) * 10 * u}px)`, marginRight: '-0.42em'}}>
            INTELLIGENCE TERMINAL
          </div>
          <div style={{height: 44 * u}} />
          <div style={{width: lerp(0, 120, E.out(prog(t, BEAT.tagline - 0.2, BEAT.tagline + 0.5))) * u, height: 1, background: C.borderStrong}} />
          <div style={{height: 40 * u}} />
          <KineticText t={t} text="Explore the signals behind biotech." start={BEAT.tagline} size={(vertical ? 36 : 32) * u} weight={400} color={C.text2} tracking={-0.005} stagger={0.05} />
          <div style={{height: 22 * u}} />
          <div style={{fontFamily: F.mono, fontSize: (vertical ? 32 : 30) * u, color: C.accent, letterSpacing: 0.5 * u, opacity: E.out(prog(t, BEAT.url, BEAT.url + 0.5))}}>
            bioterm.streamlit.app
          </div>
        </div>
      )}
      {t >= BEAT.url && (
        <div style={{position: 'absolute', left: 60 * u, right: 60 * u, bottom: (vertical ? 90 : 38) * u, textAlign: 'center', fontFamily: F.sans, fontSize: 13 * u, lineHeight: 1.5, color: C.faint, opacity: E.out(prog(t, BEAT.url + 0.2, BEAT.url + 0.8))}}>
          Monitoring and screening only — not investment advice. Market data: Nasdaq daily OHLCV. Not affiliated with Moderna or Merck.
        </div>
      )}
    </>
  );
};
