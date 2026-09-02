import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ScreenHeader } from '@/components/ScreenHeader';
import { ShotRow } from '@/components/ShotVisuals';
import { Eyebrow, SectionHeader, Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { colors, radii, spacing } from '@/theme';
import { Shot } from '@/types';

type Filter = 'session' | 'fastest' | 'centered';

export function HistoryScreen({ onOpenShot }: { onOpenShot: (shot: Shot) => void }) {
  const insets = useSafeAreaInsets();
  const { state, shots, isDemo } = useLaunchMonitor();
  const [filter, setFilter] = useState<Filter>('session');

  const sortedShots = useMemo(() => {
    if (filter === 'fastest') return [...shots].sort((a, b) => b.ballSpeedMps - a.ballSpeedMps);
    if (filter === 'centered') {
      return [...shots].sort(
        (a, b) => Math.hypot(a.strike.xMm, a.strike.yMm) - Math.hypot(b.strike.xMm, b.strike.yMm),
      );
    }
    return shots;
  }, [filter, shots]);

  const stats = useMemo(() => {
    if (!shots.length) return { avgBall: 0, avgSmash: 0, avgCarry: 0, consistency: 0 };
    const avgBall = shots.reduce((sum, shot) => sum + shot.ballSpeedMps, 0) / shots.length;
    const avgSmash = shots.reduce((sum, shot) => sum + shot.smashFactor, 0) / shots.length;
    const avgCarry = shots.reduce((sum, shot) => sum + shot.estimatedCarryM, 0) / shots.length;
    const variance = shots.reduce((sum, shot) => sum + (shot.ballSpeedMps - avgBall) ** 2, 0) / shots.length;
    const consistency = Math.max(0, 100 - (Math.sqrt(variance) / avgBall) * 300);
    return {
      avgBall,
      avgSmash,
      avgCarry,
      consistency,
    };
  }, [shots]);

  return (
    <ScrollView
      contentContainerStyle={[styles.content, { paddingTop: insets.top + spacing.md }]}
      showsVerticalScrollIndicator={false}
    >
      <ScreenHeader title="Sessions" subtitle={`${shots.length} shots today`} state={state} demo={isDemo} />

      <Surface style={styles.summary}>
        <View style={styles.summaryTop}>
          <View>
            <Eyebrow>Current session</Eyebrow>
            <Text style={styles.summaryTitle}>Range session</Text>
          </View>
          <View style={styles.datePill}>
            <Ionicons name="calendar-outline" size={13} color={colors.textMuted} />
            <Text style={styles.dateText}>Today</Text>
          </View>
        </View>
        <View style={styles.summaryStats}>
          <SummaryStat label="Avg ball" value={stats.avgBall.toFixed(1)} unit="m/s" />
          <View style={styles.divider} />
          <SummaryStat label="Avg smash" value={stats.avgSmash.toFixed(2)} />
          <View style={styles.divider} />
          <SummaryStat label="Avg carry" value={stats.avgCarry.toFixed(0)} unit="m" accent />
        </View>
        <View style={styles.consistencyHeader}>
          <Text style={styles.consistencyLabel}>Speed consistency</Text>
          <Text style={styles.consistencyValue}>{Math.round(stats.consistency)}%</Text>
        </View>
        <View style={styles.track}>
          <View style={[styles.trackFill, { width: `${stats.consistency}%` }]} />
        </View>
      </Surface>

      {shots.length ? (
        <Surface style={styles.trendCard}>
          <View style={styles.trendTop}>
            <View>
              <Eyebrow>Ball speed</Eyebrow>
              <Text style={styles.trendTitle}>Last {Math.min(8, shots.length)} shots</Text>
            </View>
            <View style={styles.deltaPill}>
              <Ionicons name="trending-up" size={14} color={colors.accent} />
              <Text style={styles.deltaText}>Live</Text>
            </View>
          </View>
          <MiniBarChart shots={shots.slice(0, 8).reverse()} />
        </Surface>
      ) : null}

      <View style={styles.shotsSection}>
        <SectionHeader title="Shot log" />
        <View style={styles.filters}>
          <FilterChip label="Session" active={filter === 'session'} onPress={() => setFilter('session')} />
          <FilterChip label="Fastest" active={filter === 'fastest'} onPress={() => setFilter('fastest')} />
          <FilterChip label="Centered" active={filter === 'centered'} onPress={() => setFilter('centered')} />
        </View>
        {sortedShots.length ? (
          <View style={styles.list}>
            {sortedShots.map((shot) => (
              <ShotRow key={shot.id} shot={shot} onPress={() => onOpenShot(shot)} />
            ))}
          </View>
        ) : (
          <Surface style={styles.empty}>
            <Ionicons name="stats-chart-outline" size={28} color={colors.textDim} />
            <Text style={styles.emptyTitle}>No shots yet</Text>
            <Text style={styles.emptyBody}>New captures will build your session automatically.</Text>
          </Surface>
        )}
      </View>
    </ScrollView>
  );
}

function SummaryStat({
  label,
  value,
  unit,
  accent,
}: {
  label: string;
  value: string;
  unit?: string;
  accent?: boolean;
}) {
  return (
    <View style={styles.summaryStat}>
      <Text style={styles.summaryStatLabel}>{label}</Text>
      <View style={styles.summaryValueRow}>
        <Text style={[styles.summaryStatValue, accent && styles.accent]}>{value}</Text>
        {unit ? <Text style={styles.summaryStatUnit}>{unit}</Text> : null}
      </View>
    </View>
  );
}

function FilterChip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      onPress={onPress}
      style={({ pressed }) => [styles.filter, active && styles.filterActive, pressed && styles.filterPressed]}
    >
      <Text style={[styles.filterText, active && styles.filterTextActive]}>{label}</Text>
    </Pressable>
  );
}

