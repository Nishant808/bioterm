"""Instrument + DSP primitives shared by the soundtracks (extracted from generate.py)."""
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


