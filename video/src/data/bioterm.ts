// Content of the live BioTerm app (https://bioterm.streamlit.app), captured
// Sep 24 2026 15:50 UTC. Screenshots in research/. Nothing here is invented:
// every label, number and headline appears in the app.

export const NAV = ['Overview', 'Focus list', 'Stock detail', 'Catalysts', 'News', 'Watchlist', 'Compare', 'Alerts', 'Paper trading'] as const;
export const UPDATED = 'Updated Sep 24 · 15:50 UTC';
export const FOOTER_NOTE = 'Monitoring and screening only — not investment advice.';
export const SOURCES = 'Data: yfinance · SEC EDGAR · ClinicalTrials.gov · openFDA · RSS';

export const OVERVIEW = {
  title: 'Overview',
  subtitle: 'Biotech & pharma catalyst monitor · 6-month swing horizon',
  kpis: [
    {label: 'Catalysts · next 30 days', value: '54', chip: '474 within 6 months', spark: 'bars'},
    {label: 'High-signal news · 7 days', value: '241', chip: '↑ 47', chipNote: 'vs prior week', spark: 'bars2'},
    {label: 'Sector sentiment · 14 days', value: 'Positive +0.22', chip: '↓ -0.03', chipNote: 'tone vs prior 14 days', spark: 'area', neg: true},
    {label: 'Watchlist in top 20', value: '1 of 5', chip: '161 names tracked'},
  ],
  focus: [
    ['1', 'BIIB', 'Biogen Inc', 0.771, '–', '+0.67', ['Catalyst', 'Momentum', 'News flow']],
    ['2', 'VRTX', 'Vertex Pharmaceuticals Inc', 0.766, '▲ 1', '+0.69', ['Catalyst', 'News flow', 'Your conviction']],
    ['3', 'EXEL', 'Exelixis Inc', 0.748, '▼ 1', '+0.44', ['Catalyst', 'News flow']],
    ['4', 'PFE', 'Pfizer', 0.724, '▲ 3', '+0.42', ['Catalyst', 'News flow', 'Insider buying']],
    ['5', 'ALKS', 'Alkermes Plc', 0.708, '–', '+0.66', ['Catalyst', 'News flow']],
    ['6', 'INCY', 'Incyte Corp', 0.702, '▲ 2', '+0.27', ['Catalyst', 'News flow']],
    ['7', 'TAK', 'Takeda', 0.698, '▼ 3', '+0.67', ['Catalyst', 'News flow']],
    ['8', 'TGTX', 'TG Therapeutics Inc', 0.662, '▼ 2', '+0.15', ['Catalyst']],
    ['9', 'SRRK', 'Scholar Rock Holding Corp', 0.662, '▲ 1', '+0.71', ['Catalyst', 'News flow']],
    ['10', 'CADL', 'Candel Therapeutics Inc', 0.639, '▼ 1', '-0.02', ['Catalyst']],
  ] as [string, string, string, number, string, string, string[]][],
};

// Focus list (Stocks in focus) leaderboard columns + rows.
export const FOCUS_LIST = {
  title: 'Stocks in focus',
  subtitle: 'Ranked by how much attention a name deserves · Focus = conviction × insider × (momentum + catalyst + news flow) − risk',
  search: 'Search ticker or company',
  cols: ['#', 'Ticker', 'Company', 'Focus', 'Δ rank', 'News', 'Momentum', 'Catalyst', 'News flow', 'Risk', 'Conviction'],
  rows: [
    ['1', 'BIIB', 'Biogen Inc', 0.771, '0', '+0.67', '0.70', '0.71', '0.92', '0.00', '1.0×'],
    ['2', 'VRTX', 'Vertex Pharmaceuticals Inc', 0.766, '1', '+0.69', '0.51', '0.55', '0.88', '0.00', '1.2×'],
    ['3', 'EXEL', 'Exelixis Inc', 0.748, '-1', '+0.44', '0.56', '0.79', '0.87', '0.00', '1.0×'],
    ['4', 'PFE', 'Pfizer', 0.724, '3', '+0.42', '0.56', '0.53', '0.84', '0.00', '1.0×'],
    ['5', 'ALKS', 'Alkermes Plc', 0.708, '0', '+0.66', '0.31', '0.85', '0.92', '0.00', '1.0×'],
    ['6', 'INCY', 'Incyte Corp', 0.702, '2', '+0.27', '0.57', '0.75', '0.76', '0.00', '1.0×'],
    ['7', 'TAK', 'Takeda', 0.698, '-3', '+0.67', '0.55', '0.65', '0.91', '0.00', '1.0×'],
  ] as [string, string, string, number, ...string[]][],
  mrna: ['60', 'MRNA', 'Moderna Inc', 0.477, '6', '+0.53', '0.79', '0.13', '0.89', '0.33', '1.0×'] as [string, string, string, number, ...string[]],
};

export const STOCK = {
  title: 'Stock detail',
  subtitle: 'Price, pipeline, catalysts, news, insiders and filings for one name',
  select: 'MRNA · Moderna Inc',
  ticker: 'MRNA',
  name: 'Moderna Inc',
  badges: [
    {text: 'On watchlist · conviction 3', tone: 'blue'},
    {text: 'XBI member', tone: 'gray'},
    {text: 'Short cash runway', tone: 'red'},
  ],
  kpis: [
    {label: 'Focus Score', value: '0.477', chip: 'Rank #60'},
    {label: 'Market cap', value: '$74.82B'},
    {label: 'Cash', value: '$1.72B'},
    {label: 'Burn / year', value: '$3.88B'},
    {label: 'Cash runway', value: '1.8 quarters'},
    {label: 'News · 14 days', value: 'Bullish +0.53', chip: '175 headlines'},
  ],
  thesis: 'mRNA platform beyond COVID - RSV, flu combo, oncology (INT/mRNA-4157 with MRK)',
  tracking: ['mRNA-1010 (flu)', 'mRNA-1345 (RSV)', 'mRNA-4157/V940 (melanoma)'],
  tabs: ['Price & technicals', 'Pipeline', 'Catalysts', 'News & sentiment', 'Insiders', 'SEC filings'],
  news: {
    kpis: [
      {label: 'Signal · 14 days', value: '+0.53', chip: 'Bullish', pos: true},
      {label: 'Headlines · 14 days', value: '175'},
      {label: 'Event tilt', value: '+5.0', chip: '5 positive · 0 negative'},
    ],
    headlines: [
      {title: 'Moderna Announces Late-Breaking Data to be Presented at ESMO Congress 2026', meta: 'Sep 21 · 16:43 · Investing News Network'},
      {title: 'Moderna stock jumps as ESMO cancer data and FDA vaccine approvals fuel rally', meta: 'Sep 21 · 20:02 · AD HOC NEWS', event: 'Positive event', tags: ['approval']},
      {title: 'How the Merck-Moderna mRNA melanoma vaccine is built per patient', meta: 'Sep 22 · 13:13 · qz.com'},
      {title: 'Moderna Eyes Cancer Vaccine Filing as It Expands Beyond COVID', meta: 'Sep 23 · 15:02 · Yahoo Finance'},
      {title: 'Moderna’s mRNA flu shot hits the target', meta: 'Sep 23 · 11:00 · Science News'},
    ],
  },
  tech: [
    {label: 'Return 1 month', value: '+16.7%', chip: '3M +210.1% · 6M +246.1%'},
    {label: 'RSI (14)', value: '73', chip: 'Overbought'},
    {label: 'Position in 52-week range', value: '100%'},
  ],
};
