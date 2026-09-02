import Ionicons from '@expo/vector-icons/Ionicons';
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { StatusBadge } from '@/components/ui';
import { colors, spacing } from '@/theme';
import { DeviceState } from '@/types';

export function ScreenHeader({
  title = 'Pinpoint',
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
        <View style={styles.mark}>
          <Ionicons name="golf" size={18} color={colors.accentInk} />
        </View>
        <View>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.subtitle}>{subtitle}</Text>
        </View>
      </View>
      <StatusBadge state={state} demo={demo} />
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: spacing.xl,
  },
  brandRow: { alignItems: 'center', flexDirection: 'row', gap: 11 },
  mark: {
    alignItems: 'center',
    backgroundColor: colors.accent,
    borderRadius: 13,
    height: 40,
    justifyContent: 'center',
    width: 40,
  },
  title: { color: colors.text, fontSize: 18, fontWeight: '800', letterSpacing: -0.4 },
  subtitle: { color: colors.textMuted, fontSize: 10, fontWeight: '600', marginTop: 1 },
});
