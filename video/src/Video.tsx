import React from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {C} from './config/theme';
import {useLayout} from './config/layout';
import {useTime} from './lib/anim';
import {Background, Hud} from './components/Hud';
import {TerminalUI} from './components/TerminalUI';
import {S01Market} from './scenes/S01Market';
import {S02Question} from './scenes/S02Question';
import {S03Network} from './scenes/S03Network';
import {S04Biology} from './scenes/S04Biology';
import {S05Reveal} from './scenes/S05Reveal';
import {S06Flow} from './scenes/S06Flow';
import {S07Message} from './scenes/S07Message';
import './lib/fonts';

/**
 * The film is one continuous composition: every layer is a pure function of
 * global time, and scenes overlap at their seams so transitions are morphs,
 * not cuts. Layer order = depth.
 */
export const BioTermFilm: React.FC<{withAudio?: boolean}> = ({withAudio = true}) => {
  const t = useTime();
  const L = useLayout();
  return (
    <AbsoluteFill style={{background: C.void, overflow: 'hidden'}}>
      <Background t={t} L={L} />
      <S01Market />
      <S03Network />
      <S02Question />
      <S04Biology />
      <TerminalUI t={t} L={L} />
      <S05Reveal />
      <S06Flow />
      <S07Message />
      <Hud t={t} L={L} />
      {withAudio && <Audio src={staticFile('audio/soundtrack.wav')} />}
    </AbsoluteFill>
  );
};
