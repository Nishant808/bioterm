import React from 'react';
import {C, F} from '../config/theme';
import {BEAT} from '../config/timing';
import type {Layout} from '../config/layout';
import {E, lerp, prog} from '../lib/anim';
import {FocusListPage, NavBar, NAV_X, OverviewPage, ScoreBreakdown, StockDetailPage} from './terminal/pages';

const S = BEAT.steps;
const BAR = 30; // url strip height, px at 1080p

/** Window geometry at time t (the terminal opens as a scan line, then unfolds). */
export const windowRect = (t: number, L: Layout) => {
  const {w, h, u, cx, cy, vertical} = L;
  const W = vertical ? 0.93 * w : 0.9 * w;
  const H = vertical ? 0.64 * h : 0.88 * h;
  const Y = vertical ? 0.18 * h : 0.054 * h;
  const pw = E.out(prog(t, BEAT.windowW[0], BEAT.windowW[1]));
  const ph = E.out(prog(t, BEAT.windowH[0], BEAT.windowH[1]));
  const ww = lerp(8 * u, W, pw);
  const hh = lerp(2 * u, H, ph);
  const midY = lerp(cy, Y + H / 2, ph);
  return {x: cx - ww / 2, y: midY - hh / 2, w: ww, h: hh, W, H, open: ph};
};

type Key = {t: number; fx: number; fy: number; z: number; d: number};
const KEYS: Key[] = [
  {t: BEAT.appIn, fx: 960, fy: 528, z: 1.0, d: 0.01},
  {t: 16.9, fx: 960, fy: 515, z: 1.02, d: 2.4},
  {t: S[0] + 0.05, fx: 720, fy: 330, z: 1.5, d: 0.45},
  {t: S[1] + 0.05, fx: 955, fy: 470, z: 1.22, d: 0.4},
  {t: S[1] + 0.5, fx: 955, fy: 800, z: 1.0, d: 0.5},
  {t: S[2] + 0.05, fx: 955, fy: 1000, z: 1.3, d: 0.45},
  {t: S[3] + 0.02, fx: 630, fy: 620, z: 1.62, d: 0.45},
  {t: S[4] + 0.02, fx: 700, fy: 440, z: 1.36, d: 0.45},
  {t: BEAT.uiRecede[0], fx: 960, fy: 640, z: 1.0, d: 1.2},
];

/** Camera over the app (virtual 1920px-wide page). */
export const camera = (t: number, vertical: boolean, L?: Layout) => {
  let {fx, fy, z} = KEYS[0];
  for (let i = 1; i < KEYS.length; i++) {
    const k = KEYS[i];
    const p = E.inOut(prog(t, k.t, k.t + k.d));
    fx = lerp(fx, k.fx, p);
    fy = lerp(fy, k.fy, p);
    z = lerp(z, k.z, p);
  }
  if (!vertical || !L) return {fx, fy, z};
  // 9:16: a narrower window, so zoom harder and keep the page's top-left in frame
  const zv = z * 1.25;
  const r = windowRect(t, L);
  const visW = 1920 / zv;
  const visH = ((r.H - BAR * L.u) / (r.W / 1920)) / zv;
  return {fx: Math.min(Math.max(fx, visW / 2), 1920 - visW / 2), fy: Math.max(fy, visH / 2), z: zv};
};

/** Virtual app point -> screen point. */
export const appToScreen = (t: number, L: Layout, vx: number, vy: number) => {
  const r = windowRect(t, L);
  const cam = camera(t, L.vertical, L);
  const base = r.W / 1920;
  const bar = BAR * L.u;
  return {x: r.x + r.w / 2 + (vx - cam.fx) * base * cam.z, y: r.y + bar + (r.h - bar) / 2 + (vy - cam.fy) * base * cam.z};
};

