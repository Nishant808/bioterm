import React from 'react';
import {Composition} from 'remotion';
import {DURATION, FPS} from './config/timing';
import {BioTermFilm} from './Video';
import {Showreel} from './reel/Showreel';
import {DUR as REEL_DUR, FPS as REEL_FPS} from './reel/core';

export const Root: React.FC = () => (
  <>
    <Composition id="BioTerm16x9" component={BioTermFilm} durationInFrames={DURATION * FPS} fps={FPS} width={1920} height={1080} defaultProps={{withAudio: true}} />
    <Composition id="BioTerm9x16" component={BioTermFilm} durationInFrames={DURATION * FPS} fps={FPS} width={1080} height={1920} defaultProps={{withAudio: true}} />
    <Composition id="Showreel" component={Showreel} durationInFrames={REEL_DUR * REEL_FPS} fps={REEL_FPS} width={1920} height={1080} defaultProps={{withAudio: true}} />
  </>
);
