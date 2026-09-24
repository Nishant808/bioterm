import React from 'react';
import {C, F} from '../../config/theme';
import {FOCUS_LIST, NAV, OVERVIEW, STOCK, UPDATED} from '../../data/bioterm';
import {E, prog, rng} from '../../lib/anim';
import {typed} from '../KineticText';
import {LogoMark} from '../Logo';
import {CandleChart} from './CandleChart';
import {Card, Chip, enter, Icon, Metric, mono, PageHeader} from './ui';

const NAV_ICONS = ['grid', 'bars', 'trend', 'cal', 'news', 'bookmark', 'compare', 'bell', 'wallet'];
// x of each nav tab in the live app at 1920px
export const NAV_X = [56, 151, 246, 354, 448, 520, 613, 706, 780];
const NAV_W = [91, 90, 103, 89, 67, 88, 88, 69, 106];

export const NavBar: React.FC<{active: number; p: number; hl: number}> = ({active, p, hl}) => (
  <div style={{position: 'absolute', left: 0, top: 0, width: 1920, height: 52, ...enter(p, 6)}}>
    <div style={{position: 'absolute', left: 14, top: 12}}>
      <LogoMark size={28} id="nav" />
    </div>
    {/* active pill glides between tabs */}
    <div style={{position: 'absolute', top: 13, height: 26, borderRadius: 6, background: '#1E2632', left: NAV_X[Math.floor(hl)] + (NAV_X[Math.ceil(hl)] - NAV_X[Math.floor(hl)]) * (hl % 1), width: NAV_W[Math.floor(hl)] + (NAV_W[Math.ceil(hl)] - NAV_W[Math.floor(hl)]) * (hl % 1)}} />
    {NAV.map((n, i) => (
      <div key={n} style={{position: 'absolute', left: NAV_X[i] + 8, top: 17, display: 'flex', alignItems: 'center', gap: 7, fontSize: 13, fontWeight: i === active ? 600 : 400, color: i === active ? C.text : C.text2}}>
        <Icon kind={NAV_ICONS[i]} color={i === active ? C.text : C.text2} />
        {n}
      </div>
    ))}
  </div>
);

const spark = (seed: number, n: number) => {
  const r = rng(seed);
  return Array.from({length: n}, () => r());
};

