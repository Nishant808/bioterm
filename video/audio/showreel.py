"""Procedural soundtrack for the 40 s BioTerm motion reel (numpy/scipy, fixed seed).

No samples, no third-party music. 120 BPM in A minor; every hit sits on the
beat grid in src/reel/reel.json, so picture and sound are locked.

  0-3    heartbeat, trace ticks accelerate, riser -> impact
  3-7    identity: bell chord, sparkle converge, fly-through whoosh
  7-11   kinetic: full groove, a stab + glitch on every word
  11-16  universe: filtered groove, arp sparkle, riser into the zoom
  16-21  engine: detector ticks, formula blips, STRONG BUY hit at 19
  21-26  terminal: typing, candle ticks, whip
  26-31  copilot: half-time, typing, citation bells
  31-35  numbers: stab + slot ticks per stat, riser + snare roll, drop
  35.5   impact, A major shimmer, typed URL, tail
"""
import json
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 48000
ROOT = Path(__file__).resolve().parents[1]
REEL = json.loads((ROOT / "src" / "reel" / "reel.json").read_text())
DUR = float(REEL["duration"])
N = int(SR * DUR)
rng = np.random.default_rng(2026)
L = np.zeros(N)
R = np.zeros(N)
RV = np.zeros(N)
exec((Path(__file__).parent / "_instruments.py").read_text())  # t_axis, place, kick, hat, clap, tick, blip, bell, ...

SC = REEL["scenes"]
OUT = ROOT / "public" / "audio" / "showreel.wav"


def snare(gain=0.3):
    tt = t_axis(0.25)
    body = np.sin(2 * np.pi * 190 * tt) * np.exp(-tt / 0.05)
    n = bp(rng.standard_normal(len(tt)), 1500, 8000) * np.exp(-tt / 0.08)
    return (0.5 * body + n) * gain


def stab(midis, gain=0.12, dur=0.35, cutoff=3000):
    tt = t_axis(dur)
    x = np.zeros(len(tt))
    for m in midis:
        f = hz(m)
        for d in (-0.06, 0.06):
            x += signal.sawtooth(2 * np.pi * f * 2 ** (d / 12) * tt)
    x = lp(x / (2 * len(midis)), cutoff) * env(len(tt), 0.002, dur * 0.35, 3)
    return x * gain


def glitch(dur=0.18, gain=0.12):
    tt = t_axis(dur)
    sq = signal.square(2 * np.pi * rng.uniform(300, 1400) * tt) * (rng.random(len(tt)) > 0.5)
    chop = (np.floor(tt * 60) % 2)
    return lp(sq * chop, 6000) * np.exp(-tt / (dur * 0.5)) * gain


def rev_cymbal(dur=0.8, gain=0.08):
    tt = t_axis(dur)
    return hp(rng.standard_normal(len(tt)), 5000) * (tt / dur) ** 3 * gain


# ------------------------------------------------------------------ harmony
CHORDS = [
    (0.0, 3.0, [45, 52], 400, 0.05), (3.0, 7.0, [45, 52, 57, 60, 64], 900, 0.08),
    (7.0, 9.0, [41, 48, 53, 57], 1400, 0.07), (9.0, 11.0, [43, 50, 55, 59], 1600, 0.07),
    (11.0, 13.5, [45, 52, 57, 60], 700, 0.075), (13.5, 16.0, [41, 48, 53, 57, 60], 1200, 0.08),
    (16.0, 18.5, [45, 52, 57, 60, 64], 1800, 0.07), (18.5, 21.0, [43, 50, 55, 59, 62], 2000, 0.07),
    (21.0, 23.5, [41, 48, 53, 57], 1500, 0.065), (23.5, 26.0, [43, 50, 55, 59], 1500, 0.065),
    (26.0, 28.5, [45, 52, 57, 60], 900, 0.07), (28.5, 31.0, [41, 48, 53, 57, 60], 1100, 0.07),
    (31.0, 33.0, [45, 52, 57, 60, 64], 2200, 0.07), (33.0, 35.3, [43, 50, 55, 59, 62], 2600, 0.075),
    (35.5, 40.0, [45, 52, 57, 61, 64, 71], 1800, 0.08),
]
for a, b, notes, cutoff, g in CHORDS:
    for kk, m in enumerate(notes):
        v = saw_voice(hz(m), b - a + 0.6, detune=0.1, cutoff=cutoff, gain=g / np.sqrt(len(notes)),
                      attack=0.3 if a else 1.0, release=0.5 if b < 40 else 3.0)
        place(v, max(0, a - 0.1), pan=(kk / max(1, len(notes) - 1) - 0.5) * 0.7, rev=0.35)


