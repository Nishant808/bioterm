// Reproducible renders. Usage:
//   node scripts/render.mjs stills [comp] [t1,t2,...]   PNG frames for review -> output/stills
//   node scripts/render.mjs master                      16:9 master  -> output/bioterm_30s_master.mp4
//   node scripts/render.mjs vertical                    9:16 master  -> output/bioterm_30s_vertical_master.mp4
//   node scripts/render.mjs reel                        40 s motion reel (1080p60) -> output/bioterm_reel_40s_master.mp4
import path from 'node:path';
import fs from 'node:fs';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const OUT = path.join(ROOT, 'output');
fs.mkdirSync(path.join(OUT, 'stills'), {recursive: true});
// Local Chromium (Playwright's headless shell) - no browser download needed.
const browserExecutable = process.env.REMOTION_CHROME ?? '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell';
const chromiumOptions = {gl: 'swangle', disableWebSecurity: false};

const [mode = 'stills', compArg, timesArg] = process.argv.slice(2);
const serveUrl = await bundle({entryPoint: path.join(ROOT, 'src/index.ts'), publicDir: path.join(ROOT, 'public')});

const pick = async (id, inputProps = {}) => selectComposition({serveUrl, id, inputProps, browserExecutable, chromiumOptions});

if (mode === 'stills') {
  const id = compArg ?? 'BioTerm16x9';
  const comp = await pick(id, {withAudio: false});
  const times = (timesArg ?? '0.5,1.8,2.9,3.3,3.8,4.8,5.6,6.4,6.9,7.6,9,10.5,11.6,12.5,13.6,14.4,14.9,15.4,16.3,17.5,19.4,20.2,20.9,21.8,22.6,23.5,24.6,25.5,26.4,27.3,28.2,29.9').split(',').map(Number);
  for (const t of times) {
    const frame = Math.min(comp.durationInFrames - 1, Math.round(t * comp.fps));
    const output = path.join(OUT, 'stills', `${id}_${String(t.toFixed(2)).padStart(5, '0')}.png`);
    await renderStill({serveUrl, composition: comp, frame, output, browserExecutable, chromiumOptions, inputProps: {withAudio: false}});
    console.log('still', output);
  }
} else {
  const id = mode === 'reel' ? 'Showreel' : mode === 'vertical' ? 'BioTerm9x16' : 'BioTerm16x9';
  const file = mode === 'reel' ? 'bioterm_reel_40s_master.mp4' : mode === 'vertical' ? 'bioterm_30s_vertical_master.mp4' : 'bioterm_30s_master.mp4';
  const comp = await pick(id, {withAudio: true});
  let last = -1;
  await renderMedia({
    serveUrl, composition: comp, codec: 'h264', outputLocation: path.join(OUT, file), inputProps: {withAudio: true},
    browserExecutable, chromiumOptions, crf: 12, pixelFormat: 'yuv420p', x264Preset: 'slow', audioCodec: 'aac', audioBitrate: '320k',
    concurrency: Number(process.env.CONCURRENCY ?? 4), colorSpace: 'bt709',
    onProgress: ({progress}) => {
      const p = Math.floor(progress * 20);
      if (p !== last) console.log(`render ${Math.round(progress * 100)}%`), (last = p);
    },
  });
  console.log('wrote', path.join(OUT, file));
}
