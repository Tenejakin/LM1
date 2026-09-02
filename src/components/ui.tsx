import Ionicons from '@expo/vector-icons/Ionicons';
import React, { PropsWithChildren } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleProp,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from 'react-native';

import { colors, radii, shadows, spacing } from '@/theme';
import { DeviceState } from '@/types';

export function Surface({
  children,
  style,
}: PropsWithChildren<{ style?: StyleProp<ViewStyle> }>) {
  return <View style={[styles.surface, style]}>{children}</View>;
}

export function Eyebrow({ children }: PropsWithChildren) {
  return <Text style={styles.eyebrow}>{children}</Text>;
}

export function SectionHeader({
  title,
  action,
  onAction,
}: {
  title: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {action ? (
        <Pressable
          accessibilityRole="button"
          onPress={onAction}
          hitSlop={10}
          style={({ pressed }) => pressed && styles.pressed}
        >
          <Text style={styles.sectionAction}>{action}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function PrimaryButton({
  label,
  icon,
  onPress,
  disabled = false,
  loading = false,
  variant = 'accent',
}: {
  label: string;
  icon?: keyof typeof Ionicons.glyphMap;
  onPress: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: 'accent' | 'dark' | 'outline' | 'danger';
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled, busy: loading }}
      disabled={disabled || loading}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        styles[`button_${variant}`],
        (disabled || loading) && styles.buttonDisabled,
        pressed && styles.buttonPressed,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={variant === 'accent' ? colors.accentInk : colors.text} />
      ) : icon ? (
        <Ionicons
          name={icon}
          color={variant === 'accent' ? colors.accentInk : colors.text}
          size={19}
        />
      ) : null}
      <Text style={[styles.buttonText, variant === 'accent' && styles.buttonTextAccent]}>
        {label}
      </Text>
    </Pressable>
  );
}

const stateMeta: Record<DeviceState, { label: string; color: string }> = {
  offline: { label: 'Offline', color: colors.textDim },
  connecting: { label: 'Connecting', color: colors.orange },
  ready: { label: 'Ready', color: colors.accent },
  armed: { label: 'Armed', color: colors.cyan },
  processing: { label: 'Analyzing', color: colors.orange },
  error: { label: 'Needs attention', color: colors.red },
};

export function StatusBadge({ state, demo = false }: { state: DeviceState; demo?: boolean }) {
  const meta = stateMeta[state];
  return (
    <View
      accessibilityLabel={`Device status: ${meta.label}${demo ? ', demo mode' : ''}`}
      style={styles.badge}
    >
      <View style={[styles.badgeDot, { backgroundColor: meta.color }]} />
      <Text style={styles.badgeText}>{demo ? 'Demo · ' : ''}{meta.label}</Text>
    </View>
  );
}

export function MetricTile({
  label,
  value,
  unit,
  accent = false,
}: {
  label: string;
  value: string;
  unit?: string;
  accent?: boolean;
}) {
  return (
    <View style={styles.metricTile}>
      <Text style={styles.metricLabel}>{label}</Text>
      <View style={styles.metricValueRow}>
        <Text style={[styles.metricValue, accent && styles.metricValueAccent]}>{value}</Text>
        {unit ? <Text style={styles.metricUnit}>{unit}</Text> : null}
      </View>
    </View>
  );
}

export function IconButton({
  icon,
  label,
  onPress,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={8}
      style={({ pressed }) => [styles.iconButton, pressed && styles.buttonPressed]}
    >
      <Ionicons name={icon} size={21} color={colors.text} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  surface: {
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: radii.lg,
    ...shadows.card,
  },
  eyebrow: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: 20,
    fontWeight: '700',
    letterSpacing: -0.4,
  },
  sectionAction: {
    color: colors.accent,
    fontSize: 13,
    fontWeight: '700',
  },
  pressed: { opacity: 0.7 },
  button: {
    minHeight: 54,
    borderRadius: radii.md,
    paddingHorizontal: spacing.lg,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
  },
  button_accent: { backgroundColor: colors.accent },
  button_dark: { backgroundColor: colors.surfaceSoft },
  button_outline: { borderWidth: 1, borderColor: colors.lineStrong },
  button_danger: { backgroundColor: '#2A1718', borderWidth: 1, borderColor: '#583030' },
  buttonDisabled: { opacity: 0.45 },
  buttonPressed: { transform: [{ scale: 0.98 }], opacity: 0.86 },
  buttonText: { color: colors.text, fontSize: 15, fontWeight: '800' },
  buttonTextAccent: { color: colors.accentInk },
  badge: {
    alignItems: 'center',
    backgroundColor: colors.surfaceRaised,
    borderColor: colors.line,
    borderRadius: radii.pill,
    borderWidth: 1,
    flexDirection: 'row',
    gap: 7,
    paddingHorizontal: 11,
    paddingVertical: 7,
  },
  badgeDot: { width: 7, height: 7, borderRadius: 4 },
  badgeText: { color: colors.text, fontSize: 12, fontWeight: '700' },
  metricTile: {
    flex: 1,
    minWidth: 88,
    padding: spacing.md,
    borderRadius: radii.md,
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.line,
  },
  metricLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.9,
    textTransform: 'uppercase',
    marginBottom: spacing.xs,
  },
  metricValueRow: { flexDirection: 'row', alignItems: 'baseline', gap: 4 },
  metricValue: { color: colors.text, fontSize: 25, fontWeight: '700', letterSpacing: -1 },
  metricValueAccent: { color: colors.accent },
  metricUnit: { color: colors.textMuted, fontSize: 11, fontWeight: '700' },
  iconButton: {
    alignItems: 'center',
    backgroundColor: colors.surfaceRaised,
    borderColor: colors.line,
    borderRadius: 20,
    borderWidth: 1,
    height: 40,
    justifyContent: 'center',
    width: 40,
  },
});