// ------------------------------------------------------------------ Overview
export const OverviewPage: React.FC<{t: number; t0: number; hlRow?: number}> = ({t, t0}) => {
  const a = (o: number, d = 0.45) => E.out(prog(t, t0 + o, t0 + o + d));
  const kx = [305, 634, 962, 1291];
  const cols = {num: 390, ticker: 404, company: 511, bar: 747, moved: 935, news: 1135, why: 1149};
  return (
    <>
      <PageHeader title={OVERVIEW.title} subtitle={OVERVIEW.subtitle} p={a(0.05)} updated={UPDATED} />
      {OVERVIEW.kpis.map((k, i) => {
        const p = a(0.3 + i * 0.08);
        const bars = spark(11 + i, 26);
        return (
          <Card key={k.label} x={kx[i]} y={186} w={314} h={172} p={p}>
            <Metric
              label={k.label} value={k.value} help={i !== 3}
              chip={<Chip tone={k.neg ? 'red' : 'gray'}>{k.chip}</Chip>} note={k.chipNote}
            />
            {k.spark && (
              <svg width={300} height={50} style={{position: 'absolute', left: 7, bottom: 22}}>
                {k.spark === 'area' ? (
                  <path
                    d={`M0,${50 - bars[0] * 30} ${bars.map((b, j) => `L${(j * 300) / 25},${50 - 12 - b * 30 * prog(t, t0 + 0.5, t0 + 1.1)}`).join(' ')} L300,50 L0,50 Z`}
                    fill="rgba(229,72,77,0.18)" stroke={C.neg} strokeWidth={1.4}
                  />
                ) : (
                  bars.map((b, j) => {
                    const hh = (k.spark === 'bars' ? (b > 0.6 ? b : b * 0.25) : 0.25 + b * 0.75) * 40 * E.out(prog(t, t0 + 0.5 + j * 0.012, t0 + 1.0 + j * 0.012));
                    return <rect key={j} x={j * 11.5 + 4} y={48 - hh} width={4} height={hh} fill="#8A94A6" opacity={0.75} />;
                  })
                )}
              </svg>
            )}
          </Card>
        );
      })}
      <Card x={305} y={373} w={1300} h={453} p={a(0.55)}>
        <div style={{position: 'absolute', left: 14, top: 16, display: 'flex', alignItems: 'center', gap: 8, fontSize: 13.5, fontWeight: 600, color: C.text}}>
          <Icon kind="bars" /> Stocks in focus
        </div>
        <div style={{position: 'absolute', right: 14, top: 18, fontSize: 11.5, color: C.muted}}>Top 12 by Focus Score</div>
      </Card>
      <div style={{position: 'absolute', left: 319, top: 426, width: 1272, height: 31, background: C.surface, borderRadius: '6px 6px 0 0', border: `1px solid ${C.border}`, opacity: a(0.6), fontSize: 12.5, color: C.text2}}>
        {[['#', 12], ['Ticker', 85], ['Company', 192], ['Focus', 428], ['Moved', 616], ['News', 723], ['Why it ranks', 830]].map(([s, x]) => (
          <span key={s as string} style={{position: 'absolute', left: x as number, top: 7}}>{s}</span>
        ))}
      </div>
      {OVERVIEW.focus.map(([n, tk, co, f, mv, nw, why], i) => {
        const p = a(0.65 + i * 0.05, 0.35);
        const fill = E.out(prog(t, t0 + 0.85 + i * 0.05, t0 + 1.55 + i * 0.05));
        const y = 457 + i * 31;
        return (
          <div key={tk} style={{position: 'absolute', left: 319, top: y, width: 1272, height: 31, borderBottom: `1px solid ${C.border}`, fontSize: 12.5, color: C.text, ...enter(p, 6)}}>
            <span style={{position: 'absolute', left: cols.num - 319 - 10, top: 8, width: 10, textAlign: 'right'}}>{n}</span>
            <span style={{position: 'absolute', left: cols.ticker - 319, top: 8}}>{tk}</span>
            <span style={{position: 'absolute', left: cols.company - 319, top: 8}}>{co}</span>
            <span style={{position: 'absolute', left: cols.bar - 319, top: 12, width: 140, height: 5, borderRadius: 3, background: '#1F2733'}}>
              <span style={{position: 'absolute', left: 0, top: 0, height: 5, borderRadius: 3, width: 140 * (f / 0.78) * fill, background: C.primary}} />
            </span>
            <span style={{position: 'absolute', left: cols.bar - 319 + 147, top: 8, fontSize: 11.5, opacity: 0.3 + 0.7 * fill}}>{f.toFixed(3)}</span>
            <span style={{position: 'absolute', left: cols.moved - 319, top: 8}}>{mv}</span>
            <span style={{position: 'absolute', left: cols.news - 319 - 60, width: 60, textAlign: 'right', top: 8}}>{nw}</span>
            <span style={{position: 'absolute', left: cols.why - 319, top: 5, display: 'flex', gap: 5}}>
              {why.map((w) => (
                <Chip key={w} tone={w === 'Your conviction' ? 'blue' : w === 'Insider buying' ? 'green' : 'gray'}>{w}</Chip>
              ))}
            </span>
          </div>
        );
      })}
      <div style={{position: 'absolute', left: 330, top: 796, fontSize: 13, color: C.text, opacity: a(1.1), display: 'flex', gap: 8}}>→ Full leaderboard and score breakdown</div>
      <Card x={305} y={841} w={636} h={300} p={a(0.95)}>
        <div style={{position: 'absolute', left: 14, top: 16, display: 'flex', gap: 8, alignItems: 'center', fontSize: 13.5, fontWeight: 600}}>
          <Icon kind="bolt" /> High-signal headlines
        </div>
        <div style={{position: 'absolute', right: 14, top: 18, fontSize: 11.5, color: C.muted}}>Last 7 days</div>
        <div style={{position: 'absolute', left: 20, top: 60, fontSize: 13.5, color: C.text, width: 560, lineHeight: 1.35}}>
          <span style={{...mono, fontSize: 11, color: C.text2, marginRight: 30}}>NVS</span>Roche’s phase 3 win tees up fight with Novartis for blockbuster kidney disease market
        </div>
      </Card>
      <Card x={969} y={841} w={636} h={300} p={a(1.0)}>
        <div style={{position: 'absolute', left: 14, top: 16, display: 'flex', gap: 8, alignItems: 'center', fontSize: 13.5, fontWeight: 600}}>
          <Icon kind="cal" /> Next catalysts
        </div>
        <div style={{position: 'absolute', right: 14, top: 18, fontSize: 11.5, color: C.muted}}>Next 6 months</div>
        <div style={{position: 'absolute', left: 20, top: 62, fontSize: 13, color: C.text, display: 'flex', gap: 22}}>
          <span style={{fontWeight: 600}}>Sep 17</span>
          <span style={{...mono, fontSize: 11.5}}>VRTX</span>
          <Chip tone="blue">Phase 3 readout</Chip>
          <span style={{color: C.muted, fontSize: 12}}>ClinicalTrials.gov</span>
        </div>
      </Card>
    </>
  );
};

