// The information graph under the price move. Scene 03 shows only node TYPES;
// scene 04 decodes the primary nodes into the real, publicly reported entities
// behind the Aug 19 2026 move (Merck/Moderna press release, ClinicalTrials.gov).
// Outer nodes are BioTerm's actual data sources and generic biology context -
// labelled as context, never drawn as causal claims.

export type Group = 'company' | 'biology' | 'science';
export type Shape = 'core' | 'dot' | 'chip' | 'ring' | 'square' | 'doc';

export type PrimaryNode = {
  id: string;
  type: string; // scene 03 label
  name: string; // scene 04 label
  tag: string; // tertiary metadata
  group: Group;
  shape: Shape;
  angle: number; // degrees, 0 = right, clockwise
  r: number; // radius factor (1 = ellipse)
};

export const CENTER = {id: 'mrna', type: 'COMPANY', name: 'MRNA', tag: 'MODERNA · NASDAQ'};

export const PRIMARY: PrimaryNode[] = [
  {id: 'program', type: 'PROGRAM', name: 'intismeran autogene', tag: 'mRNA-4157 · V940', group: 'company', shape: 'dot', angle: -10, r: 0.62},
  {id: 'partner', type: 'PARTNER', name: 'MRK · KEYTRUDA', tag: 'pembrolizumab · anti-PD-1', group: 'company', shape: 'dot', angle: 188, r: 0.6},
  {id: 'trial', type: 'TRIAL', name: 'INTerpath-001', tag: 'NCT05933577 · PHASE 3', group: 'science', shape: 'square', angle: 30, r: 0.9},
  {id: 'disease', type: 'DISEASE', name: 'Melanoma', tag: 'resected stage IIB–IV', group: 'biology', shape: 'ring', angle: 110, r: 0.74},
  {id: 'target', type: 'TARGET', name: 'PD-1', tag: 'PDCD1 · immune checkpoint', group: 'biology', shape: 'chip', angle: 150, r: 0.92},
  {id: 'modality', type: 'MODALITY', name: 'Neoantigen therapy', tag: 'individualized · mRNA', group: 'biology', shape: 'ring', angle: -38, r: 0.8},
  {id: 'endpoint', type: 'DATA', name: 'RFS · DMFS', tag: 'primary · key secondary', group: 'science', shape: 'square', angle: 70, r: 0.86},
  {id: 'paper', type: 'PAPER', name: 'KEYNOTE-942', tag: 'mRNA-4157-P201 · PHASE 2b', group: 'science', shape: 'doc', angle: -68, r: 0.84},
  {id: 'cell', type: 'SCIENCE', name: 'CD8⁺ T cells', tag: 'anti-tumor response', group: 'biology', shape: 'ring', angle: 256, r: 0.8},
  {id: 'catalyst', type: 'CATALYST', name: 'ESMO 2026', tag: 'OCT 24 · LATE-BREAKING', group: 'science', shape: 'square', angle: 222, r: 0.95},
];

// Primary-to-primary links that are publicly documented.
export const CROSS: [string, string][] = [
  ['program', 'trial'],
  ['partner', 'trial'],
  ['trial', 'disease'],
  ['trial', 'endpoint'],
  ['partner', 'target'],
  ['program', 'modality'],
  ['modality', 'cell'],
  ['paper', 'program'],
  ['catalyst', 'trial'],
];

// Outer ring: data sources BioTerm ingests + generic biology vocabulary.
export const OUTER_LABELS: {text: string; group: Group; near: string}[] = [
  {text: 'ClinicalTrials.gov', group: 'science', near: 'trial'},
  {text: 'SEC EDGAR · 8-K', group: 'company', near: 'program'},
  {text: 'RSS · 175 headlines', group: 'company', near: 'partner'},
  {text: 'openFDA', group: 'science', near: 'endpoint'},
  {text: 'Form 4', group: 'company', near: 'partner'},
  {text: 'PDCD1', group: 'biology', near: 'target'},
  {text: 'CD274', group: 'biology', near: 'target'},
  {text: 'HLA-A', group: 'biology', near: 'cell'},
  {text: 'B2M', group: 'biology', near: 'modality'},
  {text: 'CD8A', group: 'biology', near: 'cell'},
  {text: 'ESMO abstract', group: 'science', near: 'catalyst'},
  {text: 'ASCO 2026 · 5-yr', group: 'science', near: 'paper'},
];
export const OUTER_COUNT = 30; // labelled + unlabelled context nodes
