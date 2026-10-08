/**
 * Mission-control look: true-black canvas, hairline borders, flat surfaces, one cool
 * signal colour. Colour is reserved for state; everything else stays grey.
 */
export const colors = {
  background: '#000000',
  surface: '#0A0C0E',
  surfaceRaised: '#111417',
  surfaceSoft: '#1A1E22',
  line: '#1E2328',
  lineStrong: '#343B42',
  text: '#F5F7F8',
  textMuted: '#8C949B',
  textDim: '#5D656C',
  accent: '#5BC0FF',
  accentStrong: '#3AA8EE',
  accentInk: '#00131F',
  accentWash: 'rgba(91, 192, 255, 0.09)',
  accentLine: 'rgba(91, 192, 255, 0.34)',
  cyan: '#7AE7D9',
  green: '#3DDC97',
  orange: '#FFB86A',
  red: '#FF6B66',
  dangerWash: 'rgba(255, 107, 102, 0.09)',
  dangerLine: 'rgba(255, 107, 102, 0.34)',
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
  sm: 4,
  md: 6,
  lg: 8,
  xl: 12,
  pill: 999,
} as const;

/** Monospace for telemetry labels and units. */
export const fonts = {
  mono: 'SpaceMono_400Regular',
} as const;

/** Flat design: depth comes from hairlines, not shadows. */
export const shadows = {
  card: {
    shadowColor: colors.black,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0,
    shadowRadius: 0,
    elevation: 0,
  },
};