// ------------------------------------------------------------------ Focus list
const FCOLS = [12, 82, 184, 414, 594, 694, 794, 902, 996, 1100, 1175];

const FocusRow: React.FC<{row: (string | number)[]; y: number; style?: React.CSSProperties; fill?: number; hl?: number}> = ({row, y, style, fill = 1, hl = 0}) => (
  <div style={{position: 'absolute', left: 319, top: y, width: 1272, height: 31, borderBottom: `1px solid ${C.border}`, fontSize: 12.5, color: C.text, background: hl ? `rgba(61,132,250,${0.1 * hl})` : undefined, boxShadow: hl ? `inset 3px 0 0 rgba(91,157,255,${hl})` : undefined, ...style}}>
    {row.map((v, j) => {
      if (j === 3) {
        const f = v as number;
        return (
          <span key={j} style={{position: 'absolute', left: FCOLS[j], top: 12}}>
            <span style={{position: 'absolute', left: 0, top: 0, width: 132, height: 5, borderRadius: 3, background: '#1F2733'}} />
            <span style={{position: 'absolute', left: 0, top: 0, width: 132 * (f / 0.78) * fill, height: 5, borderRadius: 3, background: C.primary}} />
            <span style={{position: 'absolute', left: 139, top: -4, fontSize: 11.5}}>{f.toFixed(3)}</span>
          </span>
        );
      }
      const right = j === 0 || j >= 4;
      return (
        <span key={j} style={{position: 'absolute', top: 8, ...(right ? {left: FCOLS[j] + (j === 0 ? -40 : 0), width: j === 0 ? 50 : 90, textAlign: 'right'} : {left: FCOLS[j]})}}>
          {v}
        </span>
      );
    })}
  </div>
);

