import React from 'react';
import {AbsoluteFill} from 'remotion';
import {C, TYPE} from '../config/theme';
import {BEAT} from '../config/timing';
import {useLayout} from '../config/layout';
import {useTime, windowed} from '../lib/anim';
import {KineticText} from '../components/KineticText';

/**
 * SCENE 04 (11-15s) market -> biology. The graph layer (S03) decodes each type
 * into the publicly reported entity, the camera travels biology -> science,
 * then every node converges on one point. This file owns the line of copy.
 */
export const S04Biology: React.FC = () => {
  const t = useTime();
  const L = useLayout();
  const {u, h, vertical} = L;
  if (t < BEAT.connect - 0.1 || t > BEAT.converge[1] + 0.1) return null;
  const band = windowed(t, BEAT.connect - 0.2, BEAT.converge[1], 0.4, 0.3);
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute', left: 0, right: 0, top: (vertical ? 0.74 : 0.7) * h, height: (vertical ? 0.2 : 0.3) * h, opacity: band,
          background: `linear-gradient(180deg, ${C.void}00 0%, ${C.void}E6 38%, ${C.void}E6 70%, ${C.void}00 100%)`,
        }}
      />
      <div style={{position: 'absolute', left: 0, right: 0, top: (vertical ? 0.8 : 0.79) * h, display: 'flex', justifyContent: 'center'}}>
        <KineticText t={t} text="CONNECT THE SIGNALS." start={BEAT.connect} end={BEAT.converge[1] + 0.05} size={(vertical ? 62 : 76) * u} accentWords={['SIGNALS']} />
      </div>
    </AbsoluteFill>
  );
};
