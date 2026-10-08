import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { StatusBadge } from '@/components/ui';
import { colors, fonts, spacing } from '@/theme';
import { DeviceState } from '@/types';

export function ScreenHeader({
  title = 'LM1',
  subtitle = 'Launch monitor',
  state,
  demo,
}: {
  title?: string;
  subtitle?: string;
  state: DeviceState;
  demo?: boolean;
}) {
  return (
    <View style={styles.header}>
      <View style={styles.brandRow}>
        <Text style={styles.title}>{title}</Text>
        <View style={styles.divider} />
        <Text style={styles.subtitle}>{subtitle}</Text>
      </View>
      <StatusBadge state={state} demo={demo} />
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    alignItems: 'center',
    borderBottomColor: colors.line,
    borderBottomWidth: 1,
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: spacing.lg,
    paddingBottom: spacing.md,
  },
  brandRow: { alignItems: 'center', flexDirection: 'row', gap: 11 },
  title: { color: colors.text, fontSize: 20, fontWeight: '800', letterSpacing: 5 },
  divider: { backgroundColor: colors.lineStrong, height: 14, width: 1 },
  subtitle: { color: colors.textMuted, fontFamily: fonts.mono, fontSize: 9, fontWeight: '600', letterSpacing: 1.8, textTransform: 'uppercase' },
});
