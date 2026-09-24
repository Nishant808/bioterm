import React from 'react';
import {AbsoluteFill} from 'remotion';
import {useLayout} from '../config/layout';
import {useTime} from '../lib/anim';
import {DataNetwork} from '../components/DataNetwork';

/**
 * SCENE 03 (7-11s) below the market: the stream folds into a typed graph -
 * COMPANY, PROGRAM, TRIAL, DISEASE, TARGET, PAPER, DATA, SCIENCE - that keeps
 * growing. SCENE 04 continues the same component (it decodes and converges),
 * so both scenes mount one DataNetwork layer across 7-15s.
 */
export const S03Network: React.FC = () => {
  const t = useTime();
  const L = useLayout();
  return (
    <AbsoluteFill>
      <DataNetwork t={t} L={L} />
    </AbsoluteFill>
  );
};
