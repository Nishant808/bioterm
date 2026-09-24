#!/usr/bin/env bash
# Master -> Twitter/X upload file.
# H.264 High@4.2, yuv420p (BT.709), 30 fps, 2 s GOP, CRF 14 (tune animation) capped at 20 Mbps,
# AAC-LC 192 kbps 48 kHz stereo, moov atom up front (+faststart).
# Usage: bash scripts/encode.sh [in.mp4] [out.mp4]
set -euo pipefail
cd "$(dirname "$0")/.."
IN="${1:-output/bioterm_30s_master.mp4}"
OUT="${2:-output/bioterm_30s_twitter.mp4}"
FFMPEG="${FFMPEG:-$(python3 -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null || command -v ffmpeg)}"
"$FFMPEG" -y -hide_banner -loglevel error -i "$IN" \
  -c:v libx264 -preset slow -profile:v high -level:v 4.2 -pix_fmt yuv420p \
  -tune animation -crf 14 -maxrate 20M -bufsize 40M -g 60 -keyint_min 30 -bf 2 -r 30 \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 \
  -c:a aac -b:a 192k -ar 48000 -ac 2 \
  -movflags +faststart "$OUT"
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
