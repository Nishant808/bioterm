# Research record — BioTerm launch film

Captured 2026-09-24. Everything the film shows traces back to this file.

## 1. The market event (scene 01)

**Moderna (NASDAQ: MRNA), Wednesday 19 Aug 2026.**

| field | value | source |
|---|---|---|
| prior close (Aug 18) | $62.96 | Yahoo Finance daily history; StockAnalysis.com |
| open | $116.02 | same |
| high / low | $176.66 / $114.46 | same |
| close | $174.38 | same |
| change | **+176.97%** (+$111.42) | same; also Motley Fool, INDmoney ("largest one-day percentage gain on record") |
| volume | 199,252,300 | Yahoo (StockAnalysis: 199,252,328) |

Context (Merck/Moderna press release, 19 Aug 2026): positive topline results from the
Phase 3 **INTerpath-001** trial (ClinicalTrials.gov **NCT05933577**) of **intismeran autogene**
(V940 / mRNA-4157), an individualized neoantigen therapy, with KEYTRUDA (pembrolizumab,
anti-PD-1) vs KEYTRUDA alone in completely resected stage IIB–IV melanoma; 1,137 patients.
Met the primary endpoint (recurrence-free survival, RFS) and key secondary endpoint (distant
metastasis-free survival, DMFS). Builds on the Phase 2b KEYNOTE-942 / mRNA-4157-P201 study
(5-year data at ASCO 2026). Detailed Phase 3 data: ESMO 2026 Presidential Symposium, 24 Oct
2026 (Moderna release, 21 Sep 2026).

The opening chart plots the real daily closes and volumes from 13 Jul to 19 Aug 2026
(`src/data/mrna_daily.csv`, 251 sessions from 24 Sep 2025 to 23 Sep 2026). The film uses the move
only as a narrative hook. Nothing on screen says or implies that BioTerm predicted or caused it.

Sources: finance.yahoo.com/quote/MRNA/history · stockanalysis.com/stocks/mrna/history ·
merck.com news release (19 Aug 2026) · reuters.com (19 Aug 2026) · indmoney.com ·
marketwise.com · nasdaq.com press release (21 Sep 2026) · msdclinicaltrials.com (V940-001 → NCT05933577).

## 2. The product (scenes 05–08)

Live app: https://bioterm.streamlit.app, captured through Firecrawl (the session's network
policy blocks the host directly). Screenshots: `research/live_*.png`, `research/focus_*.png`.

- **Logo**: gradient rounded square (#4C8DFF → #6A5CF6) with a white double helix;
  wordmark "Bio" (700, #E6EAF2) + "Term" (500, #9DBEFF). Geometry copied from
  `dashboard/assets/mark.svg` / `logo.svg`.
- **Colours** (`.streamlit/config.toml`): bg #0B0E14, surface #121821, border #232C3A,
  text #E6EAF2, muted #8A94A6, primary #3D84FA, accent #5B9DFF, pos #3FB96B, neg #E5484D,
  warn #E0A33E, violet #9085E9.
- **Type**: Inter 400–700 (UI), JetBrains Mono (code/labels); 14px base, 26px h1,
  metric value 1.7rem/600, 8px radius.
- **Layout**: top navigation bar (Overview · Focus list · Stock detail · Catalysts · News ·
  Watchlist · Compare · Alerts · Paper trading), 1300px content column, page header + green
  "Updated Sep 24 · 15:50 UTC" chip, bordered metric cards, dataframes.
- **Screens used**: Overview (4 KPIs, Stocks in focus top 12, High-signal headlines, Next
  catalysts), Focus list (search, leaderboard with Focus/News/Momentum/Catalyst/News flow/
  Risk/Conviction), Stock detail for MRNA (6 KPIs, Your view + thesis/tracking, tabs
  Price & technicals / Pipeline / Catalysts / News & sentiment / Insiders / SEC filings).
- **Real MRNA values** shown: Focus Score 0.477, Rank #60, Market cap $74.82B, Cash $1.72B,
  Burn/year $3.88B, Cash runway 1.8 quarters, News 14 days Bullish +0.53 / 175 headlines,
  Event tilt +5.0; leaderboard momentum 0.79, catalyst 0.13, news flow 0.89, risk 0.33,
  conviction 1.0×; thesis "mRNA platform beyond COVID - RSV, flu combo, oncology
  (INT/mRNA-4157 with MRK)"; tracking "mRNA-1010 (flu) · mRNA-1345 (RSV) · mRNA-4157/V940
  (melanoma)"; five real headlines from the News & sentiment tab.
- **Terminology** used verbatim: Focus Score, Stocks in focus, Catalyst, News flow,
  High-signal headlines, Your view, Thesis, Tracking, Score breakdown,
  "Monitoring and screening only — not investment advice."

### Deliberate simplifications (not inventions)
- Nav icons are simple line glyphs standing in for the app's Material Symbols.
- KPI sparklines on the Overview cards are shape-accurate, not data-accurate.
- The Score breakdown popover shows MRNA's leaderboard sub-scores, not the app's weighted
  contribution chart. MRNA's weighted contributions were not captured.
- The Stock detail "Pipeline" tab reads "No trials found" for MRNA in the live app, so the
  film never shows a trials table inside BioTerm. The scientific entities appear only in
  the conceptual graph (scenes 03–04), labelled from the public press release.