export const TerminalUI: React.FC<{t: number; L: Layout}> = ({t, L}) => {
  if (t < BEAT.windowW[0] || t > BEAT.lockup + 0.4) return null;
  const {u} = L;
  const r = windowRect(t, L);
  const cam = camera(t, L.vertical, L);
  const base = r.W / 1920;
  const bar = BAR * u;
  const recede = E.inOut(prog(t, BEAT.uiRecede[0], BEAT.uiRecede[1]));
  const gone = E.inOut(prog(t, BEAT.lockup - 0.2, BEAT.lockup + 0.35));
  const appP = prog(t, BEAT.appIn - 0.1, BEAT.appIn + 0.2);

  const page = t < S[0] + 0.12 ? 'overview' : t < S[1] + 0.12 ? 'focus' : 'stock';
  const navActive = t < S[0] + 0.06 ? 0 : t < S[1] + 0.06 ? 1 : 2;
  const hl = E.inOut(prog(t, S[0], S[0] + 0.22)) + E.inOut(prog(t, S[1], S[1] + 0.22));
  const fadeOld = (sw: number) => 1 - prog(t, sw - 0.1, sw + 0.02);

  return (
    <div
      style={{
        position: 'absolute', left: r.x, top: r.y, width: r.w, height: r.h, borderRadius: 12 * u, overflow: 'hidden',
        background: C.bg, border: `1px solid ${r.open > 0.2 ? C.borderStrong : C.accent}`,
        boxShadow: `0 ${40 * u}px ${120 * u}px rgba(0,0,0,0.6), 0 0 0 1px rgba(91,157,255,${0.25 * (1 - appP)})`,
        opacity: lerp(1, 0.2, recede) * (1 - gone), filter: recede > 0 ? `blur(${7 * recede * u}px)` : undefined,
        transform: `scale(${lerp(1, 0.95, recede)})`,
      }}
    >
      {/* url strip */}
      <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: bar, borderBottom: `1px solid ${C.border}`, background: '#090C11', display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: appP}}>
        <span style={{fontFamily: F.mono, fontSize: 12.5 * u, color: C.muted, letterSpacing: 0.4 * u}}>
          <span style={{color: C.pos, marginRight: 8 * u}}>●</span>bioterm.streamlit.app
        </span>
      </div>
      <div style={{position: 'absolute', left: 0, top: bar, width: r.w, height: r.h - bar, overflow: 'hidden', opacity: appP}}>
        <div
          style={{
            position: 'absolute', left: 0, top: 0, width: 1920, height: 1700, fontFamily: F.sans, color: C.text, transformOrigin: '0 0',
            transform: `translate(${r.w / 2}px, ${(r.h - bar) / 2}px) scale(${base * cam.z}) translate(${-cam.fx}px, ${-cam.fy}px)`,
          }}
        >
          <NavBar active={navActive} p={E.out(prog(t, BEAT.appIn, BEAT.appIn + 0.4))} hl={hl} />
          {(page === 'overview' || fadeOld(S[0] + 0.12) > 0) && t < S[0] + 0.15 && (
            <div style={{opacity: page === 'overview' ? 1 : fadeOld(S[0] + 0.12)}}>
              <OverviewPage t={t} t0={BEAT.appIn} />
            </div>
          )}
          {(page === 'focus' || (page === 'stock' && t < S[1] + 0.15)) && (
            <div style={{opacity: page === 'focus' ? 1 : fadeOld(S[1] + 0.12)}}>
              <FocusListPage t={t} t0={S[0] + 0.12} typeAt={S[0] + 0.32} filterAt={S[0] + 0.66} />
            </div>
          )}
          {page === 'stock' && (
            <>
              <StockDetailPage
                t={t} t0={S[1] + 0.12} tab={t < S[2] + 0.08 ? 'price' : 'news'} tabAt={S[2] + 0.08}
                focusGlow={E.out(prog(t, S[4], S[4] + 0.3))} trackGlow={E.out(prog(t, S[3] + 0.2, S[3] + 0.5))}
              />
              <ScoreBreakdown t={t} t0={S[4] + 0.12} />
            </>
          )}
        </div>
      </div>
    </div>
  );
};

/** Click targets for the flow scene, in virtual app coordinates. */
export const CLICKS = [
  {t: S[0] - 0.02, vx: NAV_X[1] + 45, vy: 26},
  {t: S[1] - 0.02, vx: NAV_X[2] + 50, vy: 26},
  {t: S[2], vx: 656, vy: 745},
  {t: S[4], vx: 400, vy: 340},
];
