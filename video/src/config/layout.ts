import {useVideoConfig} from 'remotion';

// One composition, two formats. Everything positions against w/h and sizes
// type/strokes by u (short side / 1080), so 1920x1080 and 1080x1920 share code.
export const useLayout = () => {
  const {width: w, height: h} = useVideoConfig();
  const vertical = h > w;
  const u = Math.min(w, h) / 1080;
  return {w, h, vertical, u, cx: w / 2, cy: h / 2};
};
export type Layout = ReturnType<typeof useLayout>;
