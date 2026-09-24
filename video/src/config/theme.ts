// Visual system. Product tokens mirror BioTerm's .streamlit/config.toml + dashboard/_ui.py
// so the reveal matches the live app; the film adds only a deeper "void" plane.
export const C = {
  void: '#05070A', // film background, one step below the product plane
  bg: '#0B0E14', // BioTerm page plane
  surface: '#121821',
  surface2: '#19212D',
  border: '#232C3A',
  borderStrong: '#334055',
  grid: '#1A2230',
  text: '#E6EAF2',
  text2: '#B4BCCB',
  muted: '#8A94A6',
  faint: '#6B7485',
  primary: '#3D84FA',
  accent: '#5B9DFF', // single accent: links, highlights, pulses
  accentSoft: '#9DBEFF', // the "Term" in the BioTerm wordmark
  pos: '#3FB96B',
  neg: '#E5484D',
  warn: '#E0A33E', // dated catalysts only
  violet: '#9085E9',
  sma200: '#C9D1DD',
} as const;

export const F = {
  sans: "'Inter', system-ui, sans-serif",
  mono: "'JetBrains Mono', ui-monospace, monospace",
} as const;

// Type scale in px at 1080p-short-side; multiply by layout.u.
export const TYPE = {
  hero: 132, // BIOTERM wordmark
  display: 92, // kinetic statements
  title: 56,
  secondary: 26,
  label: 15, // terminal labels (mono, tracked)
  meta: 13, // tertiary metadata
} as const;
