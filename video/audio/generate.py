"""Procedural soundtrack + sound design for the BioTerm 30s film.

Everything is synthesised here (numpy/scipy, fixed seed) - no samples, no
third-party music - so the audio is original and cleared for posting.
Cue times mirror src/config/timing.ts (BEAT) and the chart draw curve in
src/scenes/marketState.ts; retime both together.

Structure (A minor, 120 BPM):
  0-4   sub pulse + market ticks that accelerate with the chart, riser, impact
  4-8   tension: pad moves to F, data sweeps as the camera dives
  8-15  rhythm arrives (hats, then kick, clap, arp); network blips
  15-20 strongest build: riser + snare roll into the product
  20-24 peak groove under the investigation; UI clicks and typing
  24-27 release: drums out, soft hits on each line of type
  27-30 logo impact, A major resolution, clean tail
"""
import json
from pathlib import Path

import numpy as np
from scipy import signal

SR = 48000
DUR = 30.0
N = int(SR * DUR)
rng = np.random.default_rng(20260819)
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "audio" / "soundtrack.wav"
B = json.loads((ROOT / "src" / "config" / "timeline.json").read_text())["beat"]
S = B["steps"]

L = np.zeros(N)
R = np.zeros(N)
RV = np.zeros(N)  # reverb send (mono)


def t_axis(d):
    return np.arange(int(d * SR)) / SR


def place(x, at, gain=1.0, pan=0.0, rev=0.0):
    i = int(at * SR)
    if i >= N:
        return
    x = x[: N - i]
    lg, rg = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    L[i : i + len(x)] += x * gain * lg * 1.414
    R[i : i + len(x)] += x * gain * rg * 1.414
    RV[i : i + len(x)] += x * gain * rev


def env(n, a, d, curve=4.0):
    tt = np.arange(n) / SR
    e = np.minimum(1, tt / max(a, 1e-4)) * np.exp(-curve * np.maximum(0, tt - a) / max(d, 1e-4))
    return e


def lp(x, fc, order=2):
    b, a = signal.butter(order, min(fc, SR / 2 - 100) / (SR / 2), "low")
    return signal.lfilter(b, a, x)


def hp(x, fc, order=2):
    b, a = signal.butter(order, fc / (SR / 2), "high")
    return signal.lfilter(b, a, x)


def bp(x, lo, hi, order=2):
    b, a = signal.butter(order, [lo / (SR / 2), min(hi, SR / 2 - 100) / (SR / 2)], "band")
    return signal.lfilter(b, a, x)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


# ------------------------------------------------------------------ instruments
def kick(gain=1.0, dec=0.35, f0=150, f1=44):
    tt = t_axis(dec * 2.2)
    f = f1 + (f0 - f1) * np.exp(-tt * 38)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-tt / dec)
    x += 0.15 * lp(rng.standard_normal(len(tt)), 3000) * np.exp(-tt * 90)
    return np.tanh(1.6 * x) * gain


def hat(gain=0.2, dec=0.035):
    tt = t_axis(0.12)
    return hp(rng.standard_normal(len(tt)), 7500, 3) * np.exp(-tt / dec) * gain


def clap(gain=0.3):
    tt = t_axis(0.35)
    n = bp(rng.standard_normal(len(tt)), 900, 4200)
    e = np.exp(-tt / 0.09)
    for k in (0.0, 0.012, 0.024):
        e += 0.6 * np.exp(-np.maximum(0, tt - k) / 0.008) * (tt >= k)
    return n * e * gain


def tick(freq=2600, gain=0.12, dec=0.012):
    tt = t_axis(0.06)
    return (np.sin(2 * np.pi * freq * tt) + 0.3 * rng.standard_normal(len(tt))) * np.exp(-tt / dec) * gain


def blip(freq, gain=0.08, dec=0.18):
    tt = t_axis(dec * 4)
    x = np.sin(2 * np.pi * freq * tt) + 0.25 * np.sin(4 * np.pi * freq * tt)
    return x * env(len(tt), 0.003, dec) * gain


