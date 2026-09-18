import Ionicons from '@expo/vector-icons/Ionicons';
import React, { PropsWithChildren, useState } from 'react';
import {
  ActivityIndicator,
  LayoutAnimation,
  Platform,
  Pressable,
  StyleProp,
  StyleSheet,
  Text,
  UIManager,
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

if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

/**
 * A section that stays folded away until it is needed. Everyday controls stay on
 * screen; setup and tuning live behind a tap so the screen is not a wall of options.
 */
export function CollapsibleSection({
  title,
  summary,
  icon,
  badge,
  defaultOpen = false,
  children,
}: PropsWithChildren<{
  title: string;
  summary?: string;
  icon?: keyof typeof Ionicons.glyphMap;
  /** Short status shown on the closed row, e.g. "Connected" or "Needs setup". */
  badge?: string;
  defaultOpen?: boolean;
}>) {
  const [open, setOpen] = useState(defaultOpen);
  const toggle = () => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setOpen((current) => !current);
  };

  return (
    <View style={styles.collapsible}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={title}
        accessibilityHint={open ? 'Double tap to hide these settings' : 'Double tap to show these settings'}
        accessibilityState={{ expanded: open }}
        onPress={toggle}
        style={({ pressed }) => [styles.collapsibleHeader, pressed && styles.pressed]}
      >
        {icon ? (
          <View style={styles.collapsibleIcon}>
            <Ionicons name={icon} size={18} color={colors.textMuted} />
          </View>
        ) : null}
        <View style={styles.collapsibleCopy}>
          <Text style={styles.collapsibleTitle}>{title}</Text>
          {summary ? <Text style={styles.collapsibleSummary}>{summary}</Text> : null}
        </View>
        {badge ? <Text style={styles.collapsibleBadge}>{badge}</Text> : null}
        <Ionicons name={open ? 'chevron-up' : 'chevron-down'} size={18} color={colors.accent} />
      </Pressable>
      {open ? <View style={styles.collapsibleBody}>{children}</View> : null}
    </View>
  );
}

/** A row of mutually exclusive choices, e.g. a units switch. */
export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label?: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <View style={styles.segmentWrap}>
      {label ? <Text style={styles.segmentLabel}>{label}</Text> : null}
      <View style={styles.segmentTrack}>
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <Pressable
              accessibilityRole="radio"
              accessibilityLabel={option.label}
              accessibilityState={{ selected }}
              key={option.value}
              onPress={() => onChange(option.value)}
              style={({ pressed }) => [
                styles.segment,
                selected && styles.segmentSelected,
                pressed && styles.pressed,
              ]}
            >
              <Text style={[styles.segmentText, selected && styles.segmentTextSelected]}>
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

/** A quiet explanatory line. Use it instead of leaving a control unexplained. */
export function HelpText({ children }: PropsWithChildren) {
  return <Text style={styles.helpText}>{children}</Text>;
}

/** A numbered instruction, for the "what do I do now" moments. */
export function StepRow({
  index,
  title,
  body,
  done = false,
}: {
  index: number;
  title: string;
  body: string;
  done?: boolean;
}) {
  return (
    <View style={styles.stepRow}>
      <View style={[styles.stepIndex, done && styles.stepIndexDone]}>
        {done ? (
          <Ionicons name="checkmark" size={15} color={colors.accentInk} />
        ) : (
          <Text style={styles.stepIndexText}>{index}</Text>
        )}
      </View>
      <View style={styles.stepCopy}>
        <Text style={[styles.stepTitle, done && styles.stepTitleDone]}>{title}</Text>
        <Text style={styles.stepBody}>{body}</Text>
      </View>
    </View>
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
  note,
}: {
  label: string;
  value: string;
  unit?: string;
  accent?: boolean;
  note?: string;
}) {
  return (
    <View style={styles.metricTile}>
      <Text style={styles.metricLabel}>{label}</Text>
      <View style={styles.metricValueRow}>
        <Text style={[styles.metricValue, accent && styles.metricValueAccent]}>{value}</Text>
        {unit ? <Text style={styles.metricUnit}>{unit}</Text> : null}
      </View>
      {note ? <Text style={styles.metricNote}>{note}</Text> : null}
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
  metricNote: { color: colors.textDim, fontSize: 10, fontWeight: '700', lineHeight: 14, marginTop: 5 },
  collapsible: {
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderRadius: radii.lg,
    borderWidth: 1,
    overflow: 'hidden',
  },
  collapsibleHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
    minHeight: 60,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  collapsibleIcon: {
    alignItems: 'center',
    backgroundColor: colors.surfaceRaised,
    borderRadius: 14,
    height: 36,
    justifyContent: 'center',
    width: 36,
  },
  collapsibleCopy: { flex: 1 },
  collapsibleTitle: { color: colors.text, fontSize: 15, fontWeight: '700' },
  collapsibleSummary: { color: colors.textMuted, fontSize: 12, lineHeight: 16, marginTop: 2 },
  collapsibleBadge: { color: colors.textMuted, fontSize: 11, fontWeight: '800' },
  collapsibleBody: {
    borderTopColor: colors.line,
    borderTopWidth: 1,
    padding: spacing.md,
  },
  segmentWrap: { gap: spacing.xs },
  segmentLabel: { color: colors.textMuted, fontSize: 12, fontWeight: '700' },
  segmentTrack: {
    backgroundColor: colors.surfaceRaised,
    borderColor: colors.line,
    borderRadius: radii.md,
    borderWidth: 1,
    flexDirection: 'row',
    padding: 3,
  },
  segment: {
    alignItems: 'center',
    borderRadius: radii.sm,
    flex: 1,
    justifyContent: 'center',
    minHeight: 42,
  },
  segmentSelected: { backgroundColor: colors.accent },
  segmentText: { color: colors.textMuted, fontSize: 13, fontWeight: '800' },
  segmentTextSelected: { color: colors.accentInk },
  helpText: { color: colors.textMuted, fontSize: 12, lineHeight: 17 },
  stepRow: { flexDirection: 'row', gap: spacing.sm },
  stepIndex: {
    alignItems: 'center',
    backgroundColor: colors.surfaceSoft,
    borderRadius: 14,
    height: 28,
    justifyContent: 'center',
    marginTop: 1,
    width: 28,
  },
  stepIndexDone: { backgroundColor: colors.accent },
  stepIndexText: { color: colors.textMuted, fontSize: 13, fontWeight: '800' },
  stepCopy: { flex: 1 },
  stepTitle: { color: colors.text, fontSize: 14, fontWeight: '700' },
  stepTitleDone: { color: colors.textMuted, textDecorationLine: 'line-through' },
  stepBody: { color: colors.textMuted, fontSize: 12, lineHeight: 17, marginTop: 2 },
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