function MiniBarChart({ shots }: { shots: Shot[] }) {
  const min = Math.min(...shots.map((shot) => shot.ballSpeedMps)) - 1;
  const max = Math.max(...shots.map((shot) => shot.ballSpeedMps)) + 1;
  const range = Math.max(1, max - min);
  return (
    <View accessibilityLabel="Ball speed trend chart" style={styles.chart}>
      {shots.map((shot, index) => {
        const height = 30 + ((shot.ballSpeedMps - min) / range) * 52;
        const isBest = shot.ballSpeedMps === Math.max(...shots.map((item) => item.ballSpeedMps));
        return (
          <View key={shot.id} style={styles.barColumn}>
            <View style={[styles.bar, { height }, isBest && styles.barBest]} />
            <Text style={styles.barLabel}>{index + 1}</Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 110, paddingHorizontal: spacing.md },
  summary: { padding: spacing.lg },
  summaryTop: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  summaryTitle: { color: colors.text, fontSize: 23, fontWeight: '700', letterSpacing: -0.6, marginTop: 4 },
  datePill: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: radii.pill, flexDirection: 'row', gap: 5, paddingHorizontal: 10, paddingVertical: 7 },
  dateText: { color: colors.textMuted, fontSize: 11, fontWeight: '700' },
  summaryStats: { flexDirection: 'row', marginVertical: spacing.lg },
  summaryStat: { flex: 1 },
  summaryStatLabel: { color: colors.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 0.7, textTransform: 'uppercase' },
  summaryValueRow: { alignItems: 'baseline', flexDirection: 'row', gap: 3, marginTop: 4 },
  summaryStatValue: { color: colors.text, fontSize: 24, fontWeight: '700', letterSpacing: -0.8 },
  summaryStatUnit: { color: colors.textDim, fontSize: 9, fontWeight: '700' },
  accent: { color: colors.accent },
  divider: { backgroundColor: colors.line, marginHorizontal: spacing.md, width: 1 },
  consistencyHeader: { flexDirection: 'row', justifyContent: 'space-between' },
  consistencyLabel: { color: colors.textMuted, fontSize: 11, fontWeight: '600' },
  consistencyValue: { color: colors.text, fontSize: 11, fontWeight: '800' },
  track: { backgroundColor: colors.surfaceSoft, borderRadius: radii.pill, height: 6, marginTop: 9, overflow: 'hidden' },
  trackFill: { backgroundColor: colors.accent, borderRadius: radii.pill, height: '100%' },
  trendCard: { marginTop: spacing.sm, padding: spacing.lg },
  trendTop: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  trendTitle: { color: colors.text, fontSize: 17, fontWeight: '700', marginTop: 3 },
  deltaPill: { alignItems: 'center', backgroundColor: '#182117', borderRadius: radii.pill, flexDirection: 'row', gap: 4, paddingHorizontal: 9, paddingVertical: 6 },
  deltaText: { color: colors.accent, fontSize: 10, fontWeight: '800' },
  chart: { alignItems: 'flex-end', flexDirection: 'row', gap: 8, height: 108, marginTop: spacing.md },
  barColumn: { alignItems: 'center', flex: 1, justifyContent: 'flex-end', height: '100%' },
  bar: { backgroundColor: colors.surfaceSoft, borderRadius: 5, minWidth: 13, width: '70%' },
  barBest: { backgroundColor: colors.accent },
  barLabel: { color: colors.textDim, fontSize: 8, fontWeight: '700', marginTop: 6 },
  shotsSection: { marginTop: spacing.xl },
  filters: { flexDirection: 'row', gap: 8, marginBottom: spacing.md },
  filter: { backgroundColor: colors.surface, borderColor: colors.line, borderRadius: radii.pill, borderWidth: 1, paddingHorizontal: 14, paddingVertical: 8 },
  filterActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  filterPressed: { opacity: 0.75 },
  filterText: { color: colors.textMuted, fontSize: 11, fontWeight: '700' },
  filterTextActive: { color: colors.accentInk },
  list: { gap: spacing.sm },
  empty: { alignItems: 'center', padding: spacing.xl },
  emptyTitle: { color: colors.text, fontSize: 18, fontWeight: '700', marginTop: spacing.md },
  emptyBody: { color: colors.textMuted, fontSize: 12, marginTop: 6, textAlign: 'center' },
});
