import React from 'react';
import {AbsoluteFill} from 'remotion';
import {useLayout} from '../config/layout';
import {useTime} from '../lib/anim';
import {BrandSequence} from '../components/EndCard';

/**
 * SCENE 07 (24-27s) + SCENE 08 (27-30s). The app recedes behind the type
 * (TerminalUI handles its own blur/dim), UNDERSTAND THE SIGNAL / THE BIOLOGY,
 * then BIOTERM becomes the focal word and settles into the end card, which
 * holds from ~28.3s to the last frame.
 */
export const S07Message: React.FC = () => {
  const t = useTime();
  const L = useLayout();
  return (
    <AbsoluteFill>
      <BrandSequence t={t} L={L} />
    </AbsoluteFill>
  );
};