def bell(freq, gain=0.1, dec=2.4):
    tt = t_axis(dec * 1.8)
    x = sum(a * np.sin(2 * np.pi * freq * m * tt) * np.exp(-tt * m / dec) for m, a in ((1, 1), (2.01, 0.35), (3.98, 0.12), (5.43, 0.05)))
    return x * env(len(tt), 0.004, dec, 1.0) * gain


def saw_voice(freq, dur, detune=0.08, cutoff=1200, gain=0.1, attack=0.6, release=0.8):
    tt = t_axis(dur)
    x = np.zeros(len(tt))
    for d in (-detune, 0, detune):
        f = hz(freq + d) if freq < 200 else freq * 2 ** (d / 12)
        x += signal.sawtooth(2 * np.pi * f * tt + rng.uniform(0, 6.28))
    x = lp(x / 3, cutoff)
    e = np.minimum(1, tt / attack) * np.minimum(1, np.maximum(0, (dur - tt) / release))
    return x * e * gain


def noise_sweep(dur, f_lo, f_hi, gain=0.2, rising=True):
    tt = t_axis(dur)
    n = rng.standard_normal(len(tt))
    out = np.zeros(len(tt))
    seg = int(0.02 * SR)
    for i in range(0, len(tt), seg):
        p = i / len(tt)
        p = p if rising else 1 - p
        fc = f_lo * (f_hi / f_lo) ** p
        out[i : i + seg] = bp(n[max(0, i - 2000) : i + seg], fc * 0.7, fc * 1.4)[-len(n[i : i + seg]) :]
    e = np.sin(np.pi * np.clip(tt / dur, 0, 1)) ** 1.5 if not rising else (tt / dur) ** 2.2
    return out * e * gain


def whoosh(dur=0.8, gain=0.18, lo=300, hi=5000):
    tt = t_axis(dur)
    n = rng.standard_normal(len(tt))
    out = np.zeros(len(tt))
    seg = int(0.015 * SR)
    for i in range(0, len(tt), seg):
        p = i / len(tt)
        fc = lo * (hi / lo) ** np.sin(np.pi * p)
        out[i : i + seg] = bp(n[max(0, i - 1500) : i + seg], fc * 0.6, fc * 1.6)[-len(n[i : i + seg]) :]
    return out * np.sin(np.pi * tt / dur) ** 2 * gain


def impact(gain=0.9, tail=1.6):
    tt = t_axis(tail)
    f = 38 + 50 * np.exp(-tt * 9)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / (tail * 0.35))
    x += 0.35 * lp(rng.standard_normal(len(tt)), 900) * np.exp(-tt * 14)
    return np.tanh(1.3 * x) * gain


# ------------------------------------------------------------------ harmony
# (start, end, notes as midi)  A minor world; resolves to A major.
CHORDS = [
    (0.0, 4.0, [45, 52]),  # A2 E3 - drone
    (4.0, 8.0, [41, 48, 52, 57]),  # Fmaj7 - tension
    (8.0, 12.0, [45, 52, 57, 60]),  # Am
    (12.0, 15.0, [43, 50, 55, 59]),  # G
    (15.0, 19.6, [41, 48, 53, 57, 60]),  # F - build
    (19.6, 24.0, [45, 52, 57, 60, 64]),  # Am - peak
    (24.0, 27.0, [41, 48, 57, 60]),  # F - release
    (27.0, 30.0, [45, 52, 57, 61, 64, 71]),  # A major add9 - resolution
]
pad_gain = {0: 0.06, 1: 0.12, 2: 0.09, 3: 0.075, 4: 0.085, 5: 0.08, 6: 0.07, 7: 0.075}
for ci, (a, b, notes) in enumerate(CHORDS):
    dur = b - a + 0.9
    cutoff = [500, 700, 900, 1100, 1500, 2200, 1200, 1800][ci]
    for k, m in enumerate(notes):
        v = saw_voice(hz(m), dur, detune=0.1, cutoff=cutoff, gain=pad_gain[ci] / np.sqrt(len(notes)), attack=0.5 if ci else 1.2, release=0.9 if ci < 7 else 2.6)
        place(v, a - 0.15 if ci else 0.0, pan=(k / max(1, len(notes) - 1) - 0.5) * 0.6, rev=0.35)