def chord_at(x):
    return next((c for c in CHORDS if c[0] <= x < c[1]), CHORDS[-1])


# ------------------------------------------------------------------ 0-3 ignite
for x in (0.0, 0.5, 1.0):
    place(kick(0.4, dec=0.3, f0=95, f1=40), x)
    place(blip(hz(81), 0.03, 0.3), x, rev=0.6)
tt = t_axis(0.5)
place(np.sin(2 * np.pi * np.cumsum(120 + 700 * tt / 0.5) / SR) * np.sin(np.pi * tt / 0.5) * 0.05, 0.95)  # line stretches
for n in range(34):  # trace ticks, accelerating with the draw (ease in-out over 1.35-2.55)
    p = n / 34
    at = 1.35 + 1.2 * (0.5 - 0.5 * np.cos(np.pi * p))
    place(tick(2000 + 50 * n, 0.03 + 0.002 * n, 0.01), at, pan=0.5 * np.sin(n), rev=0.1)
place(bell(hz(88), 0.05, 0.8), 2.25, pan=0.4, rev=0.6)  # anomaly
place(noise_sweep(0.8, 300, 10000, gain=0.16), 2.2)
place(rev_cymbal(0.6, 0.08), 2.4)

# ------------------------------------------------------------------ hits
for h in REEL["hits"]:
    big = h in (3, 16, 35.5)
    place(impact(0.95 if big else 0.7, 2.2 if big else 1.4), h, rev=0.4)
    place(kick(0.8, dec=0.4), h)

# ------------------------------------------------------------------ 3-7 identity
place(bell(hz(69), 0.08, 2.4), 3.02, rev=0.7)
place(bell(hz(76), 0.05, 2.4), 3.05, pan=0.3, rev=0.7)
for j in range(24):  # particles converge: rising sparkle
    place(blip(hz([69, 72, 76, 79, 81, 84][j % 6] + 12), 0.02, 0.1), 3.05 + j * 0.03, pan=np.sin(j * 1.7) * 0.8, rev=0.5)
for j, at in enumerate([3.9, 4.0, 4.1, 4.2, 4.3, 4.4]):  # hex / pulse draw
    place(tick(1400 + 120 * j, 0.05, 0.015), at, rev=0.3)
place(blip(hz(76), 0.07, 0.4), 4.45, rev=0.6)  # the dot pops
for i in range(7):  # wordmark letters land
    place(tick(2600, 0.04, 0.008), 4.3 + i * 0.05 + 0.25, pan=(i - 3) * 0.12)
place(noise_sweep(0.9, 2000, 9000, 0.05, rising=False), 5.2)  # light sweep
for x in np.arange(5.0, 7.0, 0.25):  # anticipation hats
    place(hat(0.05 + 0.04 * (x - 5.0)), x, pan=0.2)
place(whoosh(0.7, 0.2, 300, 8000), 6.35, rev=0.3)  # fly-through
place(rev_cymbal(0.55, 0.1), 6.45)

# ------------------------------------------------------------------ groove (7-26, 31-35)
def in_groove(x):
    return (7.0 <= x < 26.0) or (31.0 <= x < 35.25)


x = 7.0
while x < 35.25:
    if in_groove(x):
        half_filtered = 11.0 <= x < 13.5  # universe intro: kick only on 1 and 3
        if not half_filtered or (round(x * 2) % 2 == 0):
            place(kick(0.55 if x < 31 else 0.65), x)
        if round(x * 2) % 2 == 1 and not half_filtered:
            place(clap(0.14), x, rev=0.25)
        for s16 in range(2):
            place(hat(0.07 if s16 == 0 else 0.04), x + s16 * 0.25 + 0.125 * (1 if s16 else 0), pan=0.25)
        # bass: 8ths on the chord root
        root = hz(chord_at(x)[2][0] - 12)
        for e8 in (0.0, 0.25):
            tt = t_axis(0.22)
            v = signal.sawtooth(2 * np.pi * root * tt) + 0.6 * np.sin(2 * np.pi * root * tt)
            place(lp(v, 500 if not half_filtered else 250) * env(len(tt), 0.004, 0.12, 3) * 0.16, x + e8)
    x += 0.5
