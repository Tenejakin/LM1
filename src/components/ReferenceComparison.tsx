import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Eyebrow, Surface } from '@/components/ui';
import { useUnits } from '@/context/UnitsContext';
import { colors, radii, spacing } from '@/theme';
import { Shot } from '@/types';
import {
  clubComparisons, COMPARISON_METRICS, ComparisonMetric, ComparisonUnit, lm1SpinEstimated, lm1Value, MetricComparison,
  referenceComparison, referenceValue,
} from '@/utils/sessions';

type Units = ReturnType<typeof useUnits>;

/** A value in display units with the right precision for its kind. */
function formatValue(value: number | null, unit: ComparisonUnit, units: Units, digits?: number): string {
  if (value === null || !Number.isFinite(value)) return '—';
  switch (unit) {
    case 'speed': return units.speed(value, digits ?? 1);
    case 'distance': return units.distance(value, digits ?? 1);
    case 'ratio': return value.toFixed(digits ?? 2);
    case 'rpm': return Math.round(value).toLocaleString();
    default: return value.toFixed(digits ?? 1);
  }
}

/** A difference in display units, signed, so a bias reads as "+2.1" or "−0.4". */
function formatDelta(value: number, unit: ComparisonUnit, units: Units): string {
  const magnitude = formatValue(Math.abs(value), unit, units, unit === 'ratio' ? 3 : undefined);
  if (Math.abs(value) < 1e-9) return '0';
  return `${value < 0 ? '−' : '+'}${magnitude}`;
}

function unitLabel(unit: ComparisonUnit, units: Units): string {
  switch (unit) {
    case 'speed': return units.speedLabel;
    case 'distance': return units.distanceLabel;
    case 'rpm': return 'rpm';
    case 'deg': return '°';
    default: return '';
  }
}

/** Side by side values for one shot: LM1, the reference monitor and the difference. */
export function ShotReferenceCard({ shot, onEdit }: { shot: Shot; onEdit: () => void }) {
  const units = useUnits();
  const reference = shot.reference;
  const rows = useMemo(() => COMPARISON_METRICS.flatMap((metric) => {
    const lm1 = lm1Value(shot, metric.key);
    const ref = referenceValue(reference, metric.key);
    if (lm1 === null && ref === null) return [];
    return [{ metric, lm1, ref }];
  }), [shot, reference]);
  return (
    <Surface style={styles.card}>
      <View style={styles.header}>
        <View style={styles.headerCopy}>
          <Eyebrow>Reference launch monitor</Eyebrow>
          <Text style={styles.title}>{reference ? `LM1 vs ${reference.device}` : 'Compare with another monitor'}</Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={reference ? 'Edit reference data' : 'Enter reference data'}
          onPress={onEdit}
          style={({ pressed }) => [styles.editButton, pressed && styles.pressed]}
        >
          <Ionicons name={reference ? 'create-outline' : 'add'} size={16} color={colors.accentInk} />
          <Text style={styles.editText}>{reference ? 'Edit' : 'Enter data'}</Text>
        </Pressable>
      </View>
      {reference ? (
        <>
          <View style={[styles.row, styles.headRow]}>
            <Text style={[styles.cell, styles.metricCell, styles.head]}>Metric</Text>
            <Text style={[styles.cell, styles.head]}>LM1</Text>
            <Text style={[styles.cell, styles.head]}>{reference.device}</Text>
            <Text style={[styles.cell, styles.head]}>Δ</Text>
          </View>
          {rows.map(({ metric, lm1, ref }) => {
            const estimated = metric.lm1Estimated || (metric.key === 'spinRpm' && lm1SpinEstimated(shot));
            return (
              <View key={metric.key} style={styles.row}>
                <View style={[styles.cell, styles.metricCell]}>
                  <Text style={styles.metric}>{metric.label}</Text>
                  <Text style={styles.metricUnit}>{unitLabel(metric.unit, units)}{estimated && lm1 !== null ? ' · LM1 model' : ''}</Text>
                </View>
                <Text style={[styles.cell, styles.value, lm1 === null && styles.missing]}>{formatValue(lm1, metric.unit, units)}</Text>
                <Text style={[styles.cell, styles.value, ref === null && styles.missing]}>{formatValue(ref, metric.unit, units)}</Text>
                <Text style={[styles.cell, styles.delta, (lm1 === null || ref === null) && styles.missing]}>
                  {lm1 === null || ref === null ? '—' : formatDelta(lm1 - ref, metric.unit, units)}
                </Text>
              </View>
            );
          })}
          {reference.notes ? <Text style={styles.notes}>{reference.notes}</Text> : null}
          <Text style={styles.note}>
            Δ is LM1 minus {reference.device}. Direction, path and spin axis: positive is right. LM1 carry, total, apex
            and model spin are calculated, not measured.
          </Text>
        </>
      ) : (
        <Text style={styles.note}>
          Hitting on LM1 next to another launch monitor? Type its numbers for this swing and the session view will show
          how far apart the two are, per metric and per club.
        </Text>
      )}
    </Surface>
  );
}