# sub bass on the root, 8ths from 9s through the peak
for ci, (a, b, notes) in enumerate(CHORDS):
    root = hz(notes[0] - 12 if notes[0] > 40 else notes[0])
    if b <= 9.0 or a >= 24.0:
        continue
    step = 0.5 if a < 19.6 else 0.25
    tt0 = max(a, 9.0)
    x = tt0
    while x < b - 0.01:
        tt = t_axis(step * 0.95)
        v = np.sin(2 * np.pi * root * tt) + 0.2 * np.sin(4 * np.pi * root * tt)
        place(v * env(len(tt), 0.005, step * 0.6, 2.5), x, gain=0.16 if a >= 19.6 else 0.11)
        x += step

# ------------------------------------------------------------------ 01 market
# low heartbeat pulse
for x in np.arange(0.25, 4.0, 1.0):
    place(kick(0.35, dec=0.25, f0=90, f1=40), x)
# ticks follow the chart: k(t) = 26*(0.5p + 0.5p^3), p over [0.55, 2.72]
ps = np.linspace(0, 1, 20000)
ks = 26 * (0.5 * ps + 0.5 * ps**3)
for n in range(1, 27):
    p = ps[np.searchsorted(ks, n)]
    at = 0.55 + p * (2.72 - 0.55)
    place(tick(2300 + 40 * n, gain=0.05 + 0.004 * n), at, pan=0.35 if n % 2 else -0.35, rev=0.1)
place(noise_sweep(0.8, 400, 9000, gain=0.12), 2.32)  # riser into the spike
tt = t_axis(0.42)
place(np.sin(2 * np.pi * np.cumsum(220 + 900 * (tt / 0.42) ** 2) / SR) * (tt / 0.42) * 0.05, 2.72)
place(impact(0.85, 2.0), 3.12, rev=0.35)
place(bell(hz(76), 0.05, 1.6), 3.14, pan=0.3, rev=0.6)
# text hits
place(blip(hz(69), 0.05, 0.25), 3.05, rev=0.4)
place(blip(hz(72), 0.05, 0.25), 3.5, rev=0.4)

# ------------------------------------------------------------------ 02 question
place(whoosh(1.1, 0.14, 200, 4000), 4.2, rev=0.3)  # camera starts the dive
place(bell(hz(64), 0.06, 2.0), 4.45, pan=-0.2, rev=0.7)  # BUT WHY
place(noise_sweep(2.2, 200, 3000, gain=0.07), 4.7)  # falling into the chart
for i in range(16):  # data stream: fast soft ticks
    place(tick(3200 + 150 * (i % 5), 0.018, 0.006), 5.0 + i * 0.09, pan=np.sin(i) * 0.7)
place(whoosh(0.9, 0.16, 500, 7000), 6.35, rev=0.3)  # stream folds into the graph

# tension: an 8th-note bass pulse on F whose filter opens as the camera dives
for n_, x in enumerate(np.arange(4.0, 9.0, 0.25)):
    tt = t_axis(0.22)
    f = hz(29)
    v = signal.sawtooth(2 * np.pi * f * tt) + 0.5 * signal.sawtooth(2 * np.pi * f * 2.005 * tt)
    v = lp(v, 180 + 900 * min(1, (x - 4.0) / 4.0)) * env(len(tt), 0.004, 0.12, 3)
    place(v, x, gain=0.2 + 0.12 * min(1, (x - 4.0) / 4.0), pan=0.0)
for x in np.arange(5.0, 8.0, 0.5):  # soft off-beat ticks keep time under the question
    place(tick(1800, 0.04, 0.01), x + 0.25, pan=0.4, rev=0.2)
    place(hat(0.05, 0.02), x, pan=-0.3)