export const FocusListPage: React.FC<{t: number; t0: number; typeAt: number; filterAt: number}> = ({t, t0, typeAt, filterAt}) => {
  const a = (o: number, d = 0.25) => E.out(prog(t, t0 + o, t0 + o + d));
  const q = typed('MRNA', prog(t, typeAt, typeAt + 0.3));
  const f = E.inOut(prog(t, filterAt, filterAt + 0.25));
  const caret = Math.floor(t * 4) % 2 === 0 && t > typeAt - 0.2 ? 1 : 0;
  return (
    <>
      <PageHeader title={FOCUS_LIST.title} subtitle={FOCUS_LIST.subtitle} p={a(0)} updated={UPDATED} />
      <div style={{position: 'absolute', left: 305, top: 210, width: 300, height: 34, borderRadius: 8, border: `1px solid ${q ? C.primary : C.border}`, background: C.surface, display: 'flex', alignItems: 'center', gap: 10, paddingLeft: 12, fontSize: 13.5, color: q ? C.text : C.muted, ...enter(a(0.08))}}>
        <Icon kind="search" color={C.muted} />
        {q || FOCUS_LIST.search}
        {q && <span style={{width: 1.5, height: 16, background: C.text, opacity: caret, marginLeft: -8}} />}
      </div>
      <div style={{position: 'absolute', left: 620, top: 217, display: 'flex', gap: 6, ...enter(a(0.12))}}>
        {['Watchlist', 'XBI members'].map((c) => (
          <span key={c} style={{border: `1px solid ${C.border}`, borderRadius: 14, padding: '4px 10px', fontSize: 12.5, color: C.text}}>{c}</span>
        ))}
      </div>
      <div style={{position: 'absolute', left: 813, top: 190, fontSize: 12.5, color: C.text, ...enter(a(0.14))}}>
        Minimum catalyst score
        <div style={{color: C.accent, fontSize: 12, marginTop: 2}}>0.00</div>
        <div style={{position: 'absolute', left: 0, top: 36, width: 255, height: 3, background: '#2A3342', borderRadius: 2}} />
        <div style={{position: 'absolute', left: 0, top: 31, width: 12, height: 12, borderRadius: 6, background: C.primary}} />
      </div>
      <Card x={305} y={260} w={1300} h={420} p={a(0.18)}>
        <div style={{position: 'absolute', left: 14, top: 16, display: 'flex', gap: 8, alignItems: 'center', fontSize: 13.5, fontWeight: 600}}>
          <Icon kind="bars" /> Leaderboard
        </div>
        <div style={{position: 'absolute', right: 14, top: 18, fontSize: 11.5, color: C.muted}}>{f > 0.5 ? '1 of 161 names' : '161 of 161 names'}</div>
      </Card>
      <div style={{position: 'absolute', left: 319, top: 311, width: 1272, height: 31, background: C.surface, border: `1px solid ${C.border}`, borderRadius: '6px 6px 0 0', fontSize: 12.5, color: C.text2, opacity: a(0.22)}}>
        {FOCUS_LIST.cols.map((c, j) => (
          <span key={c} style={{position: 'absolute', top: 7, left: FCOLS[j]}}>{c}</span>
        ))}
      </div>
      {FOCUS_LIST.rows.map((r, i) => (
        <FocusRow key={r[1]} row={r} y={342 + i * 31} fill={E.out(prog(t, t0 + 0.3 + i * 0.04, t0 + 0.8 + i * 0.04))} style={{opacity: a(0.24 + i * 0.04, 0.3) * (1 - f), transform: `translateY(${f * -6}px)`}} />
      ))}
      <FocusRow row={FOCUS_LIST.mrna} y={342} fill={E.out(prog(t, filterAt + 0.1, filterAt + 0.6))} hl={E.out(prog(t, filterAt + 0.2, filterAt + 0.5))} style={{opacity: f, transform: `translateY(${(1 - f) * 8}px)`}} />
    </>
  );
};

