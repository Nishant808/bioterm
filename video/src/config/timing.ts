// Every beat of the film lives in timeline.json - the composition and
// audio/generate.py both read it, so picture and sound retime together.
import timeline from './timeline.json';

export const FPS = timeline.fps;
export const DURATION = timeline.duration;
export const SCENES = timeline.scenes;
export const BEAT = timeline.beat as typeof timeline.beat & {
  chromeOut: [number, number];
  streamToEdges: [number, number];
  converge: [number, number];
  windowW: [number, number];
  windowH: [number, number];
  uiRecede: [number, number];
};
export const CHAPTERS = timeline.chapters;