# ------------------------------------------------------------------ 03-04 network
PENTA = [57, 60, 62, 64, 67, 69, 72, 74, 76]
place(blip(hz(57), 0.1, 0.4), 6.95, rev=0.5)
for i in range(10):
    place(blip(hz(PENTA[(i * 3) % len(PENTA)] + 12), 0.04, 0.16), 7.1 + i * 0.03, pan=np.cos(i * 1.3) * 0.6, rev=0.4)
for j in range(30):
    place(blip(hz(PENTA[(j * 5) % len(PENTA)] + 12), 0.022, 0.12), 7.7 + j * 0.085, pan=np.sin(j * 2.1) * 0.8, rev=0.35)
for j in range(10):  # decode typing
    place(tick(1800 + 90 * j, 0.03, 0.01), 10.8 + j * 0.07, pan=np.sin(j) * 0.5)
# hats from 8s (8ths), 16ths from 11s
x = 8.0
while x < 24.0:
    sixteenth = x >= 11.0
    place(hat(0.05 if sixteenth and (round(x * 4) % 2) else 0.085), x, pan=0.25)
    x += 0.125 if sixteenth else 0.25
# kick four-on-the-floor 9 -> 24 (drops out for the build's last bar)
for x in np.arange(9.0, 24.0, 0.5):
    if S[0] - 1.0 <= x < S[0]:
        continue
    place(kick(0.3 + 0.25 * min(1, (x - 9.0) / 9.0) if x < S[0] else 0.72), x)
for x in np.arange(11.5, 24.0, 1.0):
    if S[0] - 1.0 <= x < S[0]:
        continue
    place(clap(0.1 + 0.06 * min(1, (x - 11.0) / 7.0) if x < S[0] else 0.2), x, rev=0.25)
# arp 11 -> 24 on chord tones
x = 11.0
i = 0
while x < 24.0:
    ch = next(c for c in CHORDS if c[0] <= x < c[1])
    tones = [m + 12 for m in ch[2][1:]] + [ch[2][1] + 24]
    f = hz(tones[i % len(tones)])
    tt = t_axis(0.2)
    v = signal.square(2 * np.pi * f * tt, 0.3) * env(len(tt), 0.002, 0.08, 3)
    cutoff = 900 + 3500 * min(1, (x - 11.0) / 9.0)
    place(lp(v, cutoff) * 0.03, x, pan=np.sin(i * 0.9) * 0.5, rev=0.3)
    x += 0.125
    i += 1
place(whoosh(1.2, 0.18, 300, 6000), 13.9, rev=0.4)  # converge
place(noise_sweep(1.1, 300, 8000, 0.1), 13.9)

# ------------------------------------------------------------------ 05 reveal + build
place(impact(0.6, 1.4), 14.95, rev=0.4)
place(bell(hz(69), 0.07, 2.2), 14.97, rev=0.6)
tt = t_axis(0.6)  # the window opening: a rising scan tone
place(np.sin(2 * np.pi * np.cumsum(400 + 2400 * tt / 0.6) / SR) * np.sin(np.pi * tt / 0.6) * 0.03, 15.0, rev=0.3)
LANDINGS = [0.05] + [0.3 + i * 0.08 for i in range(4)] + [0.65 + i * 0.05 for i in range(10)]  # S05Reveal.TARGETS
for k, off in enumerate(LANDINGS):  # each converged node lands on an interface element
    place(tick(1500 + 90 * k, 0.035, 0.02), B["appIn"] + off, pan=(k % 3 - 1) * 0.4, rev=0.2)
place(noise_sweep(2.1, 200, 10000, 0.16), 17.5)  # the big riser
for n_, x in enumerate(np.concatenate([np.arange(S[0] - 1.0, S[0] - 0.5, 0.125), np.arange(S[0] - 0.5, S[0], 0.0625)])):
    place(clap(0.05 + 0.1 * (x - S[0] + 1.0)), x, pan=0.1 * (-1) ** n_)

