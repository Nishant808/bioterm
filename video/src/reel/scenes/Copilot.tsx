import React from 'react';
import {C, F} from '../../config/theme';
import {E, H, S, W, k, lerp} from '../core';

// 26-31 s: the Copilot. A question types, the answer streams word by word, each
// citation chip fires a curve to its source card.
const A = S.copilot;
const Q = 'Which names have a PDUFA date in the next 30 days and under four quarters of cash?';
const ANSWER: {w: string; cite?: number}[] = [
  ...'Three names match the screen'.split(' ').map((w) => ({w})), {w: '[1]', cite: 0},
  ...'— two filed 424B5 prospectus supplements this month'.split(' ').map((w) => ({w})), {w: '[2]', cite: 1},
  ...'and one has an FDA advisory committee on the calendar'.split(' ').map((w) => ({w})), {w: '[3]', cite: 2},
];
const SOURCES = [
  {tag: 'SCREENER', title: 'Binary event ahead · runway < 4 q', meta: '38 fields · 660 names'},
  {tag: 'SEC EDGAR', title: 'Form 424B5 · prospectus supplement', meta: 'live filings feed'},
  {tag: 'FEDERAL REGISTER', title: 'FDA Advisory Committee notice', meta: 'meeting date · agenda'},
];

export const Copilot: React.FC<{t: number}> = ({t}) => {
  if (t < A - 0.05 || t > S.numbers + 0.05) return null;
  const lt = t - A;
  const enterX = lerp(W * 1.2, 0, k(lt, 0, 0.45, E.out));
  const fold = k(lt, 4.5, 5.0, E.in);
  const qn = Math.floor(Q.length * k(lt, 0.35, 1.25, (x) => x));
  const words = Math.floor(ANSWER.length * k(lt, 1.45, 3.4, (x) => x));
  const chipT = ANSWER.map((a, i) => (a.cite !== undefined ? 1.45 + ((i + 1) / ANSWER.length) * 1.95 : null));
  const L = {x: 150, y: 250, w: 900};
  const srcX = 1180;
  const srcY = (i: number) => 280 + i * 190;
  return (
    <div style={{position: 'absolute', inset: 0, transform: `translateX(${enterX}px) scaleY(${1 - fold * 0.96})`, opacity: 1 - k(lt, 4.8, 5.0)}}>
      <div style={{position: 'absolute', left: L.x, top: 140, fontFamily: F.mono, fontSize: 20, letterSpacing: 8, color: C.muted}}>
        COPILOT <span style={{color: C.border}}>—</span> <span style={{color: C.text2}}>ANSWERS WITH SOURCES</span>
      </div>
      {/* question */}
      <div style={{position: 'absolute', left: L.x + 160, top: L.y, width: L.w - 160, padding: '22px 28px', borderRadius: 20, background: C.primary,
        fontFamily: F.sans, fontSize: 30, lineHeight: 1.35, color: '#FFFFFF', opacity: k(lt, 0.2, 0.4), boxShadow: `0 20px 60px ${C.primary}44`}}>
        {Q.slice(0, qn)}<span style={{opacity: qn < Q.length ? 1 : 0}}>▍</span>
      </div>
      {/* answer */}
      <div style={{position: 'absolute', left: L.x, top: L.y + 200, width: L.w, padding: '26px 30px', borderRadius: 20, background: C.surface,
        border: `1px solid ${C.border}`, opacity: k(lt, 1.3, 1.5), fontFamily: F.sans, fontSize: 32, lineHeight: 1.5, color: C.text}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 12, fontFamily: F.mono, fontSize: 14, letterSpacing: 3, color: C.accent, marginBottom: 10}}>
          <span style={{width: 10, height: 10, borderRadius: 5, background: C.accent, boxShadow: `0 0 12px ${C.accent}`, opacity: lt < 3.4 && Math.floor(lt * 5) % 2 ? 0.3 : 1}} />
          {lt < 3.4 ? 'READING FILINGS · SCREENING · CITING' : '3 SOURCES'}
        </div>
        {ANSWER.slice(0, words).map((a, i) => {
          const p = k(lt, 1.45 + (i / ANSWER.length) * 1.95, 1.6 + (i / ANSWER.length) * 1.95);
          return a.cite !== undefined ? (
            <span key={i} id={`chip-${a.cite}`} style={{display: 'inline-block', margin: '0 6px', padding: '0 10px', borderRadius: 8, background: `${C.accent}33`,
              color: C.accentSoft, fontFamily: F.mono, fontSize: 24, transform: `scale(${lerp(1.6, 1, p)})`}}>{a.w}</span>
          ) : (
            <span key={i} style={{opacity: p, marginRight: 9, display: 'inline-block', transform: `translateY(${(1 - p) * 10}px)`}}>{a.w}</span>
          );
        })}
      </div>
      {/* connectors */}
      <svg width={W} height={H} style={{position: 'absolute', overflow: 'visible'}}>
        {SOURCES.map((_, i) => {
          const at = chipT.filter((x) => x !== null)[i] as number;
          const p = k(lt, at, at + 0.45, E.inOut);
          const x0 = L.x + L.w;
          const y0 = L.y + 330 + i * 30;
          const x1 = srcX;
          const y1 = srcY(i) + 60;
          return (
            <g key={i}>
              <path d={`M${x0} ${y0} C ${x0 + 90} ${y0}, ${x1 - 90} ${y1}, ${x1} ${y1}`} fill="none" stroke={C.accent} strokeWidth={2.5}
                pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - p} filter="url(#glow)" />
              {p > 0 && p < 1 && (
                <circle cx={lerp(x0, x1, p)} cy={lerp(y0, y1, E.inOut(p))} r={6} fill="#FFFFFF" filter="url(#glow)" />
              )}
            </g>
          );
        })}
      </svg>
      {/* source cards */}
      {SOURCES.map((s, i) => {
        const at = chipT.filter((x) => x !== null)[i] as number;
        const p = k(lt, at + 0.3, at + 0.75, E.overshoot);
        return (
          <div key={i} style={{position: 'absolute', left: srcX, top: srcY(i), width: 600, height: 150, borderRadius: 16, background: C.surface,
            border: `1px solid ${p > 0.9 ? C.borderStrong : C.border}`, padding: '20px 26px', opacity: p, transform: `translateX(${(1 - p) * 120}px) scale(${lerp(0.9, 1, p)})`,
            boxShadow: '0 30px 80px rgba(0,0,0,0.5)'}}>
            <div style={{fontFamily: F.mono, fontSize: 15, letterSpacing: 4, color: C.accent}}>[{i + 1}] {s.tag}</div>
            <div style={{fontFamily: F.sans, fontSize: 28, fontWeight: 600, color: C.text, marginTop: 12}}>{s.title}</div>
            <div style={{fontFamily: F.mono, fontSize: 15, letterSpacing: 2, color: C.faint, marginTop: 10}}>{s.meta}</div>
          </div>
        );
      })}
    </div>
  );
};