/** Agreement across a set of shots: bias and scatter per metric, overall and per club. */
export function SessionReferenceCard({ shots }: { shots: Shot[] }) {
  const units = useUnits();
  const overall = useMemo(() => referenceComparison(shots), [shots]);
  const byClub = useMemo(() => clubComparisons(shots), [shots]);
  const [expandedClub, setExpandedClub] = useState<string | null>(null);
  if (!overall.referencedShots) return null;
  const device = shots.find((shot) => shot.reference)?.reference?.device ?? 'reference';
  return (
    <Surface style={styles.card}>
      <Eyebrow>Reference comparison</Eyebrow>
      <Text style={styles.title}>LM1 vs {device} · {overall.referencedShots} {overall.referencedShots === 1 ? 'shot' : 'shots'}</Text>
      <ComparisonTable metrics={overall.metrics} units={units} />
      {byClub.length > 1 ? (
        <View style={styles.clubs}>
          <Text style={styles.subheading}>By club</Text>
          {byClub.map((club) => {
            const open = expandedClub === club.key;
            const ball = club.comparison.metrics.find((item) => item.metric.key === 'ballSpeedMps');
            return (
              <View key={club.key} style={styles.club}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityState={{ expanded: open }}
                  onPress={() => setExpandedClub(open ? null : club.key)}
                  style={styles.clubHeader}
                >
                  <Text style={styles.clubName} numberOfLines={1}>{club.label}</Text>
                  <Text style={styles.clubSummary}>
                    {club.shots} {club.shots === 1 ? 'shot' : 'shots'}
                    {ball ? ` · ball ${formatDelta(ball.delta.mean, 'speed', units)} ${units.speedLabel}` : ''}
                  </Text>
                  <Ionicons name={open ? 'chevron-up' : 'chevron-down'} size={16} color={colors.textDim} />
                </Pressable>
                {open ? <ComparisonTable metrics={club.comparison.metrics} units={units} /> : null}
              </View>
            );
          })}
        </View>
      ) : null}
      <Text style={styles.note}>
        Bias is the average of LM1 minus {device}; ± is one standard deviation of that difference, so it shows scatter
        after the bias is removed. MAE is the mean absolute difference. Only shots with both values count; excluded
        shots are left out. LM1 spin, carry, total and apex are model estimates.
      </Text>
    </Surface>
  );
}

function ComparisonTable({ metrics, units }: { metrics: MetricComparison[]; units: Units }) {
  return (
    <View style={styles.table}>
      <View style={[styles.row, styles.headRow]}>
        <Text style={[styles.cell, styles.metricCell, styles.head]}>Metric</Text>
        <Text style={[styles.cell, styles.head]}>n</Text>
        <Text style={[styles.cell, styles.head, styles.wide]}>Bias ± sd</Text>
        <Text style={[styles.cell, styles.head]}>MAE</Text>
      </View>
      {metrics.map((item) => (
        <View key={item.metric.key} style={styles.row}>
          <View style={[styles.cell, styles.metricCell]}>
            <Text style={styles.metric}>{item.metric.label}</Text>
            <Text style={styles.metricUnit}>
              {unitLabel(item.metric.unit, units)}{item.metric.lm1Estimated ? ' · LM1 model' : ''}
            </Text>
          </View>
          <Text style={[styles.cell, styles.value]}>{item.pairs.length}</Text>
          <Text style={[styles.cell, styles.delta, styles.wide]}>
            {formatDelta(item.delta.mean, item.metric.unit, units)}
            {item.delta.sd === null ? '' : ` ± ${formatValue(item.delta.sd, item.metric.unit, units, item.metric.unit === 'ratio' ? 3 : undefined)}`}
          </Text>
          <Text style={[styles.cell, styles.value]}>
            {formatValue(item.meanAbsDelta, item.metric.unit, units, item.metric.unit === 'ratio' ? 3 : undefined)}
            {item.meanAbsPct === null ? '' : `\n${item.meanAbsPct.toFixed(0)}%`}
          </Text>
        </View>
      ))}
    </View>
  );
}

export type { ComparisonMetric };

const styles = StyleSheet.create({
  card: { gap: spacing.sm, marginTop: spacing.sm, padding: spacing.lg },
  header: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  headerCopy: { flex: 1, paddingRight: spacing.sm },
  title: { color: colors.text, fontSize: 18, fontWeight: '700', marginTop: 3 },
  editButton: { alignItems: 'center', backgroundColor: colors.accent, borderRadius: radii.pill, flexDirection: 'row', gap: 4, paddingHorizontal: 12, paddingVertical: 8 },
  editText: { color: colors.accentInk, fontSize: 12, fontWeight: '800' },
  pressed: { opacity: 0.8 },
  table: { marginTop: spacing.xs },
  row: { alignItems: 'center', borderTopColor: colors.line, borderTopWidth: 1, flexDirection: 'row', paddingVertical: 7 },
  headRow: { borderTopWidth: 0 },
  head: { color: colors.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 0.7, textTransform: 'uppercase' },
  cell: { flex: 1, textAlign: 'right' },
  wide: { flex: 1.6 },
  metricCell: { flex: 1.5, textAlign: 'left' },
  metric: { color: colors.text, fontSize: 12, fontWeight: '700' },
  metricUnit: { color: colors.textDim, fontSize: 9, fontWeight: '700', marginTop: 1 },
  value: { color: colors.text, fontSize: 13, fontWeight: '700' },
  delta: { color: colors.accent, fontSize: 13, fontWeight: '800' },
  missing: { color: colors.textDim },
  notes: { color: colors.textMuted, fontSize: 12, fontStyle: 'italic', lineHeight: 17 },
  note: { color: colors.textDim, fontSize: 10, lineHeight: 14 },
  clubs: { gap: spacing.xs, marginTop: spacing.xs },
  subheading: { color: colors.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 0.8, textTransform: 'uppercase' },
  club: { borderTopColor: colors.line, borderTopWidth: 1, paddingTop: spacing.xs },
  clubHeader: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm, paddingVertical: 6 },
  clubName: { color: colors.text, flex: 1, fontSize: 14, fontWeight: '700' },
  clubSummary: { color: colors.textMuted, fontSize: 11 },
});
