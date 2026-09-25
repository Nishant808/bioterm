import React from 'react';
import {C, F} from '../../config/theme';
import {E, H, S, W, k, lerp} from '../core';
import R from '../reel.json';

// 31-35 s: a 3x2 mosaic fills on the beat. Each cell wipes in behind a colour
// block, then its number rolls like a slot machine and locks.
const A = S.numbers;
const COLS = 3;
const GAP = 18;
const MX = 150;
const MY = 170;
const CW = (W - MX * 2 - GAP * (COLS - 1)) / COLS;
const CH = (H - MY * 2 - GAP) / 2;
const BLOCK = [C.primary, C.violet, C.pos, '#39C5CF', C.warn, C.accentSoft];

const Roll: React.FC<{value: number; p: number}> = ({value, p}) => {
  const digits = String(value).split('');
  return (
    <div style={{display: 'flex', height: 170, overflow: 'hidden'}}>
      {digits.map((d, i) => {
        const dp = E.out(Math.min(1, Math.max(0, p * 1.25 - i * 0.12)));
        const spins = 2 + i;
        const pos = (Number(d) + spins * 10) * dp;
        return (
          <div key={i} style={{display: 'flex', flexDirection: 'column', transform: `translateY(${-pos * 170}px)`}}>
            {Array.from({length: (spins + 1) * 10}, (_, j) => (
              <div key={j} style={{height: 170, fontFamily: F.sans, fontWeight: 800, fontSize: 170, lineHeight: '170px', letterSpacing: -6, color: C.text}}>{j % 10}</div>
            ))}
          </div>
        );
      })}
    </div>
  );
};

export const Numbers: React.FC<{t: number}> = ({t}) => {
  if (t < A - 0.05 || t > S.finale + 0.6) return null;
  const lt = t - A;
  const push = k(lt, 0, 4, (x) => x);
  return (
    <div style={{position: 'absolute', inset: 0, transform: `scale(${lerp(1, 1.05, push)})`}}>
      {R.stats.map((s, i) => {
        const col = i % COLS;
        const row = Math.floor(i / COLS);
        const x = MX + col * (CW + GAP);
        const y = MY + row * (CH + GAP);
        const at = s.at - A;
        const wipe = k(lt, at, at + 0.22, E.inOut);
        const reveal = k(lt, at + 0.14, at + 0.36, E.inOut);
        const roll = k(lt, at + 0.1, at + 0.75, (q) => q);
        // collapse into the centre, outer cells first
        const d = Math.hypot(x + CW / 2 - W / 2, y + CH / 2 - H / 2);
        const c = k(t, S.finale - 0.35 + (1 - d / 900) * 0.25, S.finale + 0.2 + (1 - d / 900) * 0.25, E.in);
        const cx = lerp(0, W / 2 - (x + CW / 2), c);
        const cy = lerp(0, H / 2 - (y + CH / 2), c);
        return (
          <div key={i} style={{position: 'absolute', left: x, top: y, width: CW, height: CH, transform: `translate(${cx}px, ${cy}px) scale(${1 - c})`,
            opacity: 1 - k(c, 0.8, 1)}}>
            <div style={{position: 'absolute', inset: 0, borderRadius: 20, background: C.surface, border: `1px solid ${C.border}`, overflow: 'hidden',
              clipPath: `inset(0 ${(1 - reveal) * 100}% 0 0 round 20px)`}}>
              <div style={{position: 'absolute', left: 40, top: 46}}><Roll value={s.n} p={roll} /></div>
              <div style={{position: 'absolute', left: 44, bottom: 44, fontFamily: F.mono, fontSize: 24, letterSpacing: 8, color: C.text2}}>{s.label}</div>
              <div style={{position: 'absolute', right: 40, top: 44, width: 14, height: 14, borderRadius: 7, background: BLOCK[i], boxShadow: `0 0 20px ${BLOCK[i]}`}} />
              <div style={{position: 'absolute', left: 0, bottom: 0, height: 4, width: `${roll * 100}%`, background: BLOCK[i]}} />
            </div>
            {/* the colour block that wipes across first */}
            <div style={{position: 'absolute', inset: 0, borderRadius: 20, background: BLOCK[i],
              clipPath: `inset(0 ${(1 - wipe) * 100}% 0 ${reveal * 100}% round 20px)`}} />
          </div>
        );
      })}
    </div>
  );
};
