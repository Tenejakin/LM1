import Ionicons from '@expo/vector-icons/Ionicons';
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Eyebrow, Surface } from '@/components/ui';
import { colors, spacing } from '@/theme';
import { Readiness, ReadinessStatus } from '@/types';

const TONE: Record<ReadinessStatus, { icon: keyof typeof Ionicons.glyphMap; color: string }> = {
  ok: { icon: 'checkmark-circle', color: colors.accent },
  warn: { icon: 'alert-circle', color: colors.orange },
  fail: { icon: 'close-circle', color: colors.red },
};

/**
 * Pre-shot verdict from the Pi, checked when the ball is placed: problems that would
 * otherwise only appear as a failed measurement after the swing.
 */
export function ReadinessCard({ readiness }: { readiness: Readiness | null | undefined }) {
  if (!readiness) return null;
  const problems = readiness.items.filter((item) => item.status !== 'ok');
  if (!problems.length) {
    return (
      <View accessibilityLabel="Setup checks passed" style={styles.okRow}>
        <Ionicons name={TONE.ok.icon} size={16} color={TONE.ok.color} />
        <Text style={styles.okText}>Setup checks passed: cameras aligned, exposure fast enough.</Text>
      </View>
    );
  }
  const title = readiness.status === 'fail' ? 'Fix before you hit' : 'Some values will be missing';
  return (
    <Surface style={styles.card}>
      <Eyebrow>Setup check</Eyebrow>
      <Text style={styles.title}>{title}</Text>
      {problems.map((item) => (
        <View key={item.id} style={styles.item}>
          <Ionicons name={TONE[item.status].icon} size={18} color={TONE[item.status].color} style={styles.icon} />
          <View style={styles.itemCopy}>
            <Text style={[styles.itemLabel, { color: TONE[item.status].color }]}>{item.label}</Text>
            <Text style={styles.itemDetail}>{item.detail}</Text>
          </View>
        </View>
      ))}
    </Surface>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.sm, marginTop: spacing.md, padding: spacing.lg },
  title: { color: colors.text, fontSize: 18, fontWeight: '700' },
  item: { flexDirection: 'row', gap: spacing.sm },
  icon: { marginTop: 1 },
  itemCopy: { flex: 1, gap: 2 },
  itemLabel: { fontSize: 13, fontWeight: '700' },
  itemDetail: { color: colors.textMuted, fontSize: 13, lineHeight: 18 },
  okRow: { alignItems: 'center', flexDirection: 'row', gap: spacing.xs, marginTop: spacing.md, paddingHorizontal: spacing.xs },
  okText: { color: colors.textMuted, flex: 1, fontSize: 12 },
});
