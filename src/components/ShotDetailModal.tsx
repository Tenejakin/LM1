import Ionicons from '@expo/vector-icons/Ionicons';
import React from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { StrikeMap, TrajectoryChart } from '@/components/ShotVisuals';
import { Eyebrow, IconButton, MetricTile, Surface } from '@/components/ui';
import { getClub } from '@/data/clubs';
import { colors, radii, spacing } from '@/theme';
import { Shot } from '@/types';
import { metersToYards } from '@/utils/carry';

export function ShotDetailModal({ shot, onClose }: { shot: Shot | null; onClose: () => void }) {
  return (
    <Modal animationType="slide" onRequestClose={onClose} presentationStyle="pageSheet" visible={Boolean(shot)}>
      {shot ? <ShotDetail shot={shot} onClose={onClose} /> : null}
    </Modal>
  );
}

function ShotDetail({ shot, onClose }: { shot: Shot; onClose: () => void }) {
  const insets = useSafeAreaInsets();
  return (
    <View style={styles.root}>
      <ScrollView
        contentContainerStyle={[styles.content, { paddingTop: Math.max(insets.top, spacing.md) }]}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.header}>
          <View>
            <Eyebrow>Shot review</Eyebrow>
            <Text style={styles.title}>Shot #{shot.number}</Text>
            <Text style={styles.clubName}>{getClub(shot.clubId).label}</Text>
          </View>
          <IconButton icon="close" label="Close shot details" onPress={onClose} />
        </View>

        <Surface style={styles.hero}>
          <View style={styles.heroTop}>
            <View>
              <Eyebrow>Ball speed</Eyebrow>
              <View style={styles.speedRow}>
                <Text style={styles.speed}>{shot.ballSpeedMps.toFixed(1)}</Text>
                <Text style={styles.unit}>m/s</Text>
              </View>
              <Text style={styles.mph}>{(shot.ballSpeedMps * 2.23694).toFixed(1)} mph</Text>
            </View>
            <View style={styles.heroAside}>
              <Text style={styles.carryLabel}>Estimated carry</Text>
              <View style={styles.carryRow}>
                <Text style={styles.carryValue}>{shot.estimatedCarryM}</Text>
                <Text style={styles.carryUnit}>m</Text>
              </View>
              <Text style={styles.carryYards}>{metersToYards(shot.estimatedCarryM)} yd</Text>
              <View style={styles.quality}>
                <Ionicons name="shield-checkmark" size={14} color={colors.accent} />
                <Text style={styles.qualityValue}>{Math.round(shot.confidence * 100)}%</Text>
                <Text style={styles.qualityLabel}>confidence</Text>
              </View>
            </View>
          </View>
          <View style={styles.metricRow}>
            <MetricTile label="Club speed" value={shot.clubSpeedMps.toFixed(1)} unit="m/s" />
            <MetricTile label="Smash" value={shot.smashFactor.toFixed(2)} accent />
            <MetricTile label="Launch" value={shot.launchAngleDeg.toFixed(1)} unit="deg" />
          </View>
          <Text style={styles.carryNote}>Carry estimate excludes spin, wind, altitude and temperature.</Text>
        </Surface>

        <Surface style={styles.visualCard}>
          <View style={styles.visualHeader}>
            <View>
              <Eyebrow>Initial trajectory</Eyebrow>
              <Text style={styles.visualTitle}>Ball flight</Text>
            </View>
            <Ionicons name="navigate" size={19} color={colors.cyan} />
          </View>
          <TrajectoryChart shot={shot} />
        </Surface>

        <Surface style={styles.visualCard}>
          <View style={styles.visualHeader}>
            <View>
              <Eyebrow>Estimated contact</Eyebrow>
              <Text style={styles.visualTitle}>Clubface strike</Text>
            </View>
            <Ionicons name="locate" size={19} color={colors.accent} />
          </View>
          <StrikeMap shot={shot} />
        </Surface>

        <View style={styles.technicalHeader}>
          <Text style={styles.technicalTitle}>Capture details</Text>
          <Text style={styles.technicalNote}>For diagnosis & replay</Text>
        </View>
        <Surface style={styles.technicalCard}>
          <DetailRow label="Frames retained" value={`${shot.frameCount}`} />
          <DetailRow label="Capture window" value={`${shot.captureDurationMs} ms`} />
          <DetailRow label="Confidence" value={`${Math.round(shot.confidence * 100)}%`} accent />
          <DetailRow label="Captured" value={formatTimestamp(shot.capturedAt)} last />
        </Surface>

        <Pressable
          accessibilityRole="button"
          onPress={onClose}
          style={({ pressed }) => [styles.doneButton, pressed && styles.donePressed]}
        >
          <Text style={styles.doneText}>Done</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

function DetailRow({
  label,
  value,
  accent,
  last,
}: {
  label: string;
  value: string;
  accent?: boolean;
  last?: boolean;
}) {
  return (
    <View style={[styles.detailRow, last && styles.detailRowLast]}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={[styles.detailValue, accent && styles.detailAccent]}>{value}</Text>
    </View>
  );
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value));
}

