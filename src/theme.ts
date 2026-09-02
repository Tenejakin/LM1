export const colors = {
  background: '#080B0D',
  surface: '#101417',
  surfaceRaised: '#171C1F',
  surfaceSoft: '#20262A',
  line: '#283034',
  lineStrong: '#394247',
  text: '#F4F7F2',
  textMuted: '#98A29D',
  textDim: '#69736E',
  accent: '#C7F36B',
  accentStrong: '#AEE640',
  accentInk: '#172006',
  cyan: '#6FE7E3',
  orange: '#FFB86A',
  red: '#FF7C75',
  white: '#FFFFFF',
  black: '#000000',
} as const;

export const spacing = {
  xs: 6,
  sm: 10,
  md: 16,
  lg: 22,
  xl: 28,
  xxl: 36,
} as const;

export const radii = {
  sm: 10,
  md: 16,
  lg: 22,
  xl: 30,
  pill: 999,
} as const;

export const shadows = {
  card: {
    shadowColor: colors.black,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.2,
    shadowRadius: 18,
    elevation: 5,
  },
};
