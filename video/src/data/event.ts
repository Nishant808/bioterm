import {MRNA_DAILY} from './mrna.generated';

// The market event the film opens on. Verified - see research/RESEARCH.md.
//   Aug 19 2026: Moderna + Merck report positive Phase 3 INTerpath-001 topline
//   (intismeran autogene + KEYTRUDA, resected stage IIB-IV melanoma; RFS primary
//   endpoint and DMFS key secondary met). MRNA closed $174.38 vs $62.96 prior
//   close: +176.97%, its largest one-day gain on record.
export const EVENT = {
  ticker: 'MRNA',
  name: 'Moderna, Inc.',
  exchange: 'NASDAQ',
  date: '2026-08-19',
  dateLabel: 'AUG 19 2026',
  prevClose: 62.96,
  open: 116.02,
  high: 176.66,
  low: 114.46,
  close: 174.38,
  changePct: 176.97,
  volume: 199_252_300,
} as const;

// Opening chart window: a calm month, then the event day.
export const OPENING_WINDOW = MRNA_DAILY.filter((b) => b.date >= '2026-07-13' && b.date <= '2026-08-19');

// The 1Y window BioTerm's Stock detail shows (live app, Sep 24 2026).
export const ONE_YEAR = MRNA_DAILY;
