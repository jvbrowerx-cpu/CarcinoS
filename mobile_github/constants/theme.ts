export const colors = {
  bg: '#060609',
  black: '#000000',
  dark: '#080808',
  cardBg: '#0d0d10',
  white: '#ffffff',
  body: '#b0b0bc',
  grey: 'rgba(255,255,255,0.55)',
  greyDim: 'rgba(255,255,255,0.35)',
  border: 'rgba(255,255,255,0.10)',
  borderDim: 'rgba(255,255,255,0.08)',
  green: '#6ab87a',
  greenMuted: '#7a8e7a',
  greenDim: 'rgba(106,184,122,0.14)',
  greenBorder: 'rgba(106,184,122,0.35)',
  approved: '#4caf7d',
  rejected: '#e05c5c',
  pending: '#f0a843',
};

export type TierCode = 'PI' | 'INC' | 'HOR';

export const tiers: Record<TierCode, { label: string; shortLabel: string; bg: string; text: string; dimBg: string; dimBorder: string }> = {
  PI: {
    label: 'Practice Impacting',
    shortLabel: 'PRACTICE IMPACTING',
    bg: '#7a8e7a',
    text: '#ffffff',
    dimBg: 'rgba(122,142,122,0.14)',
    dimBorder: 'rgba(122,142,122,0.4)',
  },
  INC: {
    label: 'Incremental',
    shortLabel: 'INCREMENTAL',
    bg: '#e4e4e4',
    text: '#222222',
    dimBg: 'rgba(255,255,255,0.06)',
    dimBorder: 'rgba(255,255,255,0.14)',
  },
  HOR: {
    label: 'Horizon',
    shortLabel: 'HORIZON',
    bg: '#d0d0d0',
    text: '#333333',
    dimBg: 'rgba(255,255,255,0.03)',
    dimBorder: 'rgba(255,255,255,0.10)',
  },
};