// ------------------------------------------------------------------ Stock detail
export const StockDetailPage: React.FC<{t: number; t0: number; tab: 'price' | 'news'; tabAt: number; focusGlow: number; trackGlow: number}> = ({t, t0, tab, tabAt, focusGlow, trackGlow}) => {
  const a = (o: number, d = 0.35) => E.out(prog(t, t0 + o, t0 + o + d));
  const sel = typed(STOCK.select, prog(t, t0 + 0.05, t0 + 0.3));
  const tabIdx = tab === 'price' ? 0 : 3;
  const tabX = [305, 438, 513, 596, 730, 805];
  const tabW = [120, 62, 70, 120, 62, 80];
  const tp = E.out(prog(t, tabAt, tabAt + 0.3));
  return (
    <>
      <PageHeader title={STOCK.title} subtitle={STOCK.subtitle} p={a(0)} updated={UPDATED} />
      <div style={{position: 'absolute', left: 305, top: 186, width: 420, height: 34, border: `1px solid ${C.border}`, borderRadius: 8, background: C.surface, fontSize: 13, color: C.text, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 10px', boxSizing: 'border-box', ...enter(a(0.02))}}>
        {sel}
        <Icon kind="chev" color={C.text} />
      </div>
      <div style={{position: 'absolute', left: 305, top: 244, display: 'flex', alignItems: 'center', gap: 10, ...enter(a(0.14))}}>
        <span style={{...mono, fontSize: 23, fontWeight: 600, color: C.text}}>{STOCK.ticker}</span>
        <span style={{fontSize: 15, color: C.text2}}>{STOCK.name}</span>
        {STOCK.badges.map((b) => (
          <Chip key={b.text} tone={b.tone as 'blue' | 'gray' | 'red'} style={{fontSize: 11}}>{b.text}</Chip>
        ))}
      </div>
      {STOCK.kpis.map((k, i) => (
        <Card key={k.label} x={305 + i * 219} y={297} w={205} h={172} p={a(0.18 + i * 0.04)} style={i === 0 && focusGlow > 0 ? {borderColor: `rgba(91,157,255,${0.3 + 0.7 * focusGlow})`, boxShadow: `0 0 0 ${3 * focusGlow}px rgba(91,157,255,0.15)`} : undefined}>
          <Metric label={k.label} value={k.value} help={i === 0 || i === 4} chip={k.chip ? <Chip>{k.chip}</Chip> : undefined} />
          {i === 0 && (
            <svg width={203} height={40} style={{position: 'absolute', left: 0, bottom: 26}}>
              <path d="M0,36 L12,38 L26,34 L52,34 L54,24 L96,22 L110,22 L112,18 L150,20 L160,12 L178,10 L203,11 L203,40 L0,40 Z" fill="rgba(138,148,166,0.22)" stroke="#8A94A6" strokeWidth={1.2} />
            </svg>
          )}
        </Card>
      ))}
      {/* Your view */}
      <Card x={305} y={485} w={636} h={224} p={a(0.3)}>
        <div style={{position: 'absolute', left: 14, top: 16, display: 'flex', gap: 8, alignItems: 'center', fontSize: 13.5, fontWeight: 600}}>
          <Icon kind="psych" /> Your view
        </div>
        <div style={{position: 'absolute', right: 14, top: 18, fontSize: 11.5, color: C.muted}}>Conviction multiplies the Focus Score</div>
        <div style={{position: 'absolute', left: 14, top: 54, fontSize: 13, color: C.text}}>Conviction</div>
        <div style={{position: 'absolute', left: 14, top: 76, display: 'flex'}}>
          {[1, 2, 3, 4, 5].map((n) => (
            <span key={n} style={{width: 36, height: 26, border: `1px solid ${n === 3 ? C.primary : C.border}`, background: n === 3 ? 'rgba(61,132,250,0.18)' : undefined, color: n === 3 ? C.accent : C.text, fontSize: 12.5, display: 'flex', alignItems: 'center', justifyContent: 'center', marginLeft: -1}}>{n}</span>
          ))}
        </div>
        <div style={{position: 'absolute', left: 390, top: 69, padding: '8px 12px', borderRadius: 7, background: C.primary, color: '#fff', fontSize: 12.5}}>✓ Update conviction</div>
        <div style={{position: 'absolute', left: 14, top: 120, fontSize: 13, color: C.text}}>Thesis</div>
        <div style={{position: 'absolute', left: 14, top: 142, width: 606, height: 34, border: `1px solid ${C.border}`, borderRadius: 8, background: C.surface, fontSize: 13, color: C.text, display: 'flex', alignItems: 'center', paddingLeft: 11, boxSizing: 'border-box'}}>{STOCK.thesis}</div>
        <div style={{position: 'absolute', left: 14, top: 190, fontSize: 12.5, color: C.muted, display: 'flex', gap: 5}}>
          Tracking:
          {STOCK.tracking.map((m, i) => (
            <span key={m} style={{position: 'relative', color: i === 2 ? (trackGlow > 0.5 ? C.accentSoft : C.muted) : C.muted}}>
              {i === 2 && (
                <span style={{position: 'absolute', left: -4, right: -4, top: -3, bottom: -3, borderRadius: 4, border: `1px solid rgba(91,157,255,${trackGlow})`, background: `rgba(61,132,250,${0.14 * trackGlow})`}} />
              )}
              {m}
              {i < 2 ? ' ·' : ''}
            </span>
          ))}
        </div>
      </Card>
      <Card x={969} y={485} w={636} h={210} p={a(0.34)}>
        <div style={{position: 'absolute', left: 14, top: 16, display: 'flex', gap: 8, alignItems: 'center', fontSize: 13.5, fontWeight: 600}}>
          <Icon kind="note" /> Research notes
        </div>
        <div style={{position: 'absolute', right: 14, top: 18, fontSize: 11.5, color: C.muted}}>Private to you</div>
        <div style={{position: 'absolute', left: 14, top: 52, width: 606, height: 94, border: `1px solid ${C.border}`, borderRadius: 8, background: C.surface, fontSize: 13, color: C.muted, padding: '10px 11px', boxSizing: 'border-box'}}>Mechanism, trial design, competitive read...</div>
        <div style={{position: 'absolute', left: 14, top: 162, padding: '7px 11px', borderRadius: 7, border: `1px solid ${C.border}`, fontSize: 12.5}}>Save note</div>
      </Card>
      {/* tabs */}
      <div style={{position: 'absolute', left: 305, top: 730, width: 1300, height: 32, borderBottom: `1px solid ${C.border}`, opacity: a(0.36)}}>
        {STOCK.tabs.map((s, i) => (
          <span key={s} style={{position: 'absolute', left: tabX[i] - 305, top: 3, fontSize: 13, color: i === tabIdx ? C.accent : C.text}}>{s}</span>
        ))}
        <span style={{position: 'absolute', top: 29, height: 2, background: C.accent, left: (tab === 'price' ? tabX[0] : tabX[0] + (tabX[3] - tabX[0]) * tp) - 305, width: tab === 'price' ? tabW[0] : tabW[0] + (tabW[3] - tabW[0]) * tp}} />
      </div>
      {tab === 'price' ? (
        <div style={{opacity: a(0.38)}}>
          <div style={{position: 'absolute', left: 305, top: 773, display: 'flex'}}>
            {['6M', '1Y', '2Y'].map((w) => (
              <span key={w} style={{width: 44, height: 26, border: `1px solid ${w === '1Y' ? C.primary : C.border}`, color: w === '1Y' ? C.accent : C.text, background: w === '1Y' ? 'rgba(61,132,250,0.15)' : undefined, fontSize: 12.5, display: 'flex', alignItems: 'center', justifyContent: 'center', marginLeft: -1}}>{w}</span>
            ))}
          </div>
          <div style={{position: 'absolute', left: 372, top: 826, display: 'flex', gap: 16, fontSize: 11.5, color: C.text}}>
            {[['SMA 20', C.accent], ['SMA 50', C.violet], ['SMA 200', C.sma200], ['RSI 14', C.accent]].map(([n, c]) => (
              <span key={n} style={{display: 'flex', alignItems: 'center', gap: 6}}><span style={{width: 26, height: 2, background: c}} />{n}</span>
            ))}
            <span style={{display: 'flex', alignItems: 'center', gap: 6}}><span style={{color: C.warn}}>▼</span>Catalyst</span>
          </div>
          <CandleChart x={368} y={866} w={1229} reveal={E.soft(prog(t, t0 + 0.3, t0 + 0.85))} markerP={prog(t, t0 + 0.8, t0 + 1.0)} />
        </div>
      ) : (
        <div style={{opacity: tp}}>
          {STOCK.news.kpis.map((k, i) => (
            <Card key={k.label} x={305 + i * 437} y={780} w={423} h={110} p={E.out(prog(t, tabAt + 0.05 + i * 0.05, tabAt + 0.4 + i * 0.05))}>
              <Metric label={k.label} value={k.value} valueColor={k.pos ? C.text : C.text} chip={k.chip ? <Chip tone={k.pos ? 'green' : 'gray'}>{k.chip}</Chip> : undefined} />
            </Card>
          ))}
          {STOCK.news.headlines.map((hd, i) => (
            <div key={hd.title} style={{position: 'absolute', left: 305, top: 912 + i * 64, width: 1300, height: 58, borderBottom: `1px solid ${C.border}`, ...enter(E.out(prog(t, tabAt + 0.2 + i * 0.07, tabAt + 0.5 + i * 0.07)), 8)}}>
              <span style={{position: 'absolute', left: 14, top: 12, ...mono, fontSize: 11.5, color: C.text2}}>MRNA</span>
              <span style={{position: 'absolute', left: 97, top: 8, fontSize: 14, color: C.text}}>{hd.title}</span>
              <span style={{position: 'absolute', left: 97, top: 32, fontSize: 11.5, color: C.muted, display: 'flex', gap: 6, alignItems: 'center'}}>
                {hd.meta}
                {hd.event && <span style={{color: C.pos}}>· ● {hd.event}</span>}
                {hd.tags?.map((tg) => <Chip key={tg} tone="green" style={{fontSize: 11}}>{tg}</Chip>)}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
};

/** Score breakdown popover - values are MRNA's leaderboard row in the live app. */
export const ScoreBreakdown: React.FC<{t: number; t0: number}> = ({t, t0}) => {
  const p = E.out(prog(t, t0, t0 + 0.35));
  if (p <= 0) return null;
  const rows: [string, number, string][] = [
    ['Momentum', 0.79, C.primary],
    ['Catalyst', 0.13, C.primary],
    ['News flow', 0.89, C.primary],
    ['Risk', 0.33, C.neg],
  ];
  return (
    <Card x={530} y={306} w={470} h={300} p={p} style={{background: C.surface, borderColor: C.borderStrong, boxShadow: '0 24px 60px rgba(0,0,0,0.55)'}}>
      <div style={{position: 'absolute', left: 16, top: 16, fontSize: 13.5, fontWeight: 600, display: 'flex', gap: 8, alignItems: 'center'}}>
        <Icon kind="bars" /> Score breakdown
      </div>
      <div style={{position: 'absolute', right: 16, top: 18, fontSize: 11.5, color: C.muted}}>MRNA · Moderna Inc</div>
      {rows.map(([n, v, c], i) => {
        const f = E.out(prog(t, t0 + 0.15 + i * 0.07, t0 + 0.6 + i * 0.07));
        return (
          <div key={n} style={{position: 'absolute', left: 16, top: 56 + i * 36, width: 438, fontSize: 13, color: C.text2}}>
            {n}
            <span style={{position: 'absolute', left: 110, top: 7, width: 250, height: 6, borderRadius: 3, background: '#26303F'}} />
            <span style={{position: 'absolute', left: 110, top: 7, width: 250 * v * f, height: 6, borderRadius: 3, background: c}} />
            <span style={{position: 'absolute', right: 0, top: 0, ...mono, color: C.text, opacity: f}}>{v.toFixed(2)}</span>
          </div>
        );
      })}
      <div style={{position: 'absolute', left: 16, top: 206, width: 438, borderTop: `1px solid ${C.border}`}} />
      <div style={{position: 'absolute', left: 16, top: 218, fontSize: 11.5, color: C.muted}}>conviction 1.0× · insider 1.0×</div>
      <div style={{position: 'absolute', left: 16, top: 244, fontSize: 13, color: C.text2}}>Focus Score</div>
      <div style={{position: 'absolute', left: 16, top: 262, fontSize: 26, fontWeight: 600, color: C.text}}>0.477</div>
      <div style={{position: 'absolute', left: 120, top: 270}}><Chip tone="blue">Rank #60 of 161</Chip></div>
    </Card>
  );
};