const styles = StyleSheet.create({
  root: { backgroundColor: colors.background, flex: 1 },
  content: { paddingBottom: 50, paddingHorizontal: spacing.md },
  header: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.xl },
  title: { color: colors.text, fontSize: 28, fontWeight: '700', letterSpacing: -0.9, marginTop: 3 },
  clubName: { color: colors.accent, fontSize: 11, fontWeight: '800', marginTop: 2 },
  hero: { padding: spacing.lg },
  heroTop: { alignItems: 'flex-start', flexDirection: 'row', justifyContent: 'space-between' },
  speedRow: { alignItems: 'baseline', flexDirection: 'row', gap: 7, marginTop: 1 },
  speed: { color: colors.text, fontSize: 58, fontWeight: '700', letterSpacing: -3.4 },
  unit: { color: colors.textMuted, fontSize: 16, fontWeight: '700' },
  mph: { color: colors.textDim, fontSize: 11, fontWeight: '700', marginTop: -5 },
  heroAside: { alignItems: 'flex-end' },
  carryLabel: { color: colors.textMuted, fontSize: 9, fontWeight: '800', letterSpacing: 0.7, textTransform: 'uppercase' },
  carryRow: { alignItems: 'baseline', flexDirection: 'row', gap: 4, marginTop: 2 },
  carryValue: { color: colors.accent, fontSize: 35, fontWeight: '700', letterSpacing: -1.4 },
  carryUnit: { color: colors.textMuted, fontSize: 12, fontWeight: '700' },
  carryYards: { color: colors.textDim, fontSize: 10, fontWeight: '700', marginTop: -4 },
  quality: { alignItems: 'center', flexDirection: 'row', gap: 4, marginTop: 8 },
  qualityValue: { color: colors.text, fontSize: 11, fontWeight: '800' },
  qualityLabel: { color: colors.textDim, fontSize: 9, fontWeight: '600' },
  metricRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.lg },
  carryNote: { color: colors.textDim, fontSize: 9, lineHeight: 13, marginTop: spacing.sm },
  visualCard: { marginTop: spacing.sm, overflow: 'hidden', padding: spacing.lg },
  visualHeader: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  visualTitle: { color: colors.text, fontSize: 19, fontWeight: '700', marginTop: 3 },
  technicalHeader: { alignItems: 'flex-end', flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.md, marginTop: spacing.xl },
  technicalTitle: { color: colors.text, fontSize: 19, fontWeight: '700' },
  technicalNote: { color: colors.textDim, fontSize: 10, fontWeight: '600' },
  technicalCard: { paddingHorizontal: spacing.lg },
  detailRow: { borderBottomColor: colors.line, borderBottomWidth: 1, flexDirection: 'row', justifyContent: 'space-between', paddingVertical: spacing.md },
  detailRowLast: { borderBottomWidth: 0 },
  detailLabel: { color: colors.textMuted, fontSize: 12, fontWeight: '600' },
  detailValue: { color: colors.text, fontSize: 12, fontWeight: '800' },
  detailAccent: { color: colors.accent },
  doneButton: { alignItems: 'center', backgroundColor: colors.accent, borderRadius: radii.md, justifyContent: 'center', marginTop: spacing.xl, minHeight: 54 },
  donePressed: { opacity: 0.8, transform: [{ scale: 0.99 }] },
  doneText: { color: colors.accentInk, fontSize: 15, fontWeight: '800' },
});
