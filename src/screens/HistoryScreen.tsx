import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ScreenHeader } from '@/components/ScreenHeader';
import { CaptureReview } from '@/components/CaptureReview';
import { ShotRow } from '@/components/ShotVisuals';
import { Eyebrow, PrimaryButton, SectionHeader, Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { useN8n } from '@/context/N8nContext';
import { useUnits } from '@/context/UnitsContext';
import { colors, radii, spacing } from '@/theme';
import { CaptureAnalysis, N8nSendState, Shot } from '@/types';
import { directionLabel } from '@/utils/direction';
import { measuredSmash, measuredStrike } from '@/utils/shotValues';
import { includedShots } from '@/utils/session';
import { SessionClubs } from '@/components/SessionClubs';

type Filter = 'session' | 'fastest' | 'centered';

function captureMetric(capture: CaptureAnalysis, key: string): number | null {
  return capture.measurements?.metrics[key]?.value ?? null;
}

export function HistoryScreen({ onOpenShot, onOpenCalculator }: { onOpenShot: (shot: Shot) => void; onOpenCalculator: () => void }) {
  const insets = useSafeAreaInsets();
  const { state, shots, captures, isDemo } = useLaunchMonitor();
  const { ready: n8nReady, sendShot, sendCapture } = useN8n();
  const units = useUnits();
  const [filter, setFilter] = useState<Filter>('session');
  const [n8nStates, setN8nStates] = useState<Record<string, N8nSendState>>({});
  const [n8nErrors, setN8nErrors] = useState<Record<string, string>>({});

  const sendToN8n = async (shot: Shot) => {
    setN8nStates((current) => ({ ...current, [shot.id]: 'sending' }));
    setN8nErrors((current) => ({ ...current, [shot.id]: '' }));
    try {
      await sendShot(shot);
      setN8nStates((current) => ({ ...current, [shot.id]: 'sent' }));
    } catch (error) {
      setN8nStates((current) => ({ ...current, [shot.id]: 'error' }));
      setN8nErrors((current) => ({
        ...current,
        [shot.id]: error instanceof Error ? error.message : 'Could not send this shot to n8n.',
      }));
    }
  };

  const sendCaptureToN8n = async (capture: CaptureAnalysis) => {
    setN8nStates((current) => ({ ...current, [capture.id]: 'sending' }));
    setN8nErrors((current) => ({ ...current, [capture.id]: '' }));
    try {
      await sendCapture(capture);
      setN8nStates((current) => ({ ...current, [capture.id]: 'sent' }));
    } catch (error) {
      setN8nStates((current) => ({ ...current, [capture.id]: 'error' }));
      setN8nErrors((current) => ({
        ...current,
        [capture.id]: error instanceof Error ? error.message : 'Could not send this camera hit to n8n.',
      }));
    }
  };
  // Avoid counting the same motion-tracked capture twice after it becomes a shot.
  const speedSamples = useMemo(() => {
    const shotIds = new Set(shots.map((shot) => shot.id));
    return [
      ...includedShots(shots).map((shot) => ({ id: shot.id, ballSpeedMps: shot.ballSpeedMps })),
      ...captures.flatMap((capture) => {
      if (shotIds.has(capture.id) || (capture.mode === 'full-shot' && capture.measurements?.shotEvidence?.status === 'not-a-strike')) return [];
      const speed = captureMetric(capture, 'ballSpeedMps');
      return speed === null ? [] : [{ id: capture.id, ballSpeedMps: speed }];
    }),
    ];
  }, [captures, shots]);

  const sortedShots = useMemo(() => {
    if (filter === 'fastest') return [...shots].sort((a, b) => b.ballSpeedMps - a.ballSpeedMps);
    if (filter === 'centered') {
      // Shots without a measured strike cannot be ranked by it and sort last.
      const offset = (shot: Shot) => {
        const strike = measuredStrike(shot);
        return strike ? Math.hypot(strike.xMm, strike.yMm) : Number.POSITIVE_INFINITY;
      };
      return [...shots].sort((a, b) => offset(a) - offset(b));
    }
    return shots;
  }, [filter, shots]);

  const stats = useMemo(() => {
    const avgBall = speedSamples.length
      ? speedSamples.reduce((sum, sample) => sum + sample.ballSpeedMps, 0) / speedSamples.length
      : 0;
    const variance = speedSamples.length
      ? speedSamples.reduce((sum, sample) => sum + (sample.ballSpeedMps - avgBall) ** 2, 0) / speedSamples.length
      : 0;
    const consistency = avgBall > 0 ? Math.max(0, 100 - (Math.sqrt(variance) / avgBall) * 300) : 0;
    const counted = includedShots(shots);
    const smashSamples = counted.map(measuredSmash).filter((smash): smash is number => smash !== null);
    const avgSmash = smashSamples.length ? smashSamples.reduce((sum, smash) => sum + smash, 0) / smashSamples.length : null;
    const avgCarry = counted.length ? counted.reduce((sum, shot) => sum + shot.estimatedCarryM, 0) / counted.length : null;
    return { avgBall, avgSmash, avgCarry, consistency };
  }, [shots, speedSamples]);

  return (
    <ScrollView
      contentContainerStyle={[styles.content, { paddingTop: insets.top + spacing.md }]}
      showsVerticalScrollIndicator={false}
    >
      <ScreenHeader
        title="Sessions"
        subtitle={captures.length ? `${shots.length} shots · ${captures.length} captures today` : `${shots.length} shots today`}
        state={state}
        demo={isDemo}
      />
      <CaptureReview history />

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
          <SummaryStat label="Avg ball" value={units.speed(stats.avgBall)} unit={units.speedLabel} />
          <View style={styles.divider} />
          <SummaryStat label="Avg smash" value={stats.avgSmash === null ? '—' : stats.avgSmash.toFixed(2)} />
          <View style={styles.divider} />
          <SummaryStat label="Avg carry" value={stats.avgCarry === null ? '—' : units.distance(stats.avgCarry)} unit={units.distanceLabel} accent />
        </View>
        <View style={styles.consistencyHeader}>
          <Text style={styles.consistencyLabel}>Speed consistency</Text>
          <Text style={styles.consistencyValue}>{Math.round(stats.consistency)}%</Text>
        </View>
        <View style={styles.track}>
          <View style={[styles.trackFill, { width: `${stats.consistency}%` }]} />
        </View>
      </Surface>

      <SessionClubs shots={shots} />

      <View style={styles.calculatorSection}>
        <Surface style={styles.calculatorCard}>
          <View style={styles.calculatorCopy}>
            <Eyebrow>Session tools</Eyebrow>
            <Text style={styles.calculatorTitle}>Shot calculator</Text>
            <Text style={styles.calculatorBody}>Enter or refine a shot result without leaving your session.</Text>
          </View>
          <View style={styles.calculatorButton}>
            <PrimaryButton label="Open Calc" icon="calculator-outline" onPress={onOpenCalculator} variant="outline" />
          </View>
        </Surface>
      </View>

      {speedSamples.length ? (
        <Surface style={styles.trendCard}>
          <View style={styles.trendTop}>
            <View>
              <Eyebrow>Ball speed</Eyebrow>
              <Text style={styles.trendTitle}>Last {Math.min(8, speedSamples.length)} hits</Text>
            </View>
            <View style={styles.deltaPill}>
              <Ionicons name="trending-up" size={14} color={colors.accent} />
              <Text style={styles.deltaText}>Live</Text>
            </View>
          </View>
          <MiniBarChart samples={speedSamples.slice(0, 8).reverse()} />
        </Surface>
      ) : null}

      {captures.length ? (
        <View style={styles.shotsSection}>
          <SectionHeader title="Camera hits" />
          {!n8nReady ? (
            <View style={styles.n8nSetupNote}>
              <Ionicons name="information-circle-outline" size={16} color={colors.cyan} />
              <Text style={styles.n8nSetupText}>Add your n8n webhook in Device to enable camera-hit sending.</Text>
            </View>
          ) : null}
          <View style={styles.list}>
            {captures.map((capture, index) => {
              const speed = captureMetric(capture, 'ballSpeedMps');
              const launch = captureMetric(capture, 'launchAngleDeg');
              const direction = captureMetric(capture, 'startDirectionDeg');
              const time = new Date(capture.capturedAt);
              const sendState = n8nStates[capture.id] ?? 'idle';
              return (
                <View key={capture.id} style={styles.shotWithSend}>
                  <Surface style={[styles.hitRow, styles.hitRowCell]}>
                    <View style={styles.hitMeta}>
                      <Text style={styles.hitTitle}>
                        Capture {captures.length - index}
                      </Text>
                      <Text style={styles.hitTime}>
                        {Number.isNaN(time.getTime()) ? '' : time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                      </Text>
                      <Text style={[styles.hitClass, speed !== null && capture.classification === 'motion-observed' ? styles.hitClassOk : styles.hitClassWeak]}>
                        {capture.mode === 'full-shot' && capture.measurements?.shotEvidence?.status === 'not-a-strike' ? 'not a strike'
                          : capture.mode === 'full-shot' && speed === null ? 'tracking failed'
                          : capture.classification === 'motion-observed' ? 'ball motion seen' : 'ball not seen leaving'}
                      </Text>
                    </View>
                    <View style={styles.hitMetrics}>
                      <View style={styles.hitMetric}>
                        <Text style={[styles.hitValue, speed === null && styles.hitMissing]}>
                          {speed === null ? '—' : units.speed(speed)}
                        </Text>
                        <Text style={styles.hitUnit}>{units.speedLabel}</Text>
                      </View>
                      <View style={styles.hitMetric}>
                        <Text style={[styles.hitValue, launch === null && styles.hitMissing]}>
                          {launch === null ? '—' : launch.toFixed(1)}
                        </Text>
                        <Text style={styles.hitUnit}>launch°</Text>
                      </View>
                      <View style={styles.hitMetric}>
                        <Text style={[styles.hitValue, direction === null && styles.hitMissing]}>
                          {direction === null ? '—' : directionLabel(direction)}
                        </Text>
                        <Text style={styles.hitUnit}>direction</Text>
                      </View>
                    </View>
                  </Surface>
                  <N8nSendButton
                    label={`Send camera hit ${captures.length - index} to n8n`}
                    ready={n8nReady}
                    state={sendState}
                    onPress={() => void sendCaptureToN8n(capture)}
                  />
                  {n8nErrors[capture.id] ? <Text style={styles.n8nError}>{n8nErrors[capture.id]}</Text> : null}
                </View>
              );
            })}
          </View>
          <Text style={styles.hitNote}>
            Camera hits keep the raw analysis. Only hits with camera-derived speed,
            launch and direction appear as shots below; failed tracking stays here as unavailable.
          </Text>
        </View>
      ) : null}

      <View style={styles.shotsSection}>
        <SectionHeader title="Shot log" />
        {!n8nReady ? (
          <View style={styles.n8nSetupNote}>
            <Ionicons name="information-circle-outline" size={16} color={colors.cyan} />
            <Text style={styles.n8nSetupText}>Add your n8n webhook in Device to enable shot sending.</Text>
          </View>
        ) : null}
        <View style={styles.filters}>
          <FilterChip label="Session" active={filter === 'session'} onPress={() => setFilter('session')} />
          <FilterChip label="Fastest" active={filter === 'fastest'} onPress={() => setFilter('fastest')} />
          <FilterChip label="Centered" active={filter === 'centered'} onPress={() => setFilter('centered')} />
        </View>
        {sortedShots.length ? (
          <View style={styles.list}>
            {sortedShots.map((shot) => {
              const sendState = n8nStates[shot.id] ?? 'idle';
              return (
                <View key={shot.id} style={styles.shotWithSend}>
                  <View style={styles.shotRowCell}>
                    <ShotRow shot={shot} onPress={() => onOpenShot(shot)} />
                  </View>
                  <N8nSendButton
                    label={`Send shot ${shot.number} to n8n`}
                    ready={n8nReady}
                    state={sendState}
                    onPress={() => void sendToN8n(shot)}
                  />
                  {n8nErrors[shot.id] ? <Text style={styles.n8nError}>{n8nErrors[shot.id]}</Text> : null}
                </View>
              );
            })}
          </View>
        ) : (
          <Surface style={styles.empty}>
            <Ionicons name="stats-chart-outline" size={28} color={colors.textDim} />
            <Text style={styles.emptyTitle}>No shots yet</Text>
            <Text style={styles.emptyBody}>Hit a shot and it will show up here automatically.</Text>
          </Surface>
        )}
      </View>
    </ScrollView>
  );
}

function N8nSendButton({
  label,
  ready,
  state,
  onPress,
}: {
  label: string;
  ready: boolean;
  state: N8nSendState;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !ready, busy: state === 'sending' }}
      disabled={!ready || state === 'sending'}
      onPress={onPress}
      style={({ pressed }) => [
        styles.n8nButton,
        state === 'sent' && styles.n8nButtonSent,
        state === 'error' && styles.n8nButtonError,
        !ready && styles.n8nButtonDisabled,
        pressed && styles.filterPressed,
      ]}
    >
      <Ionicons
        name={state === 'sent' ? 'checkmark' : state === 'error' ? 'alert' : 'paper-plane-outline'}
        size={19}
        color={state === 'sent' ? colors.accentInk : colors.text}
      />
      <Text style={[styles.n8nButtonText, state === 'sent' && styles.n8nButtonTextSent]}>
        {state === 'sending' ? 'Sending' : state === 'sent' ? 'Sent' : 'n8n'}
      </Text>
    </Pressable>
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

function MiniBarChart({ samples }: { samples: { id: string; ballSpeedMps: number }[] }) {
  const min = Math.min(...samples.map((sample) => sample.ballSpeedMps)) - 1;
  const max = Math.max(...samples.map((sample) => sample.ballSpeedMps)) + 1;
  const range = Math.max(1, max - min);
  const best = Math.max(...samples.map((sample) => sample.ballSpeedMps));
  return (
    <View accessibilityLabel="Ball speed trend chart" style={styles.chart}>
      {samples.map((shot, index) => {
        const height = 30 + ((shot.ballSpeedMps - min) / range) * 52;
        const isBest = shot.ballSpeedMps === best;
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
  calculatorSection: { marginTop: spacing.sm },
  calculatorCard: { alignItems: 'center', flexDirection: 'row', padding: spacing.md },
  calculatorCopy: { flex: 1, paddingRight: spacing.sm },
  calculatorTitle: { color: colors.text, fontSize: 15, fontWeight: '800', marginTop: 3 },
  calculatorBody: { color: colors.textMuted, fontSize: 10, lineHeight: 14, marginTop: 3 },
  calculatorButton: { width: 112 },
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
  n8nSetupNote: { alignItems: 'center', backgroundColor: '#142322', borderRadius: radii.sm, flexDirection: 'row', gap: 8, marginBottom: spacing.md, padding: 10 },
  n8nSetupText: { color: colors.textMuted, flex: 1, fontSize: 10, lineHeight: 14 },
  filter: { backgroundColor: colors.surface, borderColor: colors.line, borderRadius: radii.pill, borderWidth: 1, paddingHorizontal: 14, paddingVertical: 8 },
  filterActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  filterPressed: { opacity: 0.75 },
  filterText: { color: colors.textMuted, fontSize: 11, fontWeight: '700' },
  filterTextActive: { color: colors.accentInk },
  list: { gap: spacing.sm },
  shotWithSend: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  shotRowCell: { flex: 1, minWidth: 0 },
  n8nButton: { alignItems: 'center', backgroundColor: colors.surfaceSoft, borderColor: colors.lineStrong, borderRadius: radii.md, borderWidth: 1, justifyContent: 'center', minHeight: 76, width: 64 },
  n8nButtonSent: { backgroundColor: colors.accent, borderColor: colors.accent },
  n8nButtonError: { backgroundColor: '#2A1718', borderColor: '#583030' },
  n8nButtonDisabled: { opacity: 0.4 },
  n8nButtonText: { color: colors.text, fontSize: 9, fontWeight: '800', marginTop: 4 },
  n8nButtonTextSent: { color: colors.accentInk },
  n8nError: { color: colors.red, fontSize: 10, lineHeight: 14, paddingHorizontal: spacing.sm, width: '100%' },
  hitRow: { alignItems: 'center', flexDirection: 'row', padding: spacing.md },
  hitRowCell: { flex: 1, minWidth: 0 },
  hitMeta: { flex: 1 },
  hitTitle: { color: colors.text, fontSize: 14, fontWeight: '800' },
  hitTime: { color: colors.textMuted, fontSize: 10, fontWeight: '700', marginTop: 2 },
  hitClass: { fontSize: 9, fontWeight: '800', letterSpacing: 0.5, marginTop: 4, textTransform: 'uppercase' },
  hitClassOk: { color: colors.accent },
  hitClassWeak: { color: colors.orange },
  hitMetrics: { flexDirection: 'row', gap: spacing.md },
  hitMetric: { alignItems: 'flex-end', minWidth: 52 },
  hitValue: { color: colors.text, fontSize: 18, fontWeight: '700', letterSpacing: -0.5 },
  hitMissing: { color: colors.textDim },
  hitUnit: { color: colors.textDim, fontSize: 9, fontWeight: '700', marginTop: 1 },
  hitNote: { color: colors.textDim, fontSize: 10, lineHeight: 14, marginTop: spacing.md, textAlign: 'center' },
  empty: { alignItems: 'center', padding: spacing.xl },
  emptyTitle: { color: colors.text, fontSize: 18, fontWeight: '700', marginTop: spacing.md },
  emptyBody: { color: colors.textMuted, fontSize: 12, marginTop: 6, textAlign: 'center' },
});