# ------------------------------------------------------------------ 06 flow (peak)
place(impact(0.8, 1.8), S[0], rev=0.4)
place(bell(hz(81), 0.05, 1.8), S[0] + 0.02, pan=0.2, rev=0.6)
for at in (S[0] - 0.02, S[1] - 0.02, S[2], S[4]):  # clicks (TerminalUI.CLICKS)
    place(tick(1200, 0.12, 0.008), at, rev=0.15)
    place(tick(3400, 0.05, 0.004), at + 0.004)
for j in range(4):  # typing MRNA (typeAt = S0 + 0.32, 0.3 s)
    place(tick(2000 + 150 * j, 0.06, 0.009), S[0] + 0.32 + j * 0.075)
place(blip(hz(76), 0.045, 0.2), S[0] + 0.7, rev=0.4)  # search filters to one row
for j, at in enumerate(S[1:5]):  # step transitions: soft sweeps
    place(whoosh(0.35, 0.05, 1500, 7000), at - 0.1, pan=0.3 * (-1) ** j)
place(blip(hz(76), 0.05, 0.3), S[3] + 0.2, rev=0.5)  # thesis highlight
place(blip(hz(81), 0.06, 0.35), S[4] + 0.12, rev=0.5)  # score breakdown

# ------------------------------------------------------------------ 07 message
place(whoosh(1.0, 0.1, 200, 3000), 23.75, rev=0.4)  # UI recedes
tt = t_axis(0.6)
place(hp(rng.standard_normal(len(tt)), 5000) * (tt / 0.6) ** 3 * 0.06, 23.4)  # reverse cymbal into release
for at, m in ((24.25, 57), (25.05, 60)):
    place(kick(0.35, dec=0.3, f0=110, f1=45), at)
    place(bell(hz(m + 12), 0.05, 1.4), at, rev=0.6)
place(noise_sweep(0.9, 300, 6000, 0.08), 25.1)
place(impact(0.55, 1.2), 25.95, rev=0.4)
place(bell(hz(69), 0.06, 1.8), 25.96, rev=0.6)

# ------------------------------------------------------------------ 08 end card
place(impact(1.0, 2.6), 27.0, rev=0.5)
for k, m in enumerate((69, 73, 76, 81, 83)):  # A major add9 shimmer
    place(bell(hz(m), 0.05, 2.8), 27.02 + k * 0.035, pan=(k - 2) * 0.25, rev=0.8)
place(blip(hz(88), 0.03, 0.4), 28.2, rev=0.7)  # url

# ------------------------------------------------------------------ reverb + master
ir_t = t_axis(2.2)
ir = rng.standard_normal(len(ir_t)) * np.exp(-ir_t / 0.55)
ir = lp(ir, 5000)
ir /= np.sqrt(np.sum(ir**2))
wet = signal.fftconvolve(RV, ir)[:N] * 0.9
wetL = wet
wetR = np.roll(wet, int(0.013 * SR))
mixL = hp(L + wetL, 28)
mixR = hp(R + wetR, 28)
# gentle bus glue + soft clip
mix = np.stack([mixL, mixR])
mix = np.tanh(mix * 1.25) / np.tanh(1.25)
# fade the last 0.4s so the final frame lands in silence
fade = np.ones(N)
fade[-int(0.4 * SR) :] = np.linspace(1, 0, int(0.4 * SR)) ** 2
fade[: int(0.01 * SR)] = np.linspace(0, 1, int(0.01 * SR))
mix *= fade
peak = np.max(np.abs(mix))
mix = mix / peak * 10 ** (-2.6 / 20)  # -2.6 dBFS sample peak -> ~-14 LUFS, true peak < -1 dBTP after AAC
rms = np.sqrt(np.mean(mix**2))
pcm = (mix.T * 32767).astype(np.int16)
from scipy.io import wavfile

OUT.parent.mkdir(parents=True, exist_ok=True)
wavfile.write(OUT, SR, pcm)
print(f"wrote {OUT}  peak -2.6 dBFS  rms {20*np.log10(rms):.1f} dBFS  {DUR}s @ {SR} Hz")