# copilot half-time 26-31: soft kick on 1, rim on 3
for x in np.arange(26.0, 31.0, 1.0):
    place(kick(0.35, dec=0.3), x)
    place(tick(900, 0.06, 0.02), x + 0.5, rev=0.3)

# ------------------------------------------------------------------ 7-11 kinetic
for w in REEL["words"]:
    at = w["at"]
    place(stab([m + 12 for m in chord_at(at + 0.01)[2][1:]], 0.14), at, rev=0.3)
    place(glitch(0.2, 0.1), at + 0.02, pan=0.3)
    for j in range(len(w["sub"]) // 3):  # the sub-line types
        place(tick(3000 + 60 * (j % 5), 0.012, 0.005), at + 0.3 + j * 0.035, pan=-0.3)
place(whoosh(0.5, 0.16, 400, 7000), 7.0)  # halves slide in
for j in range(5):
    place(blip(hz(64 + j * 3), 0.03, 0.12), 8.05 + j * 0.05, rev=0.3)  # cards fan
place(noise_sweep(0.8, 500, 9000, 0.1, rising=False), 9.0)  # wires streak
tt = t_axis(0.6)  # counter rolls up
place(np.sin(2 * np.pi * np.cumsum(300 + 1500 * (tt / 0.6) ** 0.5) / SR) * (1 - tt / 0.6) * 0.04, 10.05)
place(whoosh(0.45, 0.2, 500, 9000), 10.65)  # whip

# ------------------------------------------------------------------ 11-16 universe
x = 11.3
i = 0
while x < 15.9:  # arp sparkle
    ch = chord_at(x)[2]
    tones = [m + 24 for m in ch[1:]]
    tt = t_axis(0.2)
    v = signal.square(2 * np.pi * hz(tones[i % len(tones)]) * tt, 0.3) * env(len(tt), 0.002, 0.07, 3)
    place(lp(v, 2500 + 3000 * min(1, (x - 11.3) / 4)) * 0.025, x, pan=np.sin(i * 0.9) * 0.6, rev=0.4)
    x += 0.125
    i += 1
place(whoosh(1.0, 0.1, 200, 3000), 13.1, rev=0.4)  # sphere -> grid morph
for j in range(20):  # ripple
    place(tick(1800 + 60 * j, 0.02, 0.012), 14.3 + j * 0.04, pan=np.cos(j) * 0.7, rev=0.3)
place(noise_sweep(1.0, 300, 9000, 0.14), 15.0)  # zoom riser
place(rev_cymbal(0.6, 0.09), 15.4)

# ------------------------------------------------------------------ 16-21 engine
for n in range(39):  # detector bars grow (0.25 + i*0.02 .. + 0.6)
    place(tick(1500 + 40 * n, 0.03, 0.01), 16.3 + n * 0.02, pan=np.sin(n * 0.7) * 0.7)
for j in range(7):  # formula glyphs
    place(blip(hz([69, 72, 74, 76, 79, 81, 84][j]), 0.035, 0.15), 17.0 + j * 0.08, rev=0.4)
tt = t_axis(1.3)  # needle sweep
place(np.sin(2 * np.pi * np.cumsum(200 + 600 * (tt / 1.3)) / SR) * np.sin(np.pi * tt / 1.3) * 0.03, 17.6)
place(stab([69, 72, 76, 81], 0.16, 0.6), 19.0, rev=0.4)  # STRONG BUY
place(bell(hz(81), 0.06, 1.6), 19.02, rev=0.6)
place(whoosh(0.6, 0.12, 300, 5000), 20.4)

# ------------------------------------------------------------------ 21-26 terminal
for j in range(8):  # typing "VRTX CAT"
    place(tick(2200 + 100 * (j % 4), 0.07, 0.009), 21.7 + j * 0.056)
place(blip(hz(76), 0.05, 0.25), 22.2, rev=0.3)  # enter
for n in range(64):  # candles print
    place(tick(2800 + 20 * (n % 8), 0.012, 0.004), 22.3 + n * (1.7 / 64), pan=-0.6 + 1.2 * n / 64)
place(blip(hz(81), 0.05, 0.3), 23.6, rev=0.5)  # buy marker
place(whoosh(0.5, 0.2, 400, 9000), 25.55)  # whip

# ------------------------------------------------------------------ 26-31 copilot
for j in range(38):  # question types
    place(tick(2400 + 80 * (j % 6), 0.03, 0.007), 26.35 + j * 0.024, pan=0.2)
for j in range(30):  # answer streams
    place(tick(1200 + 40 * (j % 7), 0.02, 0.02), 27.45 + j * 0.065, pan=-0.2, rev=0.2)
ANS = 29 + 3  # words + chips in the answer
for ci, frac in enumerate((6 / ANS, 16 / ANS, 1.0)):
    at = 27.45 + frac * 1.95
    place(bell(hz([76, 79, 83][ci]), 0.06, 1.2), at, pan=0.4, rev=0.6)
    place(whoosh(0.45, 0.05, 1500, 8000), at + 0.05, pan=0.5)
place(whoosh(0.5, 0.12, 300, 4000), 30.5)  # fold

# ------------------------------------------------------------------ 31-35 numbers
for s in REEL["stats"]:
    at = s["at"]
    place(stab([m + 12 for m in chord_at(at + 0.01)[2][1:4]], 0.1, 0.25), at, rev=0.3)
    for j in range(10):  # slot machine
        place(tick(3200 - 80 * j, 0.025, 0.006), at + 0.1 + j * 0.06, pan=0.3)
place(noise_sweep(1.3, 300, 12000, 0.18), 34.0)  # final riser
for n_, x in enumerate(np.concatenate([np.arange(34.25, 34.75, 0.125), np.arange(34.75, 35.25, 0.0625)])):
    place(snare(0.06 + 0.12 * (x - 34.25)), x, pan=0.1 * (-1) ** n_)
tt = t_axis(0.35)  # implosion: a falling tone into the silence
place(np.sin(2 * np.pi * np.cumsum(900 - 800 * (tt / 0.35)) / SR) * (1 - tt / 0.35) * 0.05, 35.05)

# ------------------------------------------------------------------ 35.5 finale
for kk, m in enumerate((69, 73, 76, 81, 83, 88)):
    place(bell(hz(m), 0.05, 3.2), 35.52 + kk * 0.03, pan=(kk - 2.5) * 0.2, rev=0.8)
tt = t_axis(4.0)  # sub swell under the logo
place(np.sin(2 * np.pi * hz(33) * tt) * env(len(tt), 0.05, 2.0, 1.5) * 0.25, 35.5)
place(noise_sweep(0.9, 2000, 9000, 0.05, rising=False), 37.0)  # light sweep
for j, at in enumerate((36.5, 36.62, 36.74, 36.86)):  # tagline words
    place(blip(hz([69, 72, 76, 81][j]), 0.04, 0.3), at, rev=0.6)
for j in range(21):  # URL types
    place(tick(2600 + 50 * (j % 5), 0.035, 0.007), 37.7 + j * 0.033)
place(bell(hz(93), 0.03, 1.5), 38.45, rev=0.8)

# ------------------------------------------------------------------ reverb + master
ir_t = t_axis(2.4)
ir = rng.standard_normal(len(ir_t)) * np.exp(-ir_t / 0.6)
ir = lp(ir, 5000)
ir /= np.sqrt(np.sum(ir ** 2))
wet = signal.fftconvolve(RV, ir)[:N] * 0.9
mix = np.stack([hp(L + wet, 28), hp(R + np.roll(wet, int(0.013 * SR)), 28)])
mix = np.tanh(mix * 1.3) / np.tanh(1.3)
fade = np.ones(N)
fade[-int(0.7 * SR):] = np.linspace(1, 0, int(0.7 * SR)) ** 2
fade[: int(0.01 * SR)] = np.linspace(0, 1, int(0.01 * SR))
mix *= fade
mix = mix / np.max(np.abs(mix)) * 10 ** (-1.5 / 20)
OUT.parent.mkdir(parents=True, exist_ok=True)
wavfile.write(OUT, SR, (mix.T * 32767).astype(np.int16))
print(f"wrote {OUT}  {DUR}s  rms {20 * np.log10(np.sqrt(np.mean(mix ** 2))):.1f} dBFS")
