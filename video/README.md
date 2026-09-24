# BioTerm — 30s launch film

Programmatic motion graphics for the BioTerm Intelligence Terminal. Built with Remotion 4
(React + SVG), rendered locally with headless Chromium, encoded with FFmpeg. There is no AI
footage and there are no stock assets. The soundtrack is synthesised in `audio/generate.py`.

**Story:** MRNA → SIGNAL → BIOLOGY → BIOTERM. A real one-day move (Moderna, 19 Aug 2026,
+176.97%) is the hook. The camera dives into the spike and the price line becomes a
stream of information. The stream folds into a graph of the entities behind the move, and
the graph converges into the BioTerm terminal, where the same investigation runs on real
screens. The film does not claim that BioTerm predicted the move. See `research/RESEARCH.md`
for every number and label.

## Layout

```
src/
  config/timeline.json   every beat (seconds) — read by the video AND the audio generator
  config/{timing,theme,layout}.ts   beats, BioTerm design tokens, 16:9 / 9:16 layout (u = short side / 1080)
  data/                  verified MRNA OHLCV (csv → generated ts), captured BioTerm UI copy, graph entities
  components/            MarketChart · DataNetwork · ScientificNode · KineticText · TerminalUI
                         (terminal/ pages: Overview, Focus list, Stock detail, CandleChart) · EndCard · Hud · Logo
  scenes/                S01Market … S07Message (07 also carries the 08 end card)
  Video.tsx              one continuous composition; every layer is a pure function of time
audio/generate.py        procedural soundtrack + SFX (numpy/scipy, fixed seed) → public/audio/soundtrack.wav
scripts/render.mjs       stills / master / vertical renders
scripts/encode.sh        master → Twitter/X-ready MP4
scripts/contact.py       review contact sheets from stills
research/                website + market-event research, live screenshots
output/                  renders (git-ignored)
```

## Build

```bash
cd video
npm install
pip install numpy scipy pillow imageio-ffmpeg
node scripts/build-data.mjs            # csv -> src/data/mrna.generated.ts
python3 audio/generate.py              # soundtrack.wav
node scripts/render.mjs stills         # review frames -> output/stills (python3 scripts/contact.py to tile)
node scripts/render.mjs master         # output/bioterm_30s_master.mp4   (1920x1080, 30fps, H.264 CRF 12, AAC 320k)
bash scripts/encode.sh                 # output/bioterm_30s_twitter.mp4  (H.264 High, ~12 Mbps, AAC 192k, faststart)
node scripts/render.mjs vertical       # output/bioterm_30s_vertical_master.mp4 (1080x1920)
npx remotion studio src/index.ts       # interactive timeline
```

Chromium: `scripts/render.mjs` points Remotion at the machine's headless shell
(`REMOTION_CHROME` overrides it). Renders are deterministic: seeded PRNG, no wall-clock time,
and fonts load before the first frame.

## Retiming

Edit `src/config/timeline.json`, rerun `python3 audio/generate.py`, then re-render. Chart
draw speed is `drawK()` in `src/scenes/marketState.ts`. The market ticks in the audio use
the same curve.
