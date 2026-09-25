import React from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {C} from '../config/theme';
import {useTime} from '../lib/anim';
import '../lib/fonts';
import {H, S, W, hitEnergy, k} from './core';
import {Camera, Defs, Flash, Grain, Hud, Vignette} from './fx';
import {Ignite} from './scenes/Ignite';
import {Identity} from './scenes/Identity';
import {Kinetic} from './scenes/Kinetic';
import {Universe} from './scenes/Universe';
import {Engine} from './scenes/Engine';
import {Terminal} from './scenes/Terminal';
import {Copilot} from './scenes/Copilot';
import {Numbers} from './scenes/Numbers';
import {Finale} from './scenes/Finale';

/** Ambient backdrop: a slow aurora of the brand colours that breathes with the hits. */
const Backdrop: React.FC<{t: number}> = ({t}) => {
  const e = Math.min(1, hitEnergy(t, 0.5));
  const a = t * 0.12;
  const on = k(t, 2.8, 3.4) * (1 - k(t, 39.2, 40));
  return (
    <>
      <div style={{position: 'absolute', inset: 0, background: C.void}} />
      <div style={{position: 'absolute', inset: -200, opacity: on * (0.55 + 0.35 * e),
        background: `radial-gradient(40% 50% at ${50 + 22 * Math.cos(a)}% ${45 + 16 * Math.sin(a * 1.3)}%, ${C.primary}26, transparent 70%),
                     radial-gradient(35% 45% at ${50 - 24 * Math.cos(a * 0.8)}% ${55 - 14 * Math.sin(a)}%, ${C.violet}22, transparent 70%)`}} />
    </>
  );
};

export const Showreel: React.FC<{withAudio?: boolean}> = ({withAudio = true}) => {
  const t = useTime();
  return (
    <AbsoluteFill style={{background: C.void, overflow: 'hidden', width: W, height: H}}>
      <Defs />
      <Backdrop t={t} />
      <Camera t={t} drift={t < S.mark ? 0.3 : 1}>
        <Ignite t={t} />
        <Identity t={t} />
        <Kinetic t={t} />
        <Universe t={t} />
        <Engine t={t} />
        <Terminal t={t} />
        <Copilot t={t} />
        <Numbers t={t} />
        <Finale t={t} />
      </Camera>
      <Flash t={t} />
      <Hud t={t} />
      <Vignette />
      <Grain />
      {withAudio && <Audio src={staticFile('audio/showreel.wav')} />}
    </AbsoluteFill>
  );
};
